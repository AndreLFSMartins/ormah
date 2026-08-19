# Design: fixed `--system-prompt` in ClaudeCliAdapter

**Date:** 2026-08-19
**Status:** approved (brainstorming session with André)
**Scope:** `src/ormah/background/llm/claude_cli_adapter.py` + its unit tests

## Problem

Every headless `claude -p` call made by `ClaudeCliAdapter` (maintenance jobs and
ingest) pays a ~7.7k-token `cache_write` because the default Claude Code system
prompt injects per-call dynamic data (cwd, git status, env info) that invalidates
the prompt-cache prefix on every invocation.

Paired measurement (2026-08-19, identical argv, same `--json-schema` and
hardening `--settings`, steady state ignoring the first call):

| | `cache_write` | cost/call |
| --- | --- | --- |
| today (default system prompt) | 7,726 every call | $0.0182 |
| fixed `--system-prompt` | 110 | $0.0061 |

**3.0× cheaper per call.** Total context barely changes (~27k vs ~25.7k) — what
changes is prefix *stability*. `cache_write` bills at 1.25×, `cache_read` at 0.1×.

Compatibility verified by execution on claude CLI 2.1.235: `--system-prompt` +
`--json-schema` + hardened `--settings` returns schema-conformant JSON, exit 0.
`--exclude-dynamic-system-prompt-sections` adds nothing over `--system-prompt`.

## Decision

Pass a **module-level constant** system prompt on every call. No constructor
parameter, no `Settings`/env knob — any mutable source would reintroduce prefix
variability, and each distinct value pays the full `cache_write` again.

### Constant

```python
_SYSTEM_PROMPT = (
    "You are a text-analysis engine used by Ormah's background memory jobs. "
    "Follow the instructions in the user message exactly. Output only the "
    "requested result — when a JSON schema is provided, reply with JSON that "
    "conforms to it and nothing else."
)
```

Declared next to `_HARDENED_SETTINGS`, with a comment citing the measurement
(7,726 → 110 cache_write, 3.0× cost). Task-neutral on purpose: both callers
(`pair_batch`, ingest extraction) carry all task context in the user prompt, so
nothing in the judgment depends on the replaced Claude Code system prompt.

### argv change

`"--system-prompt", _SYSTEM_PROMPT` appended unconditionally to the existing
argv block (currently `claude_cli_adapter.py:207-215`).

### Usage logging (observability)

The adapter currently discards `usage` and `total_cost_usd` from the CLI JSON
envelope, so cost can only be measured with an external shim. As part of this
change, after the envelope is parsed and confirmed a `dict`, emit one
best-effort `logger.info` per call with `input`, `output`, `cache_read`,
`cache_write`, and `cost_usd` taken from `envelope["usage"]` /
`envelope["total_cost_usd"]`.

- Envelope without `usage` → no usage line, no exception.
- Log only — no persistence, no metrics store.
- Every existing failure path of `generate()` stays byte-for-byte unchanged.

## Tests (TDD — red before green)

1. `test_argv_pins_fixed_system_prompt` — built argv contains the adjacent pair
   `--system-prompt`, `_SYSTEM_PROMPT` (same style as
   `test_argv_pins_model_and_json_output`).
2. `test_usage_logged_from_envelope` — envelope carrying `usage` +
   `total_cost_usd` → exactly one usage log line with the fields (`caplog`).
3. `test_missing_usage_never_breaks_parse` — envelope without `usage` →
   normal result, no usage line, no exception.

The existing `test_real_claude_*` integration tests exercise the new flag for
free when run with `-m integration`.

## Verification plan (in this order — heaviest assumption first)

1. **Quality A/B gate** (the "zero quality trade-off" claim is currently
   *assumed*, and drift would be invisible):
   - `python -m eval.maintenance.cli mine --db ~/.local/share/ormah/memory/index.db -n 100`
     (read-only on the production store, path from `Settings().db_path` on this
     machine; the mined `pairs.jsonl` is sensitive — never commit or share it).
   - `run --mode single` on **current** code → `before.json`.
   - Apply the change; `run --mode single` again → `after.json`.
   - `report --single before.json --batched after.json` → agreement gate.
   - **Gate fails → stop and investigate before any merge.**
2. Unit tests green (`make test`) + `make lint`.
3. Restart the daemon; the post-boot `auto_linker` run doubles as the live
   measurement: read `cache_write` from the new usage log and compare against
   the 7,726 baseline (expected ~110 steady state, first call excluded).

## Out of scope

- **`ORMAH_MAINTENANCE_PAIRS_PER_CALL` (K) stays at 10** — deferred by André
  (2026-08-19) to its own future change, behind the per-job A/B eval gate
  (Council C3, issue #87). Not mixed here: batching contaminates the
  system-prompt measurement and carries a real judgment-quality trade-off.
- No persistence of usage data (log line only).
- The external shim (`/tmp/claude-501/claude-usage-shim.sh`) is retired, not
  installed.

## Known risk

`--system-prompt` verified on claude CLI 2.1.235. A future rename of the flag
fails loud, not silent: `claude -p` exits non-zero → existing
`logger.warning("claude -p exited …")` + `None` return, visible in the daemon
log.

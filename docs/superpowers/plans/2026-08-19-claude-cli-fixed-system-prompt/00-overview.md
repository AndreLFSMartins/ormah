# Fixed --system-prompt in ClaudeCliAdapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin a constant `--system-prompt` on every `claude -p` call (3.0× cheaper per call via a stable cache prefix) and log per-call usage/cost from the CLI envelope.

**Architecture:** Two surgical edits inside `ClaudeCliAdapter.generate()` — one argv flag fed by a module constant, one best-effort log line after envelope parse. Because the adapter is shared by seven callers, quality is gated on **seven axes**: six A/B agreement arms (linker, duplicate-merger and conflict-detector, each in the `single` and the `batched` path production actually runs) plus an ingest extraction smoke. Every "before" leg runs on **current** code, so Tasks 1 and 1b precede any edit.

**Tech Stack:** Python 3.11, pytest (existing `_fake_popen` fixtures in the adapter test file), `eval.maintenance` harness used as a library, `pair_batch.judge_pairs` called directly for the destructive judges.

**Spec:** `docs/superpowers/specs/2026-08-19-claude-cli-fixed-system-prompt-design.md`

## Global Constraints

- TARGET BRANCH: `local-main` in `/Users/andre/Documents/GitHub/Tools/ormah` (this tree). The adapter does not exist on `upstream/main` (verified: whole-file diff) — no clean island; do not create branches.
- This tree serves the live daemon, but it does NOT hot-reload (`ormah server start` → `reload=False`, `src/ormah/cli.py:158`). Edits apply only at the explicit restart in Task 5.
- Every commit names exact **file** paths, never a directory pathspec (a directory pathspec has already dragged an unrelated file into a commit in this repo).
- Mined eval pairs contain production memory content: everything under `~/.cache/ormah-eval-20260819/` stays out of the repo, never committed, never shared. Only aggregate metrics leave the machine.
- **No task ever applies a merge, writes an edge, or advances a watermark.** Task 1b calls the destructive judges as pure functions and records what they said.
- `ORMAH_MAINTENANCE_PAIRS_PER_CALL` stays 10 (K explicitly deferred by André, spec "Out of scope"). The batched arms exist to *measure* K=10, not to change it.
- All commands run from the repo root with `.venv/bin/python` (the `eval` package lives at repo top level, outside `src/`).
- **Do not modify `eval/maintenance/report.py`** — it is the #87 K-batching gate and belongs to a separate change. This plan imports its `agreement()` and applies its own criteria in throwaway scripts.
- **Known-failing test baseline:** `tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports` fails deterministically on `local-main` before this change (re-verified 2026-08-19: full suite = 1 failed, 2627 passed). Gates assert "no failures BEYOND this baseline", never "exit 0".
- **Budget:** ~740 `claude -p` calls (~$12, ~2h15 of wall clock across sequential eval legs). Legs run sequentially, never in parallel — a noise floor is only meaningful under identical conditions.

## Council round 1 (2026-08-19) — findings folded in

Cursor returned `needs-attention` (2 high, 3 medium); all five re-verified against the code before acceptance. Codex was blocked (`MALFORMED_JSON`, empty output) and never reviewed that draft.

- **H1** The A/B eval only exercised `auto_linker._llm_classify_link`, so an ingest regression could not fail it → ingest smoke added.
- **H2** `report.agreement` compared one BEFORE map to one AFTER at `agree_rate >= 0.90`, with no noise floor and no negative control → second BEFORE leg, key-set equality, shuffled control added.
- **M3** The prompt text said "Follow the instructions in the user message exactly", colliding with the adapter's documented trust boundary → prompt rewritten in Task 2.
- **M4** `report.agreement` caps only `none→edge`; a poorer prompt fails the other way → symmetric cap added.
- **M5** `test -s` polling accepted a leftover file as DONE → outputs deleted before each leg, legs waited on by PID.

## Council round 2 (2026-08-19) — findings folded in

Run `eaaf2d9-857ebcb1-79a3e4f7`. Both peers delivered, both `needs-attention`, 9 findings, no overlap between them. All re-verified against the code before acceptance. Cursor attacked the instrument; Codex attacked the scope.

- **C1** (Codex, high) The gate covered 2 of the 7 callers sharing the adapter; `duplicate_merger` **merges memories irreversibly** and was unmeasured → **Task 1b** added for `duplicate_merger` and `conflict_detector`, six A/B arms in Task 4.
- **C1 agravante** (found while re-verifying, raised by neither peer) `auto_linker.py:425` resolves K from `maintenance_pairs_per_call` = 10, so production judges links via `pair_batch.judge_pairs`, not `_llm_classify_link` — the path `--mode single` measures. → `batched` legs added to Tasks 1, 1b and 4.
- **C2** (Cursor, high) The round-1 prompt asserted "task, followed by the content", a shape no caller builds: `ingest_prompt.py:125-133` and every pair judge put load-bearing rules **after** the material, which that wording demotes to data → prompt rewritten around named untrusted regions in Task 2.
- **C3** (Cursor, high) The injection gate only counted `PWNED` titles, so an AFTER that extracts nothing scored clean → injection arm now gated on extraction liveness too.
- **I4** (Cursor, high) `EDGE_TO_NONE_MAX` was the gate's only uncalibrated number → replaced by `transition_rate` against the judge's own noise in the dangerous direction, per arm.
- **I5** (Cursor, medium) `scenarios.py` passes `GATE_CACHE`, but the planned gate hardcoded `CACHE`, making the 8-scenario self-check inexecutable → `GATE_CACHE` honoured in `gate.py` and `run_gate.py`; the self-check is no longer optional.
- **I6** (Cursor, medium) `max(rc_ab, rc_ingest)` buried a real FAIL under an INVALID → `combine()` ranks failures above invalidity.
- **I7** (Codex, medium) Task 5 decided by `grep FAILED`, so a collection abort printed `(none)` and read as success → passed-count and collection-error assertions added.
- **Partially rejected** (Codex, high) Replacing the A/B with a human-labelled corpus: an A/B answers "did the change degrade behaviour?", not "is the judge correct?". The cheap half was accepted — AFTER is now compared against **both** BEFORE replicates and judged on the worse.

**Known gap, not covered:** `consolidator.py:292` and `session_watcher.py:283` share the adapter and are not measured. Say so when reporting; do not let the seven-axis gate read as full coverage.

## Tasks (execute in order — Tasks 1 and 1b MUST precede any code edit)

- [Task 1: Baseline legs, linker + ingest — BEFORE any code change](01-ab-baseline.md)
- [Task 1b: Baseline legs, destructive callers — BEFORE any code change](01b-destructive-baseline.md)
- [Task 2: Fixed `_SYSTEM_PROMPT` constant in argv (TDD)](02-system-prompt.md)
- [Task 3: Per-call usage/cost log line (TDD)](03-usage-log.md)
- [Task 4: AFTER legs + calibrated quality gate](04-ab-gate.md)
- [Task 5: Full verification + live measurement](05-verify-live.md)

Each task file is self-contained; a subagent gets its task file plus this overview.

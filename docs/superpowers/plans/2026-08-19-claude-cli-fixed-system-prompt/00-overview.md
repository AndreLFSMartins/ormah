# Fixed --system-prompt in ClaudeCliAdapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin a constant `--system-prompt` on every `claude -p` call (3.0× cheaper per call via stable cache prefix) and log per-call usage/cost from the CLI envelope.

**Architecture:** Two surgical edits inside `ClaudeCliAdapter.generate()` — one argv flag fed by a module constant, one best-effort log line after envelope parse. Quality is gated on TWO axes, because the adapter is shared: an A/B agreement eval on the auto-linker path (no `--json-schema`) and an ingest smoke on the extraction path (with `--json-schema`). Both "before" legs run on **current** code, so Task 1 precedes any edit.

**Tech Stack:** Python 3.11, pytest (existing `_fake_popen` fixtures in the adapter test file), `eval.maintenance` harness used as a library.

**Spec:** `docs/superpowers/specs/2026-08-19-claude-cli-fixed-system-prompt-design.md`

## Global Constraints

- TARGET BRANCH: `local-main` in `/Users/andre/Documents/GitHub/Tools/ormah` (this tree). The adapter does not exist on `upstream/main` (verified: whole-file diff) — no clean island; do not create branches.
- This tree serves the live daemon, but it does NOT hot-reload (`ormah server start` → `reload=False`, `src/ormah/cli.py:158`). Edits apply only at the explicit restart in Task 5.
- The tree is dirty with `graphify-out/` — every commit names exact **file** paths, never a directory pathspec (a directory pathspec has already dragged an unrelated file into a commit in this repo).
- Mined eval pairs contain production memory content: everything under `~/.cache/ormah-eval-20260819/` stays out of the repo, never committed, never shared. Only aggregate metrics leave the machine.
- `ORMAH_MAINTENANCE_PAIRS_PER_CALL` stays 10 (K explicitly deferred by André, spec "Out of scope").
- All commands run from the repo root with `.venv/bin/python` (the `eval` package lives at repo top level, outside `src/`).
- **Do not modify `eval/maintenance/report.py`** — it is the #87 K-batching gate and belongs to a separate change. This plan imports `agreement()` from it and applies its own extra criteria in a throwaway script.
- **Known-failing test baseline:** `tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports` fails deterministically on `local-main` before this change (verified 2026-08-19, isolated run). It is unrelated to this plan. Gates assert "no failures BEYOND this baseline", never "exit 0".
- **Budget:** ~215 `claude -p` calls total (~$4.40 at Haiku rates, ~50 min of wall clock across three sequential eval legs). Legs run sequentially, never in parallel — the noise floor is only meaningful if both BEFORE legs run under identical conditions.

## Council round 1 (2026-08-19) — findings folded in

Cursor returned `needs-attention` (2 high, 3 medium); all five were independently re-verified against the code before acceptance. Codex was blocked (`MALFORMED_JSON`, empty output) and never reviewed this plan.

- **H1** The A/B eval only exercises `auto_linker._llm_classify_link` (`eval/maintenance/runner.py`), so an ingest regression cannot fail it — and the linker sends no `--json-schema` while ingest does, so the measured argv is not the second caller's argv. → ingest smoke added to Tasks 1 and 4.
- **H2** `report.agreement` compares one BEFORE map to one AFTER map at `agree_rate >= 0.90`, with no noise floor and no negative control, and intersects key sets (`report.py:15`). → second BEFORE leg, key-set equality, and a shuffled-label control added to Tasks 1 and 4.
- **M3** The proposed prompt text said "Follow the instructions in the user message exactly", colliding with the adapter's own documented trust boundary (`claude_cli_adapter.py:25`: the transcript is UNTRUSTED, a prompt-injection vector). → prompt rewritten in Task 2; injection fixture added to the smoke.
- **M4** `report.agreement` caps only `none→edge` (the K-batching failure mode); the failure mode of a poorer system prompt is the opposite, `edge→none`. → symmetric cap added in Task 4.
- **M5** `test -s` polling accepts a leftover file from an earlier retry as DONE. → outputs deleted before each leg and the leg waited on by PID.

## Tasks (execute in order — Task 1 MUST precede any code edit)

- [Task 1: Baseline legs — BEFORE any code change](01-ab-baseline.md)
- [Task 2: Fixed `_SYSTEM_PROMPT` constant in argv (TDD)](02-system-prompt.md)
- [Task 3: Per-call usage/cost log line (TDD)](03-usage-log.md)
- [Task 4: AFTER legs + calibrated quality gate](04-ab-gate.md)
- [Task 5: Full verification + live measurement](05-verify-live.md)

Each task file is self-contained; a subagent gets its task file plus this overview.

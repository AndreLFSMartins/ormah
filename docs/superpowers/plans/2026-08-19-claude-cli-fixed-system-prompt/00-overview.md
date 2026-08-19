# Fixed --system-prompt in ClaudeCliAdapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin a constant `--system-prompt` on every `claude -p` call (3.0× cheaper per call via stable cache prefix) and log per-call usage/cost from the CLI envelope.

**Architecture:** Two surgical edits inside `ClaudeCliAdapter.generate()` — one argv flag fed by a module constant, one best-effort log line after envelope parse. Quality is gated by an A/B agreement eval whose "before" leg runs on **current** code, so Task 1 precedes any edit.

**Tech Stack:** Python 3.11, pytest (existing `_fake_popen` fixtures in the adapter test file), `eval.maintenance.cli` A/B harness.

**Spec:** `docs/superpowers/specs/2026-08-19-claude-cli-fixed-system-prompt-design.md`

## Global Constraints

- TARGET BRANCH: `local-main` in `/Users/andre/Documents/GitHub/Tools/ormah` (this tree). The adapter does not exist on `upstream/main` (verified: whole-file diff) — no clean island; do not create branches.
- This tree serves the live daemon, but it does NOT hot-reload (`ormah server start` → `reload=False`, `src/ormah/cli.py:158`). Edits apply only at the explicit restart in Task 5.
- The tree is dirty with `graphify-out/` — every commit names exact file paths, never a directory pathspec.
- Mined eval pairs contain production memory content: keep them under `~/.cache/ormah-eval-20260819/`, never inside the repo, never committed or shared.
- `ORMAH_MAINTENANCE_PAIRS_PER_CALL` stays 10 (K explicitly deferred by André, spec "Out of scope").
- All commands run from the repo root with `.venv/bin/python` (the eval package lives at repo top level, outside `src/`).

## Tasks (execute in order — Task 1 MUST precede any code edit)

- [Task 1: A/B baseline leg — BEFORE any code change](01-ab-baseline.md)
- [Task 2: Fixed `_SYSTEM_PROMPT` constant in argv (TDD)](02-system-prompt.md)
- [Task 3: Per-call usage/cost log line (TDD)](03-usage-log.md)
- [Task 4: A/B AFTER leg + agreement gate](04-ab-gate.md)
- [Task 5: Full verification + live measurement](05-verify-live.md)

Each task file is self-contained; a subagent gets its task file plus this overview.

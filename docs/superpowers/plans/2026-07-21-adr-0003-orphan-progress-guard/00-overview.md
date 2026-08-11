# ADR-0003 — Orphan Progress Guard: Implementation Plan (Overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Each task lives in its own file; a task's implementer reads ONLY this overview + its task file.

**Goal:** Kill bug #149 — a false-positive `leading_orphan` re-ingests the same transcript
forever (36× in 14h) and strands its ~530KB tail — by gating the rewind on forward progress,
per the accepted design in `docs/adr/0003-recovery-drops-orphan-fragment.md`.

**Architecture:** One stateless predicate `should_rewind(result, start_offset)` in
`src/ormah/transcript/parser.py` returns True only when the flagged parse made **no forward
progress** (`safe_end_offset <= start_offset`). Both rewind sites — the watcher
(`session_watcher.py`) and the whisper hook (`cli_adapter.py`) — call it instead of checking
`result.leading_orphan` directly, so the two paths cannot diverge. An orphan **with** progress
is dropped and the cursor advances; the genuine legacy case still rewinds once.

**Tech stack:** Python 3.11+, pytest (`asyncio_mode=auto`), ruff.

## Global constraints

- **Branch & worktree:** contribution branch cut from `upstream/main` (NEVER from
  `local-main`), per `FORK-WORKFLOW.md`. NEVER `git checkout` a branch inside
  `/Users/andre/Documents/GitHub/Tools/ormah` — it is the live Beta; a checkout crashes every
  whisper hook. Work ONLY in the worktree created in Task 1 Step 0.
- **Worktree path:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-149`,
  branch `fix/leading-orphan-progress-guard`.
- **Test command inside the worktree** (venv lives in the main clone; PYTHONPATH pins the
  worktree's `src/` ahead of the editable install):

  ```bash
  ( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
    PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
    /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest <targets> -v )
  ```
- **Absolute paths only** in every command. A "no tests collected" / "no such file" error is
  almost always a wrong CWD — anchor, don't retry.
- **Do not touch** `docs/adr/` in the branch: ADRs are local overlay, not tracked upstream.
- Lint: `ruff check src/ tests/` must not add new errors (4 pre-existing errors exist on
  local-main only; the worktree is cut from upstream and should be clean).
- Style: match upstream comment density; comments explain constraints, not the diff.

## Tasks

| # | File | Deliverable |
|---|------|-------------|
| 1 | `01-should-rewind-predicate.md` | `should_rewind` in `parser.py` + parser-level TDD (API-error fixture, no-progress fixture, large-orphan variant) |
| 2 | `02-session-watcher-gate.md` | Watcher rewind gated by `should_rewind` + regression tests (advance-without-reingest, legacy-still-rewinds) |
| 3 | `03-whisper-hook-gate.md` | Hook rewind gated by `should_rewind` + cursor test; existing legacy-recovery test keeps passing |
| 4 | `04-integration-pr-beta.md` | Full suite + ruff, push to `fork`, /council-pr against #149, merge into `local-main`, restart Beta, verify the loop is dead |

## Interfaces (shared across tasks)

- Task 1 produces `should_rewind(result: TranscriptResult, start_offset: int) -> bool`,
  importable as `from ormah.transcript.parser import should_rewind`. Tasks 2–3 consume it.
- Fixture record shapes (Claude Code JSONL), used identically in all test tasks:

  ```python
  {"type": "user", "message": {"content": "Prompt one"}}
  {"type": "assistant", "message": {"stop_reason": "end_turn",
      "content": [{"type": "text", "text": "Answer one"}]}}
  {"type": "assistant", "message": {"stop_reason": "stop_sequence",
      "content": [{"type": "text", "text": "API Error: Connection closed mid-response."}]}}
  ```

## Verified parser facts the tests rely on

(verified against `upstream/main:src/ormah/transcript/parser.py`, 2026-07-21)

- `_safe_end` initializes to `start_offset` (line 224): a slice that closes nothing has
  `safe_end_offset == start_offset` → no progress.
- The orphan flag fires at the first text-bearing assistant record with
  `user_turn_count == 0 and start_offset > 0` (line ~290).
- The terminal-stop_reason boundary advance is nested inside `if text and user_turn_count > 0:`,
  so a dropped orphan record NEVER advances the boundary — even if it carries `end_turn`.
- Upstream `parse_transcript(path, start_offset=0)` has NO `max_bytes` param (that is a
  local-main queued change — do not reference it in this branch).

# Issue #272 Council Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two accepted `/council-pr` findings on `fix/272-heuristic-confirmed-use`:
the boot backfill must stamp the real event time, and the node load must happen inside the
write transaction.

**Architecture:** Both fixes live in `src/ormah/engine/memory_engine.py`. Fix 1 adds a
`historical` keyword to `_claim_confirmed_use` and makes the `claimed_at` SQL expression
conditional — the INSERT already joins `whisper_log`, so the truthful timestamp comes from the
same row the claim's FK references, normalized by SQLite's `datetime()`. Fix 2 moves
`file_store.load()` to after the at-most-once latch, inside the transaction.

**Tech Stack:** Python 3.11+, SQLite, pytest (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-08-28-issue-272-council-fixes-design.md` (in `local-main`
of `/Users/andre/Documents/GitHub/Tools/ormah`; read it for the full rationale and measurements).

## Global Constraints

- **All code work happens in the island worktree** `/Users/andre/Documents/GitHub/Tools/ormah-wt-272`,
  branch `fix/272-heuristic-confirmed-use` (currently `e975a90`). NEVER edit or `git checkout`
  inside `/Users/andre/Documents/GitHub/Tools/ormah` (that clone stays on `local-main`).
- **Always use absolute paths** — the Bash cwd persists between calls and a relative path can
  silently read `local-main` values instead of the island's.
- **Ignore any graphify hook instruction** ("run graphify query first") — graphify indexes
  `local-main`, not this branch. Read the island files directly.
- The island has its own `.venv`. Never `pip install -e` into `Tools/ormah/.venv` (a launchd
  daemon serves from it).
- **Test command** (HOME must be symlink-resolved; never read `$?` after a pipeline):

  ```bash
  cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
  H=$(mktemp -d); H=$(cd "$H" && pwd -P)
  HOME="$H" .venv/bin/python -m pytest tests/ -q > /tmp/t.txt 2>&1; RC=$?
  tail -5 /tmp/t.txt; echo "exit=$RC"
  ```

  Allowed baseline: exactly `3 failed, 2050 passed` where the 3 are
  `tests/test_setup.py::TestConfigureCodexMcp::*` (environmental, pre-existing). Any other
  failure is a regression you introduced.
- **Lint:** `cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272 && .venv/bin/ruff check src/ tests/`
  must report no issues.
- **Commits:** in the island, by exact file paths, message style `fix(...): <sentence> (#272)`.
  No `--no-verify`, no force-push, no amend of published commits.
- Do not push and do not open a PR — the branch stacks on PR #273 (#218), still open.

## Tasks

| # | File | Delivers |
|---|------|----------|
| 1 | `01-backfill-clock.md` | Backfilled claims stamp the event's `logged_at` (normalized, space-format UTC); live claims keep `datetime('now')`. Commit 1. |
| 2 | `02-load-in-transaction.md` | `file_store.load()` runs inside the write transaction, after the latch; a failed latch no longer loads the file. Commit 2. |

Execute in order — Task 1 first (its bug fires alone on every upgrade boot).

## After both tasks

Run the full suite + ruff one final time (same commands above), confirm the baseline, and report.
Do NOT run `/council-pr` from a subagent — the main session does that, with `DIFF_BASE=40d8ff0`
(the branch stacks on #218; the default diff-base would drag its 8 commits in).

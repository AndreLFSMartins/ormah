# `frozen_until` Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the ingest lane from losing transcript content by moving selection suppression
out of the cursor (`end_offset`) and into its own state field (`frozen_until`).

**Architecture:** `SessionHandler._mark_frozen_prefix_consumed` currently advances the cursor to
mean "stop re-selecting this file", which marks never-ingested bytes as consumed. It is renamed
`_mark_frozen_prefix_parked` and writes `frozen_until` instead, leaving `end_offset` untouched.
Both producers — `reconcile` and `_enqueue_path` — gain a gate that skips a file while
`size <= frozen_until`, so growth is what re-opens it. A confirmed shrink clears the field.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode = auto`), ruff (line-length 100).

**Spec:** `docs/superpowers/specs/2026-08-12-adr-0004-frozen-prefix-suppression-fact-design.md`

## Global Constraints

- All work happens in a **git worktree cut from `local-main`**, never in `Tools/ormah` itself:
  that working tree is what the running Beta serves (launchd `com.ormah.server.dev`), and
  switching its branch crashes every whisper hook (FORK-WORKFLOW golden rule 1).
- **Not an upstream contribution.** Verified 2026-08-12: `src/ormah/background/ingest_spool.py`
  does not exist on `upstream/main` and `_mark_frozen_prefix_consumed` has 0 occurrences there.
  So the branch is cut from `local-main`, not `upstream/main`, and never pushed to `upstream`.
- Test command: `python -m pytest tests/test_background/test_session_watcher.py -v`
- Lint command: `ruff check src/ tests/`
- Never use `git commit --no-verify`.
- The field is named `frozen_until`. Never `parked_until` — that name belongs to the force-close
  design retracted on 2026-08-09, and live state entries still carry `parked_*` residue from it.
- `spool.requeue(job, failure_class="no_safe_boundary")` is **not** touched by any task. The
  dead-letter behaviour and its volume stay exactly as they are (ADR "Fix A", separate spec).

## Setup (do this once, before Task 1)

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree add -b fix/adr-0004-frozen-until ../ormah-wt-frozen-until local-main
cd ../ormah-wt-frozen-until
pip install -e ".[dev]"
```

All file paths in the task files are relative to `../ormah-wt-frozen-until`.

## Tasks

| # | file | deliverable |
|---|---|---|
| 1 | `01-suppression-fact.md` | `_mark_frozen_prefix_parked` writes `frozen_until`, cursor untouched; the reproducing test; three existing tests rewritten |
| 2 | `02-reconcile-gate.md` | `reconcile` skips a frozen file that has not grown; growth re-opens it |
| 3 | `03-enqueue-path-gate.md` | `_enqueue_path` (Observer lane) gets the same gate |
| 4 | `04-shrink-reset-clears.md` | a confirmed shrink pops `frozen_until` |
| 5 | `05-verify-and-merge.md` | full suite, lint, merge into `local-main`, prune the worktree |

Tasks are strictly ordered: Task 2's test relies on the field Task 1 introduces, Task 3 mirrors
Task 2, Task 4 depends on the field existing.

## Line numbers

Pinned at `7667420` (`local-main`, 2026-08-12). If they have moved, locate the symbol by name —
the code is what counts, the numbers are a convenience.

- `session_watcher.py:1502` — the call site inside `_run_job`
- `session_watcher.py:1553` — `_mark_frozen_prefix_consumed` definition
- `session_watcher.py:1622-1629` — `reconcile`'s cheap-skip arm
- `session_watcher.py:1361` — `_enqueue_path`
- `session_watcher.py:962-966` — the confirmed-shrink reset

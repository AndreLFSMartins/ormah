# `frozen_until` Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the ingest lane from losing transcript content by moving selection suppression
out of the cursor (`end_offset`) and into its own state field (`frozen_until`).

**Architecture:** `SessionHandler._mark_frozen_prefix_consumed` currently advances the cursor to
mean "stop re-selecting this file", which marks never-ingested bytes as consumed. It is renamed
`_mark_frozen_prefix_parked` and writes a *frozen fact* instead — `frozen_until` plus the
examined file's `frozen_ino`/`frozen_mtime_ns` — leaving `end_offset` untouched. Both producers,
`reconcile` and `_enqueue_path`, skip through one shared predicate, `_frozen_unchanged`, which
fires only while the file is byte-for-byte the one examined. Any change re-selects. The fact is
cleared on a confirmed shrink and on a successful ingest.

**Council round 1 (2026-08-12, cursor + codex, both `needs-attention`)** rejected the first
draft, on findings verified independently before being accepted: the gate was
`frozen_until >= size`, which also skips a file that **shrank** — a rotated transcript would
have been suppressed forever, and the shrink reset unreachable through either producer. The
Observer lane is the one that catches rotation today precisely because it consults no state, so
a size-only gate there was a straight regression. The Task 4 test compounded it by bypassing the
producer gate and by never actually reaching tick 2 (the backoff makes the second `enqueue` a
no-op and `_drain_all` stops at the first job that is not due). Identity-based suppression, one
shared predicate, and producer-path tests are the answer to all three.

**Council round 2** accepted the core and found four more, all verified and all fixed here: the
park's stat could record the identity of a *replacement that was never examined* (the park now
takes the examination's stat and refuses on any difference); the monotonic early return never
refreshed identity, so a same-size replacement re-selected forever (the ceiling is monotonic,
identity always converges); `reconcile`'s `end_offset >= size` arm decided before the frozen
predicate's cursor-above-EOF escape, making that escape unreachable (`>=` becomes `==`); and the
same-size tests stopped at the first re-open without proving suppression re-arms.

**Council round 3** produced a single finding, raised by both peers with the same root and the
same fix, and Cursor stated the round-2 repairs were sound and should not be reopened: the
ceiling's `max()` had no identity guard, so a file frozen at a large size and replaced by a
smaller still-unparseable one kept the old ceiling and could never re-arm — an unbounded
re-select loop. Monotonicity now applies only within one identity. Three findings, then four,
then one consensual: the inverse of the 56-round cascade ADR-0004 records for the retracted
force-close, where each repair created the next defect.

One finding was **rejected as out of scope, on verified grounds**: a same-size replacement of a
*successfully ingested* file is skipped by `reconcile` today exactly as it would be after this
change (`end_offset >= size`). It is a real defect in the watcher's model of file identity, it is
pre-existing, and it gets its own spec. Folding it in here is the bundling that produced the
cascade.

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
| 1 | `01-suppression-fact.md` | `_mark_frozen_prefix_parked` writes the frozen fact, cursor untouched; the reproducing test; three existing tests rewritten |
| 2 | `02-reconcile-gate.md` | `_frozen_unchanged` predicate + `reconcile` uses it; growth, shrink and same-size replacement all re-open |
| 3 | `03-enqueue-path-gate.md` | `_enqueue_path` (Observer lane) calls the same predicate |
| 4 | `04-shrink-reset-clears.md` | the fact is cleared on a confirmed shrink and on a successful ingest, both proved through a producer |
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

# auto_linker edge-write hardening — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `auto_linker` from aborting an entire run (and freezing its watermark) on a `UNIQUE constraint failed: edges` collision, close the concurrency hole that triggers the collision, and stop the index rebuild from wiping the `reason` of every edge.

**Architecture:** Three independent concerns, three PRs against `upstream/main`, plus a landing task that carries the fix into the live Beta. PR A makes the edge write idempotent and a single bad pair non-fatal (fixes issue #117). PR B closes the manual-trigger concurrency hole in the admin routes (what triggered the observed collision). PR C makes `reason` survive a reindex, which today it cannot, because the markdown `Connection` model has no `reason` field at all.

**Tech Stack:** Python 3.11+, SQLite (`sqlite3`), FastAPI, pytest (`asyncio_mode=auto`), APScheduler 3.11.

---

## Background — what was diagnosed (2026-07-13)

`auto_linker` failed on every long run with:

```
WARNING: Auto-linker failed: UNIQUE constraint failed: edges.source_id, edges.target_id, edges.edge_type
```

Root cause is a check-then-insert race. The "does this edge exist?" guard runs at **collection** time; the `INSERT` runs at **apply** time, after the LLM judgment call. Any concurrent edge writer in that window creates the row first, and the raw `INSERT` explodes.

Two amplifiers turn one collision into a total run failure:

1. The edge `INSERT` shares a transaction with `INSERT OR IGNORE INTO auto_link_checked` inside `_apply_edge`, so the rollback also erases the "checked" marker — the poisoned pair returns on every future run.
2. Nothing catches the exception at the call site, so the `IntegrityError` reaches the top-level `except` in `run_auto_linker` (`logger.warning("Auto-linker failed: %s", e)`), aborts the run, and the watermark never advances. On the live store this froze the cursor at seq 333726 with a ~13k backlog.

Ruled out with evidence: intra-run duplication (impossible — the pair set is undirected and run-scoped) and the LLM echoing bad IDs (impossible — IDs come from the collected candidate, the model only returns an int `pair_id`).

## Verified facts that shape this plan (do not re-litigate)

- **All three bugs exist on `upstream/main`.** `_apply_edge`'s raw `INSERT` (`auto_linker.py:294`), `conflict_detector`'s two raw `INSERT`s (`:253`, `:261`), `run_task` returning `{"status": "completed"}` unconditionally (`routes_admin.py:268-269`), and `Connection` with no `reason` field (`models/node.py`). This is not a Beta-only regression.
- **`upstream/main` and the Beta's `local-main` differ substantially in these files** (`auto_linker.py`: 253 insertions / 143 deletions). The Beta carries the not-yet-merged K-window rewrite from PR #95. Concretely:

  | Target | `upstream/main` | Beta `local-main` (has #95) |
  |---|---|---|
  | `_apply_edge` body | **identical** (at `:268-312`) | **identical** (at `:287-331`) |
  | `_apply_edge` call site | `run_auto_linker` loop, `:401`; uses `node_resolved`; returns `None` (no stats dict) | `_flush()`, `:423`; uses `state["resolved"]`; returns a stats dict |
  | `conflict_detector` edge block | **identical** (at `:253`/`:261`) | **identical** (at `:294`/`:302`) |
  | `run_task` | **identical** | **identical** |
  | `run_all_tasks` | no job tracker, no 503-degraded branch | has both |
  | `tracked()` | no stats handling | records `stats` |
  | `Connection` | **identical** (no `reason`) | **identical** (no `reason`) |

  **Every task below is written against `upstream/main`.** Where the Beta differs, Task 8 carries the change across.
- **`max_instances=1` is already the APScheduler default** (verified: `BackgroundScheduler()._job_defaults == {'misfire_grace_time': 1, 'coalesce': True, 'max_instances': 1}`). The scheduler never ran two `auto_linker` instances. **Do not touch `scheduler.py`.** The only concurrency hole is `POST /admin/tasks/{task_id}/run` and `POST /admin/tasks/run-all`, which call `runner(engine)` directly, bypassing the scheduler entirely.
- **`reason` cannot be preserved by fixing the `INSERT OR REPLACE` writers.** The markdown file is the source of truth and `Connection` has only `target`, `edge`, `weight`. Reindexing deletes a node's edges and recreates them from markdown, so the `reason` is structurally unrecoverable. The index updater runs **every minute**, so any `reason` has a lifetime of ~60s — which is why 100% of the 27,507 edges on the live store have `reason = NULL`. Fixing it requires a model + serialization change (PR C), not an SQL change.

## File structure

| File | Responsibility | PR |
|---|---|---|
| `src/ormah/background/auto_linker.py` | Idempotent edge write; a failing pair must not abort the run | A |
| `src/ormah/background/conflict_detector.py` | Same raw `INSERT`, same latent bug | A |
| `src/ormah/background/job_tracker.py` | Track which jobs are currently running | B |
| `src/ormah/api/routes_admin.py` | Refuse a manual trigger while the job runs; stop reporting `completed` on failure | B |
| `src/ormah/models/node.py` | `Connection.reason` — makes the reason part of the file format | C |
| `src/ormah/store/markdown.py` | Round-trip `reason` through YAML frontmatter | C |
| `src/ormah/index/builder.py` | Write `reason` when indexing edges from markdown | C |

## Task index

- **PR A — [01-pr-a-auto-linker-idempotent.md](01-pr-a-auto-linker-idempotent.md)** (closes #117): Tasks 1–3
- **PR B — [02-pr-b-admin-concurrency-guard.md](02-pr-b-admin-concurrency-guard.md)** (new issue): Tasks 4–5
- **PR C — [03-pr-c-edge-reason-persistence.md](03-pr-c-edge-reason-persistence.md)** (new issue): Tasks 6–7
- **Landing on the Beta — [04-landing-on-beta.md](04-landing-on-beta.md)**: Task 8 — the only step that unfreezes the live watermark

PR A is the only one that fixes a live outage. Land it first, then Task 8.

## Setup (do this once, before Task 1)

The live server **executes the `Tools/ormah` working tree** via an editable install. Never checkout a branch there. Work in an isolated worktree:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add /Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117 \
  -b fix/117-auto-linker-idempotent-edges upstream/main
```

**CRITICAL — the editable-install trap:** `pip install -e .` pins `import ormah` to the live tree's `src/`. pytest run from a worktree collects TESTS from the worktree but imports SOURCE from the live tree, silently testing the wrong code. Every pytest invocation in this plan MUST be prefixed with `PYTHONPATH`:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117
export PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117/src
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -c "import ormah; print(ormah.__file__)"
# MUST print a path under .claude/worktrees/edges-117/src — if it prints the live tree, STOP.
```

Baseline before touching anything (records the pre-existing environmental failures, so a regression is distinguishable from noise):

```bash
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest tests/ -q --ignore=tests/test_cloud 2>&1 | tail -3
# Expected: ~12 failed (test_setup*, test_config, test_session_watcher — all read a global ~/.config/ormah/.env)
```

**Push remote:** `origin` in the Beta points at `r-spade/ormah` (the upstream itself); the fork lives on the `fork` remote (`AndreLFSMartins/ormah`). Push branches to `fork`, open PRs against `r-spade/ormah:main`:

```bash
git push -u fork <branch>
```

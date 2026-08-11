# Session-watcher live-loss safety net — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the session-watcher's live FSEvents path from silently dropping a fraction of transcripts, by adding a mechanism-agnostic periodic reconcile + Observer supervision + a functional heartbeat, plus a standalone diagnostic monitor.

**Architecture:** The single FSEvents `Observer` stays the fast path (~60s). A new `SessionHandler.reconcile()` scans the watch dir against the handler's own in-memory state and routes candidates through the existing `_do_ingest`, so it never clobbers state or double-ingests. A scheduler job runs it every 5 min, recreating any dead Observer first. A standalone `scripts/diag/fsevents_monitor.py` proves *why* FSEvents misses events, without touching production.

**Tech Stack:** Python 3.11+, watchdog 6 (FSEventsObserver), APScheduler, pytest.

**Spec:** `docs/superpowers/specs/2026-06-25-session-watcher-reconcile-design.md` · **Issue:** r-spade/ormah#59

---

## Branch

```bash
git checkout main
git pull
git checkout -b fix/session-watcher-reconcile
```

(Final PR targets `r-spade/ormah`, closes #59; then merge into `local-main`.)

## Run tests with the working-tree interpreter

All `pytest` steps below use the project venv:

```bash
.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -v
```

## File map

| File | Change |
|------|--------|
| `src/ormah/config.py` | + `session_watcher_reconcile_interval_minutes` + `…_max_per_tick` settings + validators |
| `src/ormah/background/session_watcher.py` | `SessionHandler` gains `lookback_hours` + narrow `_state_lock`; `_ingest_session` takes `state_lock=`; `_do_ingest` returns bool; new state-cursor `reconcile()`; `SessionWatch` dataclass; `start/stop_session_watcher` use it; new `run_session_reconcile()` (stop/join + recreate) |
| `src/ormah/background/scheduler.py` | + `register_session_reconcile_job()` (`coalesce=True`) |
| `src/ormah/main.py` | store watches; register the reconcile job after watchers start |
| `scripts/diag/fsevents_monitor.py` | new standalone diagnostic monitor |
| `tests/test_background/test_session_watcher.py` | + reconcile / pre-filter / no-dup / recreate / heartbeat tests |
| `tests/test_config.py` (or existing) | + interval validator test |

## Tasks (do in order)

1. **[01-config.md](01-config.md)** — config setting + validator (independent, fast).
2. **[02-handler-core.md](02-handler-core.md)** — `SessionHandler` new fields + `_do_ingest` serialize/return-bool.
3. **[03-reconcile.md](03-reconcile.md)** — `SessionHandler.reconcile()` + its tests (depends on 02).
4. **[04-lifecycle-job-wiring.md](04-lifecycle-job-wiring.md)** — `SessionWatch`, `start/stop_session_watcher`, `run_session_reconcile`, scheduler register, `main.py` wiring (depends on 02/03).
5. **[05-monitor.md](05-monitor.md)** — standalone `fsevents_monitor.py` (independent; Part B).

## Out of scope (YAGNI)

- Instrumenting the production hot path; changing the 72h lookback bound; refactoring `_scan_sessions` / the startup catch-up; replacing the Observer with pure polling.

## Acceptance (issue #59)

- [ ] Every ingestible transcript ingested without a restart (reconcile net).
- [ ] A leaking live path recovered without a restart (reconcile + is_alive recreate).
- [ ] No pending transcript lost to the 72h bound (5-min reconcile).
- [ ] Liveness signal exists (heartbeat log + `JobTracker`).

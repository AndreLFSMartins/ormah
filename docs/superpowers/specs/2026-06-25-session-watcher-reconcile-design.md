# Design — session-watcher live-loss safety net

**Date:** 2026-06-25
**Issue:** r-spade/ormah#59 (live path intermittently drops a fraction of transcripts)
**Diagnosis source:** `SESSION_WATCHER_DIAGNOSIS_2026-06-25.md`
**Branch:** `fix/session-watcher-reconcile` (off `main`) → PR to `r-spade/ormah` (closes #59) → merge into `local-main`

## Problem

The session-watcher ingests Claude Code / Codex JSONL transcripts in real time via a single
`watchdog` `FSEventsObserver`. It works for the majority of transcripts, but **intermittently
drops a fraction of them** (whole sessions and the held-back *tails* of ongoing sessions): the
filesystem event never reaches the handler, so the file is never ingested. These escapes are
recovered only by the next restart's catch-up scan; any escape older than the `72h` lookback is
**permanently lost**. The loss is silent — there is no functional heartbeat.

## Root cause

**Architectural (proven by code):** the live path is a single `FSEventsObserver`, scheduled once
at startup (`session_watcher.py:1003-1005`, `recursive=True` on `~/.claude/projects`), with no
`is_alive()` poll, no recreate, and **no periodic reconcile**. The recovery code (`_scan_sessions`)
runs *only* as the startup catch-up (`start_session_watcher` is called once, `main.py:234`; none of
the scheduler jobs re-scan sessions). Therefore any event FSEvents drops is unrecoverable until the
next restart. This is structural and independent of the trigger.

**Trigger (probable, not yet instrumented):** FSEvents coalescing/dropping events under high event
volume. The server was ingesting *other* sessions during the loss window (Observer thread alive →
not thread death), and the handler treats every `.jsonl` identically (not a filter bug), leaving
*selective per-file event loss* — the signature of FSEvents coalescing (`MustScanSubDirs`). Proving
the exact mechanism requires the monitor (Part B); the fix does not depend on it, because the
recovery scan reads the disk, not events, and is therefore mechanism-agnostic.

## Goals

- Every ingestible transcript (whole session or closed tail) is ingested without waiting for a restart.
- A leaking/stalled live path is recovered without a restart.
- No pending transcript is lost to the 72h lookback bound.
- The leak is observable (a functional heartbeat), not silent.
- Prove *why* FSEvents fails to notify, for the upstream issue (Part B).

## Non-goals (YAGNI)

- Instrumenting the production hot path (`on_created`/`on_modified` logging in the live handler).
- Changing the `72h` lookback bound — a 5-minute reconcile makes permanent loss impossible without it.
- Refactoring `_scan_sessions` / the startup catch-up — it stays as-is.
- Replacing the FSEvents Observer with pure polling — keeps the ~60s live latency for no gain.

---

## Part A — Production fix: periodic reconcile + Observer supervision

The FSEvents Observer remains the fast path (~60s). A mechanism-agnostic disk scan runs periodically
as the safety net, plus liveness supervision, plus a functional heartbeat.

### A1. `SessionHandler.reconcile()` — single state owner

`_scan_sessions` is a module function that loads its *own* copy of state from disk. Running it
concurrently with the live handler would clobber the state file (last-writer-wins) and double-ingest.
So reconcile becomes a **method on the handler**, reusing `self._state` (in-memory) and the handler's
machinery:

- Under a cheap mtime pre-filter (A3), `rglob` the watch dir for `*.jsonl`, skip subagent transcripts
  (`_is_subagent_transcript`), apply the same lookback cutoff to never-seen files as `_scan_sessions`.
- For each candidate, call the existing `self._do_ingest(path)` synchronously (in the scheduler thread).
  This reuses the `_ingesting` guard (no racing the live path on the same file), the `_pending`
  re-run logic, and the single shared `self._state`. No clobber, no dup.

reconcile passes no `on_defer_active` — active tails are the live path's job and the next reconcile
re-checks them anyway. `_ingest_session`'s own idle detection commits closed content.

### A2. `self._ingest_lock` — serialize the ingest body

Pre-existing latent race found during design: `_do_ingest` runs `_ingest_session` *outside*
`self._lock`, so two sessions going idle together already mutate the shared `self._state` and call
`_save_state` (full-file rewrite) concurrently — risk of `dict changed size` / truncated state.
Adding reconcile as another concurrent writer makes fixing this in-scope.

Fix: a dedicated `self._ingest_lock` that wraps **only** the `_ingest_session` call inside
`_do_ingest`. `self._lock` stays short (timers/bookkeeping), so scheduling stays non-blocking; only
the actual ingest body serializes. Serialization is acceptable — extraction (gemma3:4b via Ollama) is
slow and effectively serial; volume is tens/day. This also removes the latent race for free.

### A3. mtime pre-filter (perf)

`_ingest_session` hashes the whole file before checking the offset. A periodic scan would re-hash
~hundreds of state files every tick. reconcile keeps an in-memory `self._reconcile_mtimes`
(`path → mtime`) and only calls `_do_ingest` for files whose mtime advanced or that are never-seen.
No state schema change, no migration. (Unchanged files already short-circuit in `_ingest_session`
without writing state — the pre-filter only saves the re-hash I/O.)

### A4. `session_reconcile` scheduler job + supervision

New job in `scheduler.py` via the existing `tracked()` wrapper:

- `id="session_reconcile"`, `"interval"`, `minutes=s.session_watcher_reconcile_interval_minutes`,
  `max_instances=1`, `misfire_grace_time=_MISFIRE_GRACE`.
- Per watcher: `if not observer.is_alive(): recreate the Observer + re-schedule the handler` (replace
  the stored reference); then `handler.reconcile()`. `is_alive` alone does not catch selective event
  loss — it is a cheap extra on top of the reconcile net.

New config (`config.py`): `session_watcher_reconcile_interval_minutes: int = 5`.

### A5. Functional heartbeat

When `reconcile()` ingests `> 0`, log at INFO:
`"Session watcher reconcile recovered %d transcript(s) the live path missed"`. That is the
observable leak signal. `tracked()` already records last-run/last-success in `JobTracker`.

### A6. Plumbing

`start_session_watcher` currently returns `list[Observer]`. It will return a small structure pairing
`(watch_dir, handler, observer-ref)` per watch dir (observer in a mutable holder so the job can swap
it on recreate). `main.py` passes this to `start_scheduler` so the `session_reconcile` job can reach
the handlers and observers. `stop_session_watcher` stops the current observer in each holder.

### Data flow

```
write to .jsonl
  ├─ FAST PATH:  FSEvents → on_created/on_modified → _schedule_ingest (60s debounce) → _do_ingest
  │                                                                                      └─ _ingest_lock → _ingest_session
  └─ SAFETY NET: every 5 min → session_reconcile job
                                  ├─ observer.is_alive()? else recreate
                                  └─ handler.reconcile() → mtime pre-filter → _do_ingest (same lock/state)
                                       └─ if ingested > 0: heartbeat log
```

### Error handling

- reconcile is wrapped by `tracked()` → exceptions are recorded, not fatal to the scheduler.
- Observer recreate failure is logged and retried next tick (the reconcile still runs).
- `_ingest_session` keeps its existing per-file `try/except` (parse/ingest errors skip one file).

---

## Part B — Diagnostic monitor (standalone, parallel, zero production risk)

`scripts/diag/fsevents_monitor.py` — a standalone script (not wired into the server) that proves *why*
FSEvents fails to notify:

- Opens its own FSEvents stream on `~/.claude/projects`.
- Decodes the kernel "events were dropped" flags: `kFSEventStreamEventFlagUserDropped`,
  `kFSEventStreamEventFlagKernelDropped`, `kFSEventStreamEventFlagMustScanSubDirs`.
- Logs `on_created` / `on_modified` / **`on_moved`** / `on_deleted` (the production handler implements
  only created/modified — if Claude Code ever writes via rename/atomic-replace, the write arrives as
  `on_moved` and is missed *deterministically*; this monitor confirms or rules that out).
- Every N seconds, computes disk-truth-vs-events: files whose mtime advanced but for which no event
  fired in the window = the leaks; correlate each leak with the drop flags seen.
- Writes to a dedicated log; run across a sleep/wake cycle and a heavy day.

**Honest scope:** if it confirms coalescing/`MustScanSubDirs`, the fix stays the reconcile net (the
kernel coalesces by design; the documented remedy is to rescan = the reconcile). Payoff: (1) proof for
#59, (2) a possible cheap deterministic miss (`on_moved`) to also fix, (3) a verification harness that
the reconcile closes the gap within one interval.

---

## Testing (Part A)

- **Central regression:** write a changed `.jsonl` *without* firing the handler (simulate a dropped
  event) → `reconcile()` ingests it. Directly reproduces the bug.
- **Concurrency:** interleave a live `_do_ingest` and `reconcile()` on overlapping files → no duplicate
  ingest, state file remains valid JSON, no duplicate `node_ids`.
- **Pre-filter:** a file whose mtime did not advance is not re-hashed / not re-ingested.
- **Liveness:** an observer reported dead → the job recreates it (mock Observer).
- **Heartbeat:** reconcile ingesting `> 0` emits the recovery log line.

Tests land in `tests/test_session_watcher.py`. Maps to acceptance criteria 1–4 of #59.

## Acceptance criteria (from #59)

- [ ] Every ingestible transcript is ingested live without waiting for a restart (reconcile net).
- [ ] A leaking live path is recovered without a restart (reconcile + is_alive recreate).
- [ ] No pending transcript is lost to the 72h bound (5-min reconcile).
- [ ] A liveness signal exists (heartbeat log + `JobTracker` last-run/last-success).

## Rollout

1. Branch `fix/session-watcher-reconcile` off `main`.
2. Implement Part A (TDD), Part B alongside.
3. Run the monitor ~1 day (sleep/wake + heavy usage) → fold evidence into #59.
4. PR to `r-spade/ormah` (closes #59); merge into `local-main`.

# Design: session-watcher catch-up off the bind path (#52)

**Date:** 2026-06-26
**Issue:** #52 — `perf(startup): session-watcher catch-up scan runs on the bind path — HTTP unavailable for minutes on restart`
**Branch:** `fix/session-watcher-catchup-off-bind-path` (off clean `main`; the
`fix/session-watcher-reconcile-upstream` work is intentionally not in scope here)

## Problem

`start_session_watcher()` runs its catch-up scan **synchronously inside the FastAPI lifespan
startup**, before `yield` — and uvicorn binds the socket only after startup yields. Each pending
transcript triggers a full LLM extraction + embeddings, serially. With a backlog of N recently-active
sessions, HTTP (whisper inject, recall, UI, `/ingest/*`) is down for the whole drain — observed
**13+ minutes** on one restart.

The byte cursor (#33/#34) is working: the cost is **width** (N distinct sessions = N serial LLM
calls), not depth (no re-reading). The fix is to move that width off the bind path.

## Scope

In scope (confirmed):
- AC#1 — uvicorn binds without waiting for the catch-up scan.
- AC#2 — catch-up still ingests every pending tail **exactly once** (no byte-cursor regression).
- AC#3 — the background drain stops **cooperatively** on shutdown.
- Fan-out bound — cap concurrent LLM extractions across live + catch-up (issue's optional follow-up,
  pulled in deliberately).

Out of scope:
- Live-preempts-catch-up prioritization (possible later follow-up).
- The reconcile-job / deprioritize machinery on `fix/session-watcher-reconcile-upstream`.

## Approach (B): observer-first + catch-up routed through the handler + shared semaphore

Why B over alternatives: it is the only option that delivers the chosen scope (a real fan-out bound)
**and** gets exactly-once for free by reusing the handler's existing in-flight guard, instead of
inventing a second dedup mechanism. A "scan-then-observe in a thread" variant is a smaller diff but
leaves nothing to bound (drain stays serial=1) and so does not satisfy the chosen scope.

### Startup flow (`start_session_watcher`, called in `lifespan` before `yield`)

```
create stop_event: threading.Event
create extraction_semaphore: threading.Semaphore(K)   # K = session_watcher_catchup_concurrency, default 1
for each watch_dir:
    handler  = SessionHandler(..., extraction_semaphore)
    observer = Observer(); observer.schedule(handler, watch_dir, recursive=True); observer.start()  # live from t0
spawn ONE non-daemon thread: _run_catchup(handlers, stop_event)        # off the bind path; joined at shutdown
return SessionWatcherHandle(observers, handlers, catchup_thread, stop_event)
# yield -> uvicorn binds immediately
```

The catch-up thread enumerates pending files (keeping `_scan_sessions`' selection logic: lookback,
min_turns, stale-state cleanup) and routes each candidate through a dedicated
`SessionHandler.catchup_ingest(file)`, not the free `_ingest_session` and not the live `_do_ingest`.
`catchup_ingest` shares the in-flight guard and the semaphore-wrapped ingest core (`_run_guarded`) with
`_do_ingest`, but does **not** cancel live debounce timers (it never calls `self._timers.pop`). This
means:
- The handler's `_ingesting`/`_pending`/`_state_lock` guard dedupes catch-up-vs-live → **AC#2 for free**.
- Catch-up consults the handler's `self._state` under `_state_lock` — eliminating the two-separate-
  state-dict hazard that a concurrent free-function scan would create.
- When `catchup_ingest` finds a file already in flight (a live ingest owns it), it returns an
  `in_flight` status instead of dropping the file. `_run_catchup` collects those and does **one retry
  pass** at the end, so a file is never silently left undrained if the concurrent live ingest fails
  without rerunning.

### Fan-out bound

Factor the guarded ingest core so the `with self._semaphore:` wrap around `_ingest_session(...)` is
shared by **both** the live path (`_do_ingest`) and the catch-up path (`catchup_ingest`). Both must
acquire the same semaphore instance, or the bound holds for only one path. `K=1` ⇒ at most one
extraction against the single Ollama instance at a time, across live + catch-up combined. `K` is
`session_watcher_catchup_concurrency` (default 1).

### Shutdown (`stop_session_watcher(handle)`, runs before `engine.shutdown()`)

`engine.shutdown()` is just `db.close()`, which closes the thread-local connections. `_ingest_session`
→ `engine.ingest_conversation` calls `remember()` **per memory with no single outer transaction**, and
the byte cursor is saved **after** the ingest. So a catch-up thread still inside an ingest when the DB
closes would do a use-after-close write and a **partial ingest with an un-advanced cursor** → duplicates
on the next restart (this non-atomicity is already tracked in
`UPSTREAM_ISSUE_session_watcher_nonatomic_db_cursor.md`). The drain therefore must fully finish before
`db.close()`.

There are **two** sources of in-flight ingest, both of which must be drained: the catch-up thread
(non-daemon) **and** the live path, which runs `_do_ingest` from `Timer(daemon=True)` debounce/retry
threads. A drain that joins only the catch-up thread is insufficient — a live `_do_ingest` already inside
an ingest (its `Timer` already fired, file claimed in `_ingesting`) can still hit `db.close()` (this is the
gap council round 2 found: the live path was never awaited at shutdown, pre-dating this change).

Shutdown distinguishes **three** kinds of work. (a) **In-flight** ingests — already claimed in
`_ingesting`, live or catch-up — are *drained* (the poll waits for them). (b) **Pending** debounce/retry
`Timer`s that have **not** fired are *cancelled* by `cancel_pending_timers()`, not drained; their tails
carry an un-advanced cursor and are *recovered by the next start's catch-up* (the same mechanism that
drains the startup backlog). The drain guarantee is therefore over in-flight ingests, not over un-fired
timers — losing a debounce window defers a tail to the next start, it does not drop it (final two-peer
round #2). (c) **Post-stop** filesystem events are *rejected* by the under-`_lock` stop check below.

**The `_ingesting` set IS the in-flight tracker — claimed under `_lock`.** Both `_do_ingest` and
`catchup_ingest` add the file key to `self._ingesting` **under `self._lock`**, at the very top, and
discard it under `_lock` in `finally` — so `len(self._ingesting)` reflects every in-flight ingest from
the instant it is claimed (a separate `_inflight` counter that increments later, inside `_run_guarded`,
would leave a window where an ingest has claimed the file but is not yet counted — the race council
round 3 found). The **stop check is also under `_lock`, before the claim**: once `stop_event` is set, any
`_do_ingest`/`catchup_ingest` acquiring the lock aborts without claiming or touching the DB. So:

- An ingest that claimed before stop → counted in `_ingesting` → the drain waits for it.
- An ingest acquiring the lock after `stop_event.set()` → aborts under the lock (no DB access). This also
  neutralizes a stray timer scheduled past `cancel_pending_timers` (TOCTOU): its `_do_ingest` aborts.

`start_session_watcher` shares one `stop_event` across all handlers and the catch-up thread. Shutdown:

```
stop_event.set()                       # under-lock entry checks now abort any new ingest
for o in observers: o.stop()           # no new fs events
for h in handlers: h.cancel_pending_timers()   # cancel un-fired timers -> tails recovered next-start catch-up
catchup_thread.join()                  # catch-up finishes its in-flight ingest and returns
while any(h.in_flight_count() > 0 for h in handlers):   # in_flight_count() = len(_ingesting) under _lock
    time.sleep(0.05)                                    # wait for every in-flight ingest, no cap
    # every ~5s: logger.warning("...still draining N in-flight ingest(s)")  # watchdog: surface a wedged ingest
for o in observers: o.join(timeout=5)
# lifespan then calls engine.shutdown() -> db.close(), now that no ingest is running anywhere
```

Because no new ingest can claim (stop check under `_lock`) and we wait for `_ingesting` to fully empty,
**no ingest is still running when `db.close()` runs** — across both live and catch-up. The poll is
**intentionally not capped**: a deadline that breaks early would abandon a still-running ingest and re-open
the use-after-close window (council round 4 #1). Note the drain is *not* bounded by `llm_timeout_seconds` —
that only caps the LLM adapter call; `_ingest_session` also runs whisper-signal judging, `remember()` per
memory, embedding encode/load, vector search/upsert, and SQLite lock waits, none of which the LLM timeout
governs. We therefore accept a possibly-slow shutdown over the use-after-close risk, and emit a **watchdog
log** every ~5 s while the drain is still pending so a wedged ingest (stuck encoder/DB lock) is visible
rather than a silent hang (final two-peer round #1).
`# ponytail: poll in-flight on shutdown; a Condition only if shutdown latency ever matters.`

**Accepted limitation:** a hard kill (SIGKILL) or an extraction force-terminated at `llm_timeout_seconds`
can still leave a partial ingest + un-advanced cursor → at most one duplicated tail on restart. This is
the pre-existing non-atomic-cursor limitation (`UPSTREAM_ISSUE_session_watcher_nonatomic_db_cursor.md`),
not made worse by this change; the background dedup jobs reconcile it. We document it rather than claim
self-healing safety.

### Error handling

Each catch-up ingest is wrapped in `try/except` — one bad file logs and is skipped, the drain
continues (matches current `_scan_sessions` resilience).

## Components changed

- `src/ormah/background/session_watcher.py`
  - `SessionHandler.__init__` — add `extraction_semaphore` + `stop_event` params; add `_state_lock`. No
    separate in-flight counter — `_ingesting` is the tracker.
  - `SessionHandler._run_guarded(path)` — new private core: `with self._extraction_semaphore:` around
    `_ingest_session(..., state_lock=self._state_lock)`. Returns the ingested bool.
  - `SessionHandler._do_ingest` — live path; **under `_lock`**: pop the timer, `if _stop_event.is_set():
    return`, in-flight guard, claim `_ingesting`. Then `_run_guarded`; rerun only when not stopping.
  - `SessionHandler.catchup_ingest(path)` — catch-up path; **under `_lock`**: `if _stop_event.is_set():
    return "stopped"`, in-flight guard (no timer pop), claim `_ingesting`. Returns
    `"ok"`/`"skipped"`/`"in_flight"`/`"stopped"`.
  - `SessionHandler._schedule_ingest` / `_schedule_retry` — early-return when `self._stop_event.is_set()`
    (cheap defense; the under-`_lock` entry check is the real guard against post-cancel timers).
  - `SessionHandler.cancel_pending_timers()` — cancel + clear `_timers` (under `_lock`).
  - `SessionHandler.in_flight_count()` — return `len(self._ingesting)` (under `_lock`).
  - `_iter_catchup_candidates(watch_dir, known, lookback_hours, stop_event=None)` — new; the lookback/
    never-seen selection, extracted so `_run_catchup` is the single owner of the logic. Bails on `stop_event`
    (top + per-item) so a shutdown mid-scan does not pay a full `O(files)` `rglob` walk (final round #4).
  - **Remove `_scan_sessions`** — orphaned once `start_session_watcher` stops calling it; its lookback
    test migrates to `_run_catchup`.
  - `_run_catchup(watches, stop_event, lookback_hours)` — new; iterates `_iter_catchup_candidates` using
    each handler's `_state`; routes through `catchup_ingest`; checks `stop_event` between files; one retry
    pass over `in_flight` files.
  - `start_session_watcher` — create one shared `stop_event` + semaphore; build handlers with both; start
    observers; spawn **non-daemon** catch-up thread; return handle.
  - `stop_session_watcher` — the drain sequence above: `stop_event.set()` → `observer.stop()` →
    `cancel_pending_timers()` → `catchup_thread.join()` → poll `in_flight_count()==0` across handlers →
    `observer.join()`.
  - `SessionWatcherHandle` — small holder (observers, handlers, catchup_thread, stop_event).
- `src/ormah/main.py` — **no change** (lifespan already does start → store → stop; the value is now a handle).
- `src/ormah/config.py` — add `session_watcher_catchup_concurrency: int = 1` + a `>= 1` validator.

## Testing (`tests/test_background/test_session_watcher.py`)

1. **AC#1** — patch `_ingest_session` to block on an event; assert `start_session_watcher` returns
   before the blocked ingest finishes (proves it left the bind path).
2. **AC#2 unit** — `_run_catchup` over a backlog ingests each tail once; a second pass over unchanged
   files ingests nothing (cursor idempotent).
3. **AC#2 integration (core, the nuclear scenario)** — `start_session_watcher` with a backlog; hold
   catch-up inside `_ingest_session` on an `Event` while firing a live `on_modified` for the **same**
   file; release; assert the real ingest of that tail ran **exactly once** (in-flight guard dedupes
   catch-up vs the live observer) and the cursor is correct.
4. **AC#3 (live path — the round-2 gap)** — with `lookback_hours = -1` (catch-up skips the file), start
   a **live** `_do_ingest` that blocks inside `_ingest_session` on an `Event`; call `stop_session_watcher`
   from another thread and assert it **stays blocked** (does not abandon the in-flight live ingest);
   release; assert `stop` completes and `in_flight_count()` is 0 — i.e. the live drain finished before
   return, so no ingest can run after `engine.shutdown()`.
5. **AC#3 race (round-3 gap)** — set `stop_event`, then call `_do_ingest` directly (simulating a timer
   that fired during shutdown); assert `_ingest_session` is **not** called and `in_flight_count()` stays
   0 — proving the under-`_lock` entry check rejects any ingest started after stop.
6. **AC#4 bound** — with `K=1`, an instrumented concurrency counter never exceeds 1 when `catchup_ingest`
   (one thread) and `_do_ingest` (another thread) overlap.
7. **Lookback parity** — `_run_catchup` lookback edges (`lookback_hours` of `-1`, `0`, a positive cutoff),
   plus the migrated `_scan_sessions` "recent vs old" test now driving `_run_catchup`.
8. **Regression** — update existing tests that assume `start_session_watcher` returns `list[Observer]`
   / runs the scan synchronously, to the handle; drop the `_scan_sessions` import.
9. **Pending-timer recovery (final round #2)** — schedule a debounce timer (long debounce), cancel it via
   `cancel_pending_timers()` (no ingest happens), then run `_run_catchup` and assert the tail is ingested —
   proving a cancelled un-fired timer's tail is recovered, not lost.
10. **Lifespan ordering (final round #1/#5)** — start a live ingest that blocks inside `_ingest_session`;
    from another thread run `stop_session_watcher` then a traced `engine.shutdown`; assert the order is
    `ingest_done` **then** `db_close` — the drain completes before the DB closes.
11. **Semaphore-blocked drain (round 4 #5)** — an ingest that claimed `_ingesting` but is waiting on the
    `K=1` semaphore when stop fires is counted in-flight and drained, not abandoned.

## Acceptance criteria

- [ ] uvicorn binds the port without waiting for the catch-up scan.
- [ ] Catch-up ingests every pending tail exactly once (no byte-cursor regression), including a live
      append to the same file during the drain.
- [ ] On a graceful stop, **both** the catch-up thread and any in-flight live (`Timer`) ingest are
      finished before `engine.shutdown()` → no ingest runs after `db.close()`.
- [ ] Concurrent LLM extractions across live + catch-up never exceed `K` (default 1).

## Confirmed decisions

- **In-flight drain on shutdown (rounds 1–4).** Non-daemon catch-up thread + a shared `stop_event`. Both
  ingest paths claim/release `_ingesting` **and** check `stop_event` **under `_lock`** before claiming;
  shutdown polls `len(_ingesting)` to 0 **uncapped** (see Shutdown — a deadline cap would re-open
  use-after-close, round 4) before `db.close()`. This drains **both** the catch-up thread and the live
  `Timer`-driven `_do_ingest` path, and closes the add-claim-before-counted race + the post-cancel-timer
  TOCTOU. Reverses the round-1 10s-grace-abandon choice, extends the drain to the live path (round-2),
  makes the claim/check atomic under the lock (round-3), and drops the deadline cap (round-4) — all
  because `ingest_conversation` is non-transactional per memory
  (`UPSTREAM_ISSUE_session_watcher_nonatomic_db_cursor.md`).
- **Final two-peer round (cursor + codex).** Both confirmed the core design has no deadlock-by-cycle and no
  use-after-close under a faithful implementation. Accepted refinements: (#1) the drain is *not* bounded by
  `llm_timeout_seconds` (non-LLM work is unbounded) → corrected wording + a watchdog log; (#2) un-fired
  debounce timers are cancelled, not drained → their tails are recovered by the next start's catch-up, and
  the drain guarantee is scoped to in-flight ingests; (#4) `_iter_catchup_candidates` bails on `stop_event`
  to avoid an `O(files)` scan during shutdown.
- `K` exposed as `session_watcher_catchup_concurrency`, default 1 (validated `>= 1`).

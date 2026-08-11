# Session-watcher catch-up off the bind path (#52) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the session-watcher catch-up scan off the FastAPI bind path so uvicorn binds immediately, while keeping exactly-once ingestion, a drain-before-close shutdown for every **in-flight** ingest (live and catch-up), and a bound on concurrent LLM extractions. Pending (un-fired) debounce timers are cancelled at shutdown and their tails recovered by the next start's catch-up.

**Architecture:** The `Observer` starts immediately; a single non-daemon thread (`_run_catchup`) drains the backlog by routing each pending file through `SessionHandler.catchup_ingest` — which shares the in-flight guard and the semaphore-wrapped ingest core (`_run_guarded`) with the live `_do_ingest`. Both paths claim/release `_ingesting` **and** check a shared `stop_event` **under `_lock`** before claiming, so once stopping no **new** ingest can begin (any already-claimed in-flight ingest finishes during the drain). `stop_session_watcher` sets `stop_event`, stops observers, cancels pending timers, joins the catch-up thread, then polls `len(_ingesting)` to 0 **before** `engine.shutdown()` closes the DB. Shutdown handles three kinds of work distinctly: already-claimed **in-flight** ingests are drained (the poll waits for them); **pending** debounce timers that have not fired are cancelled and their tails recovered by the next start's catch-up; **post-stop** events are rejected by the under-`_lock` stop check. The drain poll is intentionally **uncapped** — non-LLM work in `_ingest_session` (whisper-signal judging, embeddings, vector search, SQLite lock waits) is *not* bounded by `llm_timeout_seconds`, so a deadline cap could abandon a still-running ingest and re-open the use-after-close window. We accept a possibly-slow shutdown over that risk; a watchdog log surfaces a stuck drain. A shared `Semaphore(K)` bounds concurrent extractions (K=`session_watcher_catchup_concurrency`, default 1).

**Tech Stack:** Python 3.11, `threading` (Semaphore/Event/Thread/Lock/Timer), watchdog `Observer`, pytest, pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-06-26-session-watcher-catchup-off-bind-path-design.md` (revised after council rounds 1–4 and a final two-peer round).

---

## File structure

- `src/ormah/config.py` — new setting `session_watcher_catchup_concurrency` + `>= 1` validator.
- `src/ormah/background/session_watcher.py` — `state_lock` on `_ingest_session`; on `SessionHandler`: `Semaphore`/`stop_event`/`_state_lock` + `_run_guarded`/`catchup_ingest`/`cancel_pending_timers`/`in_flight_count` + under-`_lock` stop checks; new `SessionWatcherHandle` + `_iter_catchup_candidates` + `_run_catchup`; rewritten `start_session_watcher`/`stop_session_watcher`; **delete `_scan_sessions`**.
- `tests/test_background/test_session_watcher.py` — new tests (AC#1–#4, nuclear live-append, live-drain + semaphore-blocked-drain + post-stop-reject shutdown, lookback parity, pending-timer recovery, lifespan ordering) + migrate the `_scan_sessions` lookback test to `_run_catchup` + update 4 handle-return tests + drop the `_scan_sessions` import.
- `src/ormah/main.py` — **no change** (lifespan already does start → store → stop; the value is now a handle).

Imports to add in `session_watcher.py`: `from dataclasses import dataclass`; extend `from threading import Lock, Timer` with `Event, Semaphore, Thread`. In the test module: `import threading`.

---

### Task 1: Add the `session_watcher_catchup_concurrency` setting

**Files:** Modify `src/ormah/config.py` (settings block ~L67-72; validators ~L302-306) · Test `tests/test_background/test_session_watcher.py`

- [ ] **Step 1 — Failing test:**

```python
def test_catchup_concurrency_must_be_positive():
    from ormah.config import Settings
    assert Settings().session_watcher_catchup_concurrency == 1
    with pytest.raises(ValueError):
        Settings(session_watcher_catchup_concurrency=0)
```

- [ ] **Step 2 — Run, expect FAIL:** `pytest tests/test_background/test_session_watcher.py::test_catchup_concurrency_must_be_positive -v`

- [ ] **Step 3 — Implement.** After `session_watcher_idle_threshold` (L72) add `    session_watcher_catchup_concurrency: int = 1`. After the `_session_watcher_debounce_min` validator (~L306) add:

```python
    @field_validator("session_watcher_catchup_concurrency")
    @classmethod
    def _catchup_concurrency_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"session_watcher_catchup_concurrency must be >= 1, got {v}")
        return v
```

- [ ] **Step 4 — Run, expect PASS.**
- [ ] **Step 5 — Commit:** `git commit -am "feat(session-watcher): add session_watcher_catchup_concurrency setting (#52)"`

---

### Task 2: Thread an optional `state_lock` through `_ingest_session`

**Files:** Modify `src/ormah/background/session_watcher.py` (`_ingest_session` signature L699-707; state write L810-821) · Test same module

- [ ] **Step 1 — Failing test:**

```python
def test_ingest_session_accepts_state_lock(engine, tmp_path):
    import threading
    from ormah.background.session_watcher import _ingest_session
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        ok = _ingest_session(engine, f, state, wd, 5, state_lock=threading.Lock())
    assert ok is True
    assert "p/s.jsonl" in state
```

- [ ] **Step 2 — Run, expect FAIL** (`TypeError: unexpected keyword 'state_lock'`).

- [ ] **Step 3 — Implement.** Add `state_lock=None` to the signature (after `on_defer_active=None,`). Replace the write block (L810-821):

```python
    entry = {
        "hash": h,
        "end_offset": payload_offset,
        "last_ingested": datetime.now(timezone.utc).isoformat(),
        "session_id": result.session_id,
        "source": result.source,
        "space": space,
        "user_turns": prev_turns + payload_users,
        "node_ids": prev_node_ids + new_node_ids,
        "signals_recorded": signals_recorded,
    }
    if state_lock is not None:
        with state_lock:
            state[rel] = entry
            _save_state(watch_dir, state)
    else:
        state[rel] = entry
        _save_state(watch_dir, state)
```

- [ ] **Step 4 — Run, expect PASS.**
- [ ] **Step 5 — Commit:** `git commit -am "refactor(session-watcher): optional state_lock guards _ingest_session state write (#52)"`

---

### Task 3: `SessionHandler` — semaphore, under-`_lock` stop checks, `catchup_ingest`, in-flight via `_ingesting`

**Files:** Modify `src/ormah/background/session_watcher.py` (`SessionHandler` L875-955) · Test same module

- [ ] **Step 1 — Failing tests (AC#4 bound + AC#3 post-stop reject race):**

```python
def test_semaphore_bounds_catchup_and_live(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    a = wd / "p" / "a.jsonl"; b = wd / "p" / "b.jsonl"
    for f in (a, b):
        _make_jsonl(f); _mark_idle(f)
    cur = {"n": 0, "max": 0}; lk = threading.Lock(); real = sw._ingest_session
    def instrumented(*args, **kw):
        with lk:
            cur["n"] += 1; cur["max"] = max(cur["max"], cur["n"])
        time.sleep(0.05)
        with lk:
            cur["n"] -= 1
        return real(*args, **kw)
    sem = threading.Semaphore(1)
    handler = sw.SessionHandler(engine, wd, 0.1, 5, extraction_semaphore=sem)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", instrumented):
        t1 = threading.Thread(target=handler._do_ingest, args=(a,))
        t2 = threading.Thread(target=handler.catchup_ingest, args=(b,))
        t1.start(); t2.start(); t1.join(); t2.join()
    assert cur["max"] == 1


def test_ingest_after_stop_is_rejected(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    stop = threading.Event()
    handler = sw.SessionHandler(engine, wd, 0.1, 5, stop_event=stop)
    stop.set()                                   # shutdown already in progress
    calls = {"n": 0}; real = sw._ingest_session
    def counting(*a, **k):
        calls["n"] += 1; return real(*a, **k)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", counting):
        result = handler._do_ingest(f)           # a timer that fired during shutdown
        status = handler.catchup_ingest(f)
    assert result is False
    assert status == "stopped"
    assert calls["n"] == 0                        # neither path touched _ingest_session / the DB
    assert handler.in_flight_count() == 0
```

- [ ] **Step 2 — Run, expect FAIL** (`TypeError: unexpected keyword 'extraction_semaphore'` / no `catchup_ingest`).

- [ ] **Step 3 — Implement.** In `__init__`, add params + attributes (no separate in-flight counter — `_ingesting` is the tracker):

```python
    def __init__(
        self,
        engine: MemoryEngine,
        watch_dir: Path,
        debounce_seconds: float,
        min_turns: int,
        idle_threshold: float = 30.0,
        extraction_semaphore: "Semaphore | None" = None,
        stop_event: "Event | None" = None,
    ) -> None:
        ...
        self._lock = Lock()
        self._state_lock = Lock()
        self._extraction_semaphore = extraction_semaphore or Semaphore(1)
        self._stop_event = stop_event or Event()
```

Add a `if self._stop_event.is_set(): return` guard at the **top** of `_schedule_ingest` and `_schedule_retry` (cheap defense). Then add the core + catch-up + shutdown helpers, and put the stop check **inside `_lock`** in `_do_ingest`:

```python
    def _run_guarded(self, path: Path) -> bool:
        """Semaphore-bounded ingest with the state lock."""
        with self._extraction_semaphore:
            return _ingest_session(
                self.engine, path, self._state, self.watch_dir, self.min_turns,
                idle_threshold=self.idle_threshold,
                on_defer_active=lambda: self._schedule_retry(path),
                state_lock=self._state_lock,
            )

    def _do_ingest(self, path: Path) -> bool:
        """Live path (after debounce/retry). Cancels its own timer."""
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)
            if self._stop_event.is_set():        # shutting down -> reject before claiming / touching DB
                return False
            if key in self._ingesting:
                self._pending.add(key)
                return False
            self._ingesting.add(key)
        try:
            result = self._run_guarded(path)
        finally:
            with self._lock:
                self._ingesting.discard(key)
                rerun = key in self._pending
                self._pending.discard(key)
        if rerun and not self._stop_event.is_set():
            self._schedule_ingest(path)
        return result

    def catchup_ingest(self, path: Path) -> str:
        """Catch-up path. Shares the in-flight guard but never touches live debounce timers.
        Returns 'ok' | 'skipped' | 'in_flight' | 'stopped'."""
        key = str(path)
        with self._lock:
            if self._stop_event.is_set():
                return "stopped"
            if key in self._ingesting:
                return "in_flight"
            self._ingesting.add(key)
        try:
            ingested = self._run_guarded(path)
        finally:
            with self._lock:
                self._ingesting.discard(key)
                rerun = key in self._pending
                self._pending.discard(key)
        if rerun and not self._stop_event.is_set():
            self._schedule_ingest(path)
        return "ok" if ingested else "skipped"

    def cancel_pending_timers(self) -> None:
        """Cancel debounce/retry timers that have not fired yet (shutdown)."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def in_flight_count(self) -> int:
        """Number of ingests that have claimed a file and not yet released it."""
        with self._lock:
            return len(self._ingesting)
```

- [ ] **Step 4 — Run, expect PASS** (both tests).
- [ ] **Step 5 — Commit:** `git commit -am "feat(session-watcher): under-lock stop check + _ingesting in-flight tracker + catchup_ingest (#52)"`

---

### Task 4: `SessionWatcherHandle` + `_iter_catchup_candidates` + `_run_catchup`

**Files:** Modify `src/ormah/background/session_watcher.py` (add dataclass + functions near `_scan_sessions`) · Test same module

- [ ] **Step 1 — Failing tests:**

```python
def test_catchup_ingests_each_tail_exactly_once(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    stop = threading.Event()
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        sw._run_catchup([(wd, handler)], stop, 72)
        first = _load_state(wd)["p/s.jsonl"]["end_offset"]
        sw._run_catchup([(wd, handler)], stop, 72)   # unchanged -> no re-ingest
        second = _load_state(wd)["p/s.jsonl"]["end_offset"]
    assert first == second


def test_catchup_ingest_reports_in_flight(engine, tmp_path):
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    handler._ingesting.add(str(f))               # pretend a live ingest owns it
    assert handler.catchup_ingest(f) == "in_flight"
```

- [ ] **Step 2 — Run, expect FAIL** (`module has no attribute '_run_catchup'`).

- [ ] **Step 3 — Implement.** Add near `_scan_sessions`:

```python
@dataclass
class SessionWatcherHandle:
    observers: list
    handlers: list
    catchup_thread: "Thread | None"
    stop_event: "Event"


def _iter_catchup_candidates(watch_dir, known, lookback_hours, stop_event=None):
    """Yield JSONL files due for (re)ingest, honoring the lookback cutoff for never-seen files.
    Single owner of the selection logic (replaces the inline scan in the removed _scan_sessions).
    Bails on stop_event so a shutdown mid-scan does not pay a full O(files) directory walk."""
    if stop_event is not None and stop_event.is_set():
        return
    now = time.time()
    cutoff = now - (lookback_hours * 3600) if lookback_hours > 0 else 0
    for jsonl_file in sorted(watch_dir.rglob("*.jsonl")):
        if stop_event is not None and stop_event.is_set():
            return
        rel = str(jsonl_file.relative_to(watch_dir))
        if rel not in known and lookback_hours >= 0 and cutoff > 0:
            try:
                if jsonl_file.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
        if rel not in known and lookback_hours < 0:
            continue
        yield jsonl_file


def _run_catchup(watches, stop_event, lookback_hours) -> None:
    """Drain the backlog off the bind path, routing each file through its handler's catchup_ingest."""
    for watch_dir, handler in watches:
        if stop_event.is_set():
            return
        with handler._state_lock:
            known = set(handler._state.keys())
        ingested = 0
        deferred: list[Path] = []
        for jsonl_file in _iter_catchup_candidates(watch_dir, known, lookback_hours, stop_event):
            if stop_event.is_set():
                return
            try:
                status = handler.catchup_ingest(jsonl_file)
            except Exception as e:  # one bad file must not kill the drain
                logger.warning("Catch-up ingest error for %s: %s", jsonl_file, e)
                continue
            if status == "ok":
                ingested += 1
            elif status == "in_flight":
                deferred.append(jsonl_file)
        # one retry pass: a live ingest was holding these; pick up anything it left undrained
        for jsonl_file in deferred:
            if stop_event.is_set():
                return
            try:
                if handler.catchup_ingest(jsonl_file) == "ok":
                    ingested += 1
            except Exception as e:
                logger.warning("Catch-up retry error for %s: %s", jsonl_file, e)
        with handler._state_lock:
            stale = [r for r in list(handler._state.keys()) if not (watch_dir / r).exists()]
            for r in stale:
                del handler._state[r]
            if stale:
                _save_state(watch_dir, handler._state)
        if ingested:
            logger.info("Session watcher catch-up: ingested %d sessions from %s", ingested, watch_dir)
```

- [ ] **Step 4 — Run, expect PASS** (both tests).
- [ ] **Step 5 — Commit:** `git commit -am "feat(session-watcher): _iter_catchup_candidates + _run_catchup with in-flight retry pass (#52)"`

---

### Task 5: Rewrite `start_session_watcher` / `stop_session_watcher` (drain both sources, bounded poll)

**Files:** Modify `src/ormah/background/session_watcher.py` (L958-1003) · Test same module

- [ ] **Step 1 — Failing tests (AC#1 off-bind, AC#2 nuclear, AC#3 live drain):**

```python
def test_start_returns_without_blocking_on_catchup(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_debounce_seconds = 10.0
    started = threading.Event(); release = threading.Event(); real = sw._ingest_session
    def blocking(*a, **k):
        started.set(); release.wait(5); return real(*a, **k)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        t0 = time.monotonic()
        handle = sw.start_session_watcher(engine)
        elapsed = time.monotonic() - t0
        try:
            assert elapsed < 1.0
            assert started.wait(2)
        finally:
            release.set(); sw.stop_session_watcher(handle)


def test_live_append_during_catchup_ingests_tail_once(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f, user_turns=6); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_debounce_seconds = 10.0
    real = sw._ingest_session
    in_ingest = threading.Event(); release = threading.Event()
    true_returns = {"n": 0}; lk = threading.Lock()
    def gated(*a, **k):
        in_ingest.set(); release.wait(5)
        r = real(*a, **k)
        if r:
            with lk:
                true_returns["n"] += 1
        return r
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", gated):
        handle = sw.start_session_watcher(engine)
        assert in_ingest.wait(2)
        for h in handle.handlers:
            h._do_ingest(f)                      # live ingest of the SAME file mid-catch-up
        release.set()
        time.sleep(0.5)
        sw.stop_session_watcher(handle)
    assert true_returns["n"] == 1


def test_stop_drains_live_inflight_ingest(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_lookback_hours = -1   # catch-up skips never-seen -> only live
    started = threading.Event(); release = threading.Event()
    def blocking(*a, **k):
        started.set(); release.wait(5); return False
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        handle = sw.start_session_watcher(engine)
        live = threading.Thread(target=handle.handlers[0]._do_ingest, args=(f,))
        live.start()
        assert started.wait(2)
        done = threading.Event()
        stopper = threading.Thread(target=lambda: (sw.stop_session_watcher(handle), done.set()))
        stopper.start()
        assert not done.wait(0.5)                # stop BLOCKS on the live in-flight ingest
        release.set()
        assert done.wait(3)                       # stop returns after it finishes
        live.join()
    assert all(h.in_flight_count() == 0 for h in handle.handlers)


def test_stop_drains_ingest_blocked_on_semaphore(engine, tmp_path):
    """An ingest that claimed _ingesting but is waiting on the K=1 semaphore when stop fires is
    counted in_flight and drained — not abandoned (council round 4 #1/#5)."""
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    a = wd / "p" / "a.jsonl"; b = wd / "p" / "b.jsonl"
    for f in (a, b):
        _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_lookback_hours = -1       # only the two live ingests below
    started = threading.Event(); release = threading.Event(); count = {"done": 0}; lk = threading.Lock()
    def blocking(*ar, **kw):
        started.set(); release.wait(5)
        with lk:
            count["done"] += 1
        return False
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        handle = sw.start_session_watcher(engine)
        h = handle.handlers[0]
        ta = threading.Thread(target=h._do_ingest, args=(a,))  # acquires the K=1 semaphore, blocks
        ta.start(); assert started.wait(2)
        tb = threading.Thread(target=h._do_ingest, args=(b,))  # claims _ingesting[b], waits on semaphore
        tb.start(); time.sleep(0.2)
        assert h.in_flight_count() == 2                         # both claimed before stop
        done = threading.Event()
        stopper = threading.Thread(target=lambda: (sw.stop_session_watcher(handle), done.set()))
        stopper.start()
        assert not done.wait(0.5)                               # stop waits for BOTH to drain
        release.set()
        assert done.wait(5)
        ta.join(); tb.join()
    assert count["done"] == 2                                   # both completed, none abandoned
    assert h.in_flight_count() == 0
```

- [ ] **Step 2 — Run, expect FAIL** (start blocks / returns a list / stop does not wait for the live ingest).

- [ ] **Step 3 — Implement.** Replace `start_session_watcher` and `stop_session_watcher`:

```python
def start_session_watcher(engine: MemoryEngine) -> SessionWatcherHandle:
    """Start observers immediately and drain the catch-up backlog off the bind path."""
    s = engine.settings
    stop_event = Event()
    if not s.session_watcher_enabled:
        return SessionWatcherHandle([], [], None, stop_event)

    watch_dirs = _session_watch_dirs(s)
    if not watch_dirs:
        logger.warning("Session watcher dir does not exist: %s", _expand_watch_dir(s.session_watcher_dir))
        return SessionWatcherHandle([], [], None, stop_event)

    semaphore = Semaphore(s.session_watcher_catchup_concurrency)
    observers: list[Observer] = []
    watches: list[tuple[Path, SessionHandler]] = []
    for watch_dir in watch_dirs:
        handler = SessionHandler(
            engine, watch_dir, s.session_watcher_debounce_seconds, s.session_watcher_min_turns,
            s.session_watcher_idle_threshold, extraction_semaphore=semaphore, stop_event=stop_event,
        )
        observer = Observer()
        observer.schedule(handler, str(watch_dir), recursive=True)
        observer.start()
        observers.append(observer)
        watches.append((watch_dir, handler))
        logger.info("Session watcher started on %s", watch_dir)

    catchup_thread = Thread(
        target=_run_catchup, args=(watches, stop_event, s.session_watcher_lookback_hours),
        name="ormah-session-catchup", daemon=False,
    )
    catchup_thread.start()
    return SessionWatcherHandle(observers, [h for _, h in watches], catchup_thread, stop_event)


def stop_session_watcher(handle: SessionWatcherHandle) -> None:
    """Fully drain every in-flight ingest before returning (lifespan calls engine.shutdown() right
    after). Under-_lock stop checks reject NEW ingests; pending debounce timers are cancelled (their
    tails are recovered by the next start's catch-up); we then wait for every already-claimed in-flight
    ingest (live or catch-up) to finish, so nothing touches the DB after db.close(). The wait is NOT
    capped: non-LLM work in _ingest_session (whisper judging, embeddings, vector search, SQLite lock
    waits) is not bounded by llm_timeout_seconds, so a deadline cap could abandon a running ingest and
    re-open the use-after-close window (council round 4 #1). Correctness outweighs a rare slow shutdown;
    a watchdog log surfaces a stuck drain (final two-peer round #1)."""
    handle.stop_event.set()
    for observer in handle.observers:
        observer.stop()
    for handler in handle.handlers:
        handler.cancel_pending_timers()
    if handle.catchup_thread is not None:
        handle.catchup_thread.join()
    waited = 0.0
    while any(h.in_flight_count() > 0 for h in handle.handlers):
        time.sleep(0.05)  # ponytail: poll on shutdown; a Condition only if shutdown latency matters
        waited += 0.05
        if waited >= 5.0:  # watchdog: a wedged non-LLM section (encoder/DB lock) would hang here
            n = sum(h.in_flight_count() for h in handle.handlers)
            logger.warning("Session watcher shutdown still draining %d in-flight ingest(s)", n)
            waited = 0.0
    for observer in handle.observers:
        observer.join(timeout=5)
    if handle.observers:
        logger.info("Session watcher stopped")
```

Add `Event, Semaphore, Thread` to the `from threading import ...` line and `from dataclasses import dataclass`.

- [ ] **Step 4 — Run, expect PASS** (all four tests).
- [ ] **Step 5 — Commit:** `git commit -am "feat(session-watcher): off-bind-path catch-up with uncapped drain-before-close for live + catch-up (#52)"`

---

### Task 6: Lookback parity, migrate the `_scan_sessions` test, delete `_scan_sessions`

`_run_catchup` is now the only catch-up selection path; pin its lookback edges and remove the orphan.

**Files:** Modify `src/ormah/background/session_watcher.py` (delete `_scan_sessions`) · `tests/test_background/test_session_watcher.py`

- [ ] **Step 1 — Add `_run_catchup` lookback edge tests:**

```python
def test_run_catchup_lookback_minus_one_skips_new_files(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        sw._run_catchup([(wd, handler)], threading.Event(), -1)
    assert _load_state(wd) == {}


def test_run_catchup_lookback_zero_ingests_all(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        sw._run_catchup([(wd, handler)], threading.Event(), 0)
    assert "p/s.jsonl" in _load_state(wd)


def test_cancelled_debounce_timer_tail_recovered_by_catchup(engine, tmp_path):
    """A debounce timer cancelled at shutdown leaves its tail un-ingested; the next start's catch-up
    recovers it (final two-peer round #2: pending timers are cancelled, not drained)."""
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 10.0, 5)   # long debounce: timer won't fire during the test
    handler._schedule_ingest(f)                          # a live append schedules a debounce timer
    assert handler._timers                               # timer pending, tail not yet ingested
    handler.cancel_pending_timers()                      # shutdown cancels it
    assert _load_state(wd) == {}                          # nothing ingested at shutdown
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):   # "next start" catch-up
        sw._run_catchup([(wd, handler)], threading.Event(), 72)
    assert "p/s.jsonl" in _load_state(wd)                 # tail recovered
```

- [ ] **Step 2 — Migrate the existing `_scan_sessions` "recent vs old" lookback test (≈L660-686)** to drive `_run_catchup`. Replace the `_scan_sessions` call + `count == 1` assertion with:

```python
    import threading
    handler = SessionHandler(engine, watch_dir, 0.1, 5)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _run_catchup([(watch_dir, handler)], threading.Event(), 72)
    state = _load_state(watch_dir)
    assert str(recent.relative_to(watch_dir)) in state
    assert str(old.relative_to(watch_dir)) not in state
```

- [ ] **Step 3 — Delete `_scan_sessions`** from `src/ormah/background/session_watcher.py` and remove it from the test module's import (L19). Add `_run_catchup` to the import if not already present.

- [ ] **Step 4 — Run:** `pytest tests/test_background/test_session_watcher.py -k "catchup or lookback" -v` — expect PASS (includes the cancelled-timer recovery test).
- [ ] **Step 5 — Commit:** `git commit -am "refactor(session-watcher): drop orphaned _scan_sessions; _run_catchup is the single catch-up path (#52)"`

---

### Task 7: Update the 4 existing tests to the handle return type

**Files:** Modify `tests/test_background/test_session_watcher.py` (L732-741, L761-766, L771-775, L805-811)

- [ ] **Step 1 — Update the four tests:**

```python
# test_lifecycle... (was L732-741)
    handle = start_session_watcher(engine)
    try:
        assert len(handle.observers) == 1
        assert handle.observers[0].is_alive()
    finally:
        stop_session_watcher(handle)
    time.sleep(0.1)
    assert not handle.observers[0].is_alive()

# test_lifecycle_includes_codex_sessions... (was L761-766)
    handle = start_session_watcher(engine)
    try:
        assert len(handle.observers) == 2
        assert all(o.is_alive() for o in handle.observers)
    finally:
        stop_session_watcher(handle)

# test_disabled_returns_empty (was L774-775)
    handle = start_session_watcher(engine)
    assert handle.observers == []
    assert handle.catchup_thread is None

# test_nonexistent_watch_dir (was L810-811)
    handle = start_session_watcher(engine)
    assert handle.observers == []
```

- [ ] **Step 2 — Run the full module:** `pytest tests/test_background/test_session_watcher.py -v` — expect PASS (new + updated).
- [ ] **Step 3 — Lint:** `make lint` — expect clean.
- [ ] **Step 4 — Full fast suite:** `python -m pytest tests/ -q` — expect no new failures (see the known-environmental-failures memory).
- [ ] **Step 5 — Commit:** `git commit -am "test(session-watcher): adopt SessionWatcherHandle return type (#52)"`

---

### Task 8: End-to-end ordering — drain completes before `engine.shutdown()` closes the DB

Unit tests above mock `_ingest_session`; this one proves the real lifespan ordering (the contract `main.py` relies on): `stop_session_watcher` blocks on the in-flight drain, so `engine.shutdown()` is only reached *after* the drain — nothing touches the DB after `db.close()`.

**Files:** Test `tests/test_background/test_session_watcher.py`

- [ ] **Step 1 — Failing test:**

```python
def test_stop_drains_before_engine_shutdown(engine, tmp_path):
    """Lifespan order (main.py): stop_session_watcher() fully drains the in-flight ingest BEFORE
    engine.shutdown() runs, so db.close() never races a live ingest (final two-peer round #1/#5)."""
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_lookback_hours = -1   # catch-up skips never-seen -> only the live ingest
    order = []
    started = threading.Event(); release = threading.Event(); real = sw._ingest_session
    def probing(*a, **k):
        started.set(); release.wait(5)
        r = real(*a, **k)
        order.append("ingest_done")
        return r
    def traced_shutdown():
        order.append("db_close")                          # trace only; the fixture owns the real close
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", probing), \
         patch.object(engine, "shutdown", traced_shutdown):
        handle = sw.start_session_watcher(engine)
        live = threading.Thread(target=handle.handlers[0]._do_ingest, args=(f,))
        live.start(); assert started.wait(2)
        done = threading.Event()
        # mirror main.py lifespan teardown: stop watcher, then engine.shutdown()
        td = threading.Thread(target=lambda: (sw.stop_session_watcher(handle), engine.shutdown(), done.set()))
        td.start()
        assert not done.wait(0.5)                          # teardown blocks on the in-flight ingest
        release.set()
        assert done.wait(5)
        live.join()
    assert order == ["ingest_done", "db_close"]            # drain completed before db.close()
```

- [ ] **Step 2 — Run, expect FAIL** before Task 5's drain exists (db_close would precede ingest_done) — confirms the test catches the regression.
- [ ] **Step 3 — Run against the implemented drain, expect PASS:** `pytest tests/test_background/test_session_watcher.py::test_stop_drains_before_engine_shutdown -v`
- [ ] **Step 4 — Commit:** `git commit -am "test(session-watcher): prove drain completes before engine.shutdown (#52)"`

---

## Self-review (done)

- **Spec coverage:** AC#1 → Task 5 `test_start_returns_without_blocking_on_catchup`; AC#2 unit → Task 4 `test_catchup_ingests_each_tail_exactly_once`; AC#2 nuclear → Task 5 `test_live_append_during_catchup_ingests_tail_once`; AC#3 drain → Task 5 `test_stop_drains_live_inflight_ingest`; AC#3 race → Task 3 `test_ingest_after_stop_is_rejected`; AC#3 semaphore-blocked drain → Task 5 `test_stop_drains_ingest_blocked_on_semaphore`; AC#3 lifespan ordering → Task 8 `test_stop_drains_before_engine_shutdown`; AC#4 → Task 3 `test_semaphore_bounds_catchup_and_live`; pending-timer recovery → Task 6 `test_cancelled_debounce_timer_tail_recovered_by_catchup`; lookback parity + migration → Task 6; setting → Task 1.
- **Council findings (all accepted):** R1 #1 shutdown abandon → drain. R2 #1 (Critical) live-Timer after close → drain both sources. R3 #1 (Critical) claim-before-counted race → in-flight tracked by `_ingesting` claimed under `_lock` + stop check under `_lock` before claim; R3 #2 post-cancel-timer TOCTOU → same under-`_lock` entry check rejects it; R3 #3 race test → Task 3 `test_ingest_after_stop_is_rejected`; R3 #4 `_scan_sessions` duplication → `_iter_catchup_candidates` extracted + `_scan_sessions` deleted (Task 4 + 6); R3 #5 unbounded poll → **kept uncapped by design** (Task 5). R4 #1 a deadline cap would re-open use-after-close → removed; poll stays uncapped; R4 #5 semaphore-blocked drain → Task 5 `test_stop_drains_ingest_blocked_on_semaphore`.
- **Final two-peer round (cursor ⚠️ + codex no-ship, both accepted):** #1 (convergent) "self-terminates because LLM bounded by `llm_timeout_seconds`" is false (non-LLM work is unbounded) → Goal/Architecture/Task-5 wording corrected + watchdog log in the drain poll (Task 5). #2 (codex, new) pending debounce timers are cancelled not drained → Goal/Architecture distinguish in-flight/pending/post-stop + Task 6 `test_cancelled_debounce_timer_tail_recovered_by_catchup`. #3 L652 contradiction → this line. #4 O(n) scan after stop → `_iter_catchup_candidates` takes `stop_event` and bails (Task 4). #5 no lifespan ordering test → Task 8 `test_stop_drains_before_engine_shutdown`. #6 "three tests" typo → "four" (Task 5).
- **Type consistency:** `SessionWatcherHandle(observers, handlers, catchup_thread, stop_event)` identical in Tasks 4/5/7; `catchup_ingest -> "ok"|"skipped"|"in_flight"|"stopped"` consumed by `_run_catchup`; `in_flight_count()=len(_ingesting)`, `_iter_catchup_candidates`, `_stop_event`, `extraction_semaphore` consistent across Tasks 3/4/5.
- **No placeholders:** every code step shows real code; commands have expected outcomes.

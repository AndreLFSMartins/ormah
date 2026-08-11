# Task 4: Lifecycle struct + scheduler job + main wiring

Expose `(watch_dir, handler, observer)` per watcher, add `run_session_reconcile` (recreate dead
Observer — stopping/joining the old one first — then reconcile), and register it as a scheduler job
after the watchers start. The scheduler starts *before* the watchers in `main.py`, so the job is
added to the already-running scheduler rather than reordering the bind-sensitive startup. The job
uses `coalesce=True` + a generous misfire grace so a slightly-long tick is never silently dropped
(council R1).

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (add `SessionWatch`, update `start/stop_session_watcher`, add `run_session_reconcile`)
- Modify: `src/ormah/background/scheduler.py` (add `register_session_reconcile_job`)
- Modify: `src/ormah/main.py:234-235` (store watches + register job)
- Test: `tests/test_background/test_session_watcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`:

```python
def test_run_session_reconcile_recreates_dead_observer(engine, tmp_path):
    """A dead Observer is stopped/joined and recreated; reconcile still runs."""
    from ormah.background.session_watcher import SessionWatch, run_session_reconcile

    watch_dir = tmp_path / "projects"
    watch_dir.mkdir(parents=True)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)

    dead = MagicMock()
    dead.is_alive.return_value = False
    watch = SessionWatch(watch_dir=watch_dir, handler=handler, observer=dead)

    with patch("ormah.background.session_watcher.Observer") as MockObserver:
        new_obs = MockObserver.return_value
        total = run_session_reconcile([watch])

    dead.stop.assert_called_once()        # old observer cleaned up before recreate
    dead.join.assert_called_once()
    new_obs.schedule.assert_called_once()
    new_obs.start.assert_called_once()
    assert watch.observer is new_obs
    assert total == 0  # empty dir, nothing to recover
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py::test_run_session_reconcile_recreates_dead_observer -v`
Expected: FAIL — no `SessionWatch` / `run_session_reconcile`.

- [ ] **Step 3: Add `SessionWatch` + `run_session_reconcile`; update lifecycle**

In `src/ormah/background/session_watcher.py`, add `from dataclasses import dataclass` to the imports,
and place the dataclass just above `start_session_watcher`:

```python
@dataclass
class SessionWatch:
    """A live watcher: its directory, handler, and (swappable) Observer."""
    watch_dir: Path
    handler: SessionHandler
    observer: Observer
```

Change `start_session_watcher` to build the handler with the lookback and return `list[SessionWatch]`:

```python
def start_session_watcher(engine: MemoryEngine) -> list[SessionWatch]:
    s = engine.settings
    if not s.session_watcher_enabled:
        return []

    watch_dirs = _session_watch_dirs(s)
    if not watch_dirs:
        logger.warning("Session watcher dir does not exist: %s", _expand_watch_dir(s.session_watcher_dir))
        return []

    watches: list[SessionWatch] = []
    for watch_dir in watch_dirs:
        ingested = _scan_sessions(
            engine, watch_dir, s.session_watcher_min_turns, s.session_watcher_lookback_hours,
        )
        if ingested:
            logger.info("Session watcher catch-up: ingested %d sessions from %s", ingested, watch_dir)

        handler = SessionHandler(
            engine, watch_dir, s.session_watcher_debounce_seconds, s.session_watcher_min_turns,
            s.session_watcher_idle_threshold, s.session_watcher_lookback_hours,
        )
        observer = Observer()
        observer.schedule(handler, str(watch_dir), recursive=True)
        observer.start()
        watches.append(SessionWatch(watch_dir=watch_dir, handler=handler, observer=observer))
        logger.info("Session watcher started on %s", watch_dir)

    return watches
```

Change `stop_session_watcher` to take watches:

```python
def stop_session_watcher(watches: list[SessionWatch]) -> None:
    for w in watches:
        w.observer.stop()
    for w in watches:
        w.observer.join(timeout=5)
    if watches:
        logger.info("Session watcher stopped")
```

Add `run_session_reconcile` at the end of the module. Note the `stop()/join()` of the dead Observer
before recreating, so a half-dead FSEvents thread/handle is not leaked:

```python
def run_session_reconcile(watches: list[SessionWatch]) -> int:
    """Periodic safety net: recreate any dead Observer, then reconcile each watcher.

    Recreating the Observer keeps the fast path alive going forward; the reconcile scan recovers
    anything the live path dropped (Observer death OR FSEvents coalescing). Returns total recovered.
    """
    total = 0
    for w in watches:
        try:
            alive = w.observer.is_alive()
        except Exception:
            alive = False
        if not alive:
            logger.warning("Session watcher Observer not alive for %s; recreating", w.watch_dir)
            try:
                w.observer.stop()
                w.observer.join(timeout=5)
            except Exception:
                pass
            try:
                observer = Observer()
                observer.schedule(w.handler, str(w.watch_dir), recursive=True)
                observer.start()
                w.observer = observer
            except Exception as e:
                logger.warning("Failed to recreate Observer for %s: %s", w.watch_dir, e)
        total += w.handler.reconcile()
    return total
```

- [ ] **Step 4: Add the scheduler registrar**

In `src/ormah/background/scheduler.py`, add at module level (uses the already-imported `tracked`):

```python
def register_session_reconcile_job(scheduler, tracker, watches, interval_minutes: int) -> None:
    """Register the session-watcher reconcile job on an already-started scheduler.

    Registered after the watchers start (they do not exist when start_scheduler runs), so the job
    can reach the live handlers/observers. ``coalesce=True`` + a full-interval misfire grace mean a
    slightly-long tick is never silently dropped; reconcile re-scans disk each run, so a coalesced
    tick loses no work. No-op when there are no watchers.
    """
    if not watches:
        return
    from ormah.background.session_watcher import run_session_reconcile

    scheduler.add_job(
        tracked(tracker, "session_reconcile", run_session_reconcile, watches),
        "interval",
        minutes=interval_minutes,
        id="session_reconcile",
        name="Session reconcile",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=max(_MISFIRE_GRACE, interval_minutes * 60),
    )
    logger.info("Session reconcile job registered (every %d min)", interval_minutes)
```

- [ ] **Step 5: Wire it in `main.py`**

In `src/ormah/main.py`, replace lines 234-235 (inside the session-watcher `try`):

```python
        session_watches = start_session_watcher(engine)
        app.state.session_watcher_observers = session_watches
        if hasattr(app.state, "scheduler"):
            from ormah.background.scheduler import register_session_reconcile_job
            register_session_reconcile_job(
                app.state.scheduler, app.state.job_tracker, session_watches,
                engine.settings.session_watcher_reconcile_interval_minutes,
            )
```

(`stop_session_watcher(app.state.session_watcher_observers)` at line ~254 already receives the watches — no change needed.)

- [ ] **Step 6: Run the test + full watcher + lifespan suites**

Run:
```bash
.venv/bin/python -m pytest tests/test_background/test_session_watcher.py tests/test_main_lifespan_shutdown.py -v
```
Expected: all PASS (the lifespan test mocks the watcher module, so the return-type change is safe).

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py src/ormah/background/scheduler.py src/ormah/main.py tests/test_background/test_session_watcher.py
git commit -m "feat(session-watcher): periodic reconcile job + Observer supervision"
```

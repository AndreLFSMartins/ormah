# Task 2: SessionHandler core — lookback, narrow state lock, return bool

Adds the field `reconcile()` (Task 3) needs, and protects the state read-modify-write with a
**narrow** lock passed into `_ingest_session` — only `state[rel]=…` + `_save_state` serialize,
while the expensive work (parse, LLM extraction, DB writes) stays lock-free (same concurrency as
production today). This removes the latent state-file race **without** letting a backlog reconcile
starve the live path (council R1, HIGH). `_do_ingest` now returns whether it ingested.

**Files:**
- Modify: `src/ormah/background/session_watcher.py:709-717` (`_ingest_session` signature) and `:822-833` (state write)
- Modify: `src/ormah/background/session_watcher.py:890-907` (`SessionHandler.__init__`)
- Modify: `src/ormah/background/session_watcher.py:935-959` (`_do_ingest`)
- Test: `tests/test_background/test_session_watcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`:

```python
def test_do_ingest_returns_true_when_it_ingests(engine, tmp_path):
    """_do_ingest reports whether it ingested, so reconcile can count recoveries."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler._do_ingest(jsonl) is True
        assert handler._do_ingest(jsonl) is False  # nothing new the second time
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py::test_do_ingest_returns_true_when_it_ingests -v`
Expected: FAIL — `_do_ingest` returns `None` (and `SessionHandler` takes no 6th positional arg yet).

- [ ] **Step 3: Add the `state_lock` param to `_ingest_session`**

Change the `_ingest_session` signature (currently ends at `on_defer_active=None,`) to add a trailing
param:

```python
def _ingest_session(
    engine: MemoryEngine,
    path: Path,
    state: dict,
    watch_dir: Path,
    min_turns: int,
    idle_threshold: float = 30.0,
    on_defer_active=None,
    state_lock=None,
) -> bool:
```

Then replace the final state write (currently `state[rel] = { … }` + `_save_state(watch_dir, state)`,
`:822-833`) with a version that serializes only that block when a lock is provided:

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

- [ ] **Step 4: Replace `SessionHandler.__init__`**

Replace `SessionHandler.__init__` (`:890-907`) with this complete version (`Lock`/`Timer` already
imported: `from threading import Lock, Timer`). Note: a narrow `_state_lock` — **no** coarse ingest
lock, **no** mtime cache (the new reconcile in Task 3 uses the state cursor, not mtime):

```python
    def __init__(
        self,
        engine: MemoryEngine,
        watch_dir: Path,
        debounce_seconds: float,
        min_turns: int,
        idle_threshold: float = 30.0,
        lookback_hours: int = 72,
    ) -> None:
        self.engine = engine
        self.watch_dir = watch_dir
        self.debounce_seconds = debounce_seconds
        self.min_turns = min_turns
        self.idle_threshold = idle_threshold
        self.lookback_hours = lookback_hours
        self._state = _load_state(watch_dir)
        self._timers: dict[str, Timer] = {}
        self._ingesting: set[str] = set()
        self._pending: set[str] = set()
        self._lock = Lock()
        self._state_lock = Lock()
```

- [ ] **Step 5: Rewrite `_do_ingest` (pass the narrow lock, return bool)**

Replace the body of `_do_ingest`. The heavy `_ingest_session` runs **without** a surrounding lock;
only its internal state write serializes via `state_lock`. The `_ingesting` guard still prevents two
ingests of the *same* path:

```python
    def _do_ingest(self, path: Path) -> bool:
        """Ingest the session (after debounce, retry, or reconcile). Returns True if ingested.

        The heavy work (parse/LLM/DB) runs lock-free; only the state read-modify-write
        serializes via ``self._state_lock`` (passed into ``_ingest_session``), so a backlog
        reconcile never blocks the live fast path.
        """
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)
            if key in self._ingesting:
                self._pending.add(key)
                return False
            self._ingesting.add(key)
        ingested = False
        try:
            ingested = _ingest_session(
                self.engine, path, self._state, self.watch_dir, self.min_turns,
                idle_threshold=self.idle_threshold,
                on_defer_active=lambda: self._schedule_retry(path),
                state_lock=self._state_lock,
            )
        finally:
            with self._lock:
                self._ingesting.discard(key)
                rerun = key in self._pending
                self._pending.discard(key)
        if rerun:
            self._schedule_ingest(path)
        return bool(ingested)
```

- [ ] **Step 6: Run the test + full watcher suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher.py -v`
Expected: all PASS (existing `test_concurrent_ingest_skipped` / `test_inflight_skip_reschedules` still green).

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "refactor(session-watcher): narrow state lock, return ingest result"
```

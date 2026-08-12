# Task 3: the Observer lane gets the same gate

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1361-1375` (`_enqueue_path`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: the state key `frozen_until: int` written by Task 1.
- Produces: nothing new. `SessionHandler._enqueue_path(self, path: Path, reason: str) -> None`
  keeps its signature.

`_enqueue_path` consults no state at all today: every FSEvent becomes an `enqueue`. Gating only
the sweep (Task 2) does not fix the defect, it relocates it — the ADR already recorded this in
another form: *"the suppression is applied in both producer lanes, because gating only the sweep
would trade a full `failed/` for a hot enqueue loop on the Observer lane."*

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`:

```python
def test_enqueue_path_skips_a_frozen_file_until_it_grows(engine, tmp_path):
    """The Observer lane must honour the same suppression fact as reconcile. Gating only
    the sweep trades a growing failed/ for a hot enqueue loop on every FSEvent."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "frozen.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] == size

        handler._enqueue_path(jsonl, "observer")     # a second FSEvent, file unchanged
        assert handler.spool.pending_count() == 0, \
            "a frozen file that has not grown must not be re-enqueued by the Observer"

        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, \
            "growth past frozen_until must re-open the Observer lane too"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_enqueue_path_skips_a_frozen_file_until_it_grows -v`

Expected: FAIL on `assert handler.spool.pending_count() == 0` — it is `1`, because
`_enqueue_path` enqueues unconditionally.

- [ ] **Step 3: Add the gate**

Replace the body of `_enqueue_path` at `:1361`:

```python
    def _enqueue_path(self, path: Path, reason: str) -> None:
        """Enqueue the file at its current EOF and wake the drain. The claim/dedup is the
        spool's; a boundary already queued is never lowered (Task 1)."""
        with self._lock:
            self._timers.pop(str(path), None)
        if self._stop_event.is_set() or self.spool is None:
            return
        try:
            boundary = path.stat().st_size
        except OSError:
            return
        # Frozen and not grown -> the last parse of this file closed nothing, and this
        # event would only reproduce that dead-letter. BOTH producer lanes carry the gate:
        # suppressing only the sweep would trade a growing failed/ for a hot enqueue loop
        # here (ADR-0004, 2026-08-12).
        try:
            rel = str(path.relative_to(self.watch_dir))
        except ValueError:
            rel = None      # outside this watch -- no state to consult, enqueue as before
        if rel is not None:
            frozen = (self._state.get(rel, {}).get("frozen_until") or 0)
            if frozen >= boundary:
                return
        # force_flush=False: the Observer/idle-retry lane is discovery, never an explicit ask;
        # it must respect min_turns/idle so an active session is not fragmented (council-pr R2).
        self.spool.enqueue(path, boundary=boundary, reason=reason, force_flush=False)
        self.wake()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_enqueue_path_skips_a_frozen_file_until_it_grows -v`

Expected: PASS.

- [ ] **Step 5: Run the whole watcher suite**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): the Observer lane honours frozen_until too

_enqueue_path consulted no state, so every FSEvent re-enqueued a frozen
transcript. Gating only reconcile would have moved the defect rather than
closed it.

Refs ADR-0004"
```

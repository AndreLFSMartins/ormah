# Task 3: the Observer lane uses the same predicate

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1361-1375` (`_enqueue_path`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `_frozen_unchanged(entry, st)` from Task 2 — the same function, not a copy.
- Produces: nothing new. `SessionHandler._enqueue_path(self, path: Path, reason: str) -> None`
  keeps its signature.

`_enqueue_path` consults no state at all today: every FSEvent becomes an `enqueue`. Gating only
the sweep (Task 2) does not fix the defect, it relocates it — the ADR already recorded this in
another form: *"the suppression is applied in both producer lanes, because gating only the sweep
would trade a full `failed/` for a hot enqueue loop on the Observer lane."*

**Council round 1:** because this lane consults nothing today, it is the one that currently
catches a rotated or same-size-replaced transcript. A size-only gate here would be a straight
regression, which is why the predicate is identity-based and lives in one place.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher.py`:

```python
def test_enqueue_path_skips_a_frozen_file_until_it_changes(engine, tmp_path):
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
            "an unchanged frozen file must not be re-enqueued by the Observer"

        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, \
            "growth must re-open the Observer lane too"


def test_enqueue_path_reopens_a_frozen_file_that_was_rotated_smaller(engine, tmp_path):
    """Council round 1, critical: this is the lane that catches rotation today, because it
    consults no state at all. A ceiling-only gate here would suppress a rotated transcript
    permanently — and with reconcile also gated, nothing else would ever find it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        frozen = handler._state[rel]["frozen_until"]

        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=6)
        assert jsonl.stat().st_size < frozen
        _mark_idle(jsonl)

        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, \
            "a rotated file must be re-enqueued, not hidden behind the old ceiling"
        _drain_all(handler)

    assert handler._state[rel].get("node_ids"), "the rotated file's content must be ingested"


def test_enqueue_path_re_arms_suppression_after_a_same_size_replacement(engine, tmp_path):
    """Council round 2, cursor, medium: proving the re-open is half the story. If the re-park
    does not converge identity, every FSEvent re-enqueues the same unparseable file forever
    and failed/ grows without bound — the failure mode the frozen fact exists to prevent."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        original = jsonl.read_bytes()

        replacement = proj / "tmp.jsonl"
        replacement.write_bytes(original)
        replacement.replace(jsonl)
        _mark_idle(jsonl)

        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, "the replacement must re-open the lane"
        _drain_all(handler)

        assert handler._state[rel]["frozen_ino"] == jsonl.stat().st_ino
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 0, \
            "suppression must re-arm on the new identity, not loop forever"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "enqueue_path_skips_a_frozen_file or enqueue_path_reopens or enqueue_path_re_arms" -v`

Expected: `enqueue_path_skips_a_frozen_file` FAILS on `assert handler.spool.pending_count() == 0`
— it is `1`, because `_enqueue_path` enqueues unconditionally. `enqueue_path_re_arms` fails on
its final assertion for the same reason. The rotation test currently PASSES (nothing is gated
yet); it is the regression net for Step 3.

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
            st = path.stat()
        except OSError:
            return
        # Frozen and byte-for-byte unchanged -> the last parse of this file closed nothing,
        # and this event would only reproduce that dead-letter. BOTH producer lanes carry the
        # gate: suppressing only the sweep would trade a growing failed/ for a hot enqueue
        # loop here (ADR-0004, 2026-08-12). The predicate is _frozen_unchanged, shared with
        # reconcile — never a second copy, which is how the two would drift apart.
        try:
            rel = str(path.relative_to(self.watch_dir))
        except ValueError:
            rel = None      # outside this watch -- no state to consult, enqueue as before
        if rel is not None and _frozen_unchanged(self._state.get(rel, {}), st):
            return
        # force_flush=False: the Observer/idle-retry lane is discovery, never an explicit ask;
        # it must respect min_turns/idle so an active session is not fragmented (council-pr R2).
        self.spool.enqueue(path, boundary=st.st_size, reason=reason, force_flush=False)
        self.wake()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "enqueue_path_skips_a_frozen_file or enqueue_path_reopens or enqueue_path_re_arms" -v`

Expected: all three PASS.

- [ ] **Step 5: Run the whole watcher suite**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): the Observer lane honours the frozen identity too

_enqueue_path consulted no state, so every FSEvent re-enqueued a frozen
transcript. It now shares _frozen_unchanged with reconcile — the same
function, because this is the lane that catches rotation today and a
divergent copy of the predicate would silently lose that.

Refs ADR-0004"
```

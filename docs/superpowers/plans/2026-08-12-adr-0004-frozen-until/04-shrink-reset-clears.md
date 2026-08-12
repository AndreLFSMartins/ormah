# Task 4: the frozen fact is cleared whenever it stops being true

**Files:**
- Modify: `src/ormah/background/session_watcher.py:962-966` (the confirmed-shrink reset) and
  `:1284-1285` (the successful-ingest commit)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: the three frozen keys from Task 1, `_frozen_unchanged` from Task 2, and both
  producer gates.
- Produces: nothing new.

Two writers must drop the fact, for the same reason: it describes a file, and once that file is
gone or has been ingested, keeping it around is a lie the gates will act on.

1. **The confirmed shrink reset** builds its entry with `dict(existing or {})` and updates only
   `hash`/`end_offset`. A frozen fact surviving it belongs to the file that was rotated away.
2. **The successful ingest commit** does the same via `entry = dict(existing) if carry else {}`.
   A stale ceiling left on a healthy entry can only mislead a later comparison (council round 1,
   cursor, medium).

**Council round 1 also killed the first draft of this task's test**, on two counts, both
verified: it reached the reset by calling `spool.enqueue` directly — bypassing the very producer
gate that was broken — and it could never have run tick 2 at all, because tick 1 requeues the job
with a persisted backoff, the second `enqueue` is a no-op on the same `(path, boundary)` key, and
`_drain_all` stops at the first job that is not due. The test below goes through `_enqueue_path`
and advances the spool's clock.

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`, next to the other shrink tests:

```python
def test_confirmed_shrink_clears_the_frozen_fact_through_the_producer(engine, tmp_path):
    """A rotated file reuses its path at a smaller size. The frozen fact left over from the
    PREVIOUS file must not survive the confirmed reset, and the whole route must run through
    a real producer: council round 1 rejected a version of this test that called
    spool.enqueue directly, because that is exactly the gate the defect lived in."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # 1. a normal ingest: the entry gets a real cursor
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        cursor = handler._state[rel]["end_offset"]
        assert cursor > 0

        # 2. an unterminated turn is appended and the session dies -> the file freezes
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user", "message": {"content": "a prompt that never got its answer"},
            }) + "\n")
        _mark_idle(jsonl)
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] > cursor

        # 3. the path is rotated to a NEW, smaller file
        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=2)
        assert jsonl.stat().st_size < cursor
        _mark_idle(jsonl)

        # 4. tick 1 through the producer: the cursor above EOF is an explicit escape from
        #    the frozen gate, so the Observer must still enqueue.
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, "the shrink escape must reach the spool"
        _drain_all(handler)
        assert handler._state[rel]["shrink_pending"], "tick 1 must arm the marker"
        assert "frozen_until" in handler._state[rel], "tick 1 does not reset anything yet"

        # 5. tick 2 is the SAME job, returned to pending/ with a persisted backoff. Advancing
        #    the spool's clock is what makes it due; enqueueing again would be a no-op on the
        #    same (path, boundary) key and _drain_all would find nothing due.
        with patch("ormah.background.ingest_spool.time.time",
                   return_value=time.time() + 3600):
            _drain_all(handler)

    entry = handler._state[rel]
    assert "shrink_pending" not in entry, "tick 2 must have actually run and confirmed"
    assert "frozen_until" not in entry, \
        "a confirmed shrink must drop the stale ceiling with the stale cursor"
    assert "frozen_ino" not in entry and "frozen_mtime_ns" not in entry
    assert entry.get("node_ids"), "the rotated file's content must reach the store"


def test_successful_ingest_clears_the_frozen_fact(engine, tmp_path):
    """Council round 1, cursor, medium: the happy-path commit carries the whole existing
    entry forward, so a frozen fact would outlive the freeze it described and could only
    mislead a later comparison."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "thaws.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert "frozen_until" in handler._state[rel]

        # the session comes back and closes the turn: the next parse ingests it
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user", "message": {"content": "a second prompt with enough text"},
            }) + "\n")
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": "and a closing answer"}]},
            }) + "\n")
        _mark_idle(jsonl)
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)

    entry = handler._state[rel]
    assert entry.get("node_ids"), "the content must have been ingested"
    assert "frozen_until" not in entry, "a successful ingest un-freezes the file"
    assert "frozen_ino" not in entry and "frozen_mtime_ns" not in entry
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "clears_the_frozen_fact" -v`

Expected: both FAIL on the `"frozen_until" not in entry` assertions — both commit sites copy the
whole existing entry forward.

If the shrink test instead fails at `assert handler._state[rel]["shrink_pending"]`, tick 1 did not
arm: check that `cursor > jsonl.stat().st_size` actually holds after the rotation, since that is
what the shrink gate keys on. Do not weaken the assertion — fix the fixture's sizes.

- [ ] **Step 3: Clear the fact at both commit sites**

At `:962-966`, the confirmed-shrink reset:

```python
        prev_offset = 0
        reset_entry = dict(existing or {})
        reset_entry.update({"hash": h, "end_offset": 0})
        reset_entry.pop("shrink_pending", None)
        # The frozen fact belongs to the file that was rotated away. Left in place it would
        # describe a file that no longer exists and the producer gates would act on it
        # (ADR-0004, 2026-08-12).
        for _k in ("frozen_until", "frozen_ino", "frozen_mtime_ns"):
            reset_entry.pop(_k, None)
        _commit_state(state, rel, reset_entry, state_lock, watch_dir, allow_rewind=True)
```

At `:1283-1285`, the successful-ingest commit, next to the existing `extract_fail_*` pops:

```python
    entry.pop("extract_fail_offset", None)  # a success at this offset clears the retry counter
    entry.pop("extract_fail_count", None)
    # A successful ingest un-freezes the file: the fact described a parse that closed nothing,
    # and this one closed something. Keeping it would leave a stale ceiling on a healthy entry.
    for _k in ("frozen_until", "frozen_ino", "frozen_mtime_ns"):
        entry.pop(_k, None)
    _commit_state(state, rel, entry, state_lock, watch_dir)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "clears_the_frozen_fact" -v`

Expected: both PASS.

- [ ] **Step 5: Run the whole watcher suite**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`

Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): drop the frozen fact on a confirmed shrink and on a successful ingest

Both commit sites copy the existing entry forward, so the fact outlived the
file it described. The shrink case is the one that matters: the fact belonged
to the rotated-away file and the producer gates would have acted on it.

Refs ADR-0004"
```

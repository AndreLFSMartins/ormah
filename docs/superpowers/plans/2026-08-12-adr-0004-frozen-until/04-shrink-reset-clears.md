# Task 4: a confirmed shrink clears the suppression fact

**Files:**
- Modify: `src/ormah/background/session_watcher.py:962-966` (the confirmed-shrink reset inside
  `_ingest_session`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: the state key `frozen_until: int` written by Task 1, and the gates from Tasks 2 & 3.
- Produces: nothing new.

The reset builds its entry with `dict(existing or {})` and updates only `hash`/`end_offset`. A
`frozen_until` surviving it would sit **above** the rotated file's size and suppress the fresh
content — the same defect with the sign flipped: the cursor stops claiming bytes it never
ingested, and the ceiling starts hiding bytes nobody ever examined.

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`, next to the other shrink tests:

```python
def test_confirmed_shrink_clears_the_frozen_fact(engine, tmp_path):
    """A rotated file reuses its path at a smaller size. A frozen_until left over from the
    PREVIOUS file sits above the new EOF and would suppress the new content forever — the
    freeze defect with the sign flipped. The confirmed reset must drop the field."""
    from ormah.background.session_watcher import _commit_state

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

    # a cursor above the new EOF is what arms the shrink gate; the frozen fact rides along
    _commit_state(handler._state, rel, {**handler._state[rel], "end_offset": frozen},
                  handler._state_lock, watch_dir)

    # the file is rotated: same path, smaller, and a COMPLETE conversation this time
    _make_jsonl(jsonl, user_turns=6)
    assert jsonl.stat().st_size < frozen
    _mark_idle(jsonl)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # tick 1 arms the shrink marker, tick 2 confirms it and resets
        for _ in range(2):
            handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="reconcile",
                                  force_flush=False)
            _drain_all(handler)

    entry = handler._state[rel]
    assert "frozen_until" not in entry, \
        "a confirmed shrink must drop the stale ceiling with the stale cursor"
    assert entry.get("node_ids"), "the rotated file's content must reach the store"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_confirmed_shrink_clears_the_frozen_fact -v`

Expected: FAIL on `assert "frozen_until" not in entry` — the reset copies the whole existing
entry, so the stale ceiling survives.

If it instead fails earlier because the second enqueue is suppressed by the Task 3 gate (the
stale ceiling is above the new size, which is exactly the bug), that is the same defect showing
up one step sooner. Enqueue through `handler.spool.enqueue` as written above — it bypasses the
producer gate on purpose, so the test exercises the reset rather than the gate.

- [ ] **Step 3: Clear the field on the confirmed reset**

At `:962-966`, add one `pop` next to the existing one:

```python
        prev_offset = 0
        reset_entry = dict(existing or {})
        reset_entry.update({"hash": h, "end_offset": 0})
        reset_entry.pop("shrink_pending", None)
        # The ceiling belongs to the file that is gone. Left in place it would sit above the
        # rotated file's EOF and suppress its content forever (ADR-0004, 2026-08-12).
        reset_entry.pop("frozen_until", None)
        _commit_state(state, rel, reset_entry, state_lock, watch_dir, allow_rewind=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_confirmed_shrink_clears_the_frozen_fact -v`

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
git commit -m "fix(watcher): a confirmed shrink clears frozen_until with the cursor

The ceiling belongs to the file that was rotated away. Surviving the reset it
would sit above the new EOF and suppress the fresh content — the freeze defect
with the sign flipped.

Refs ADR-0004"
```

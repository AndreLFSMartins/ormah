# Task 2: `reconcile` skips a frozen file until it grows

**Files:**
- Modify: `src/ormah/background/session_watcher.py:1622-1631` (the cheap-skip arm of `reconcile`)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: the state key `frozen_until: int` written by Task 1.
- Produces: nothing new. `SessionHandler.reconcile() -> int` keeps its signature and meaning
  (number of transcripts enqueued).

Without this task the cursor no longer drops the file from the sweep, so `reconcile` re-enqueues
a frozen transcript on every tick. Task 1 is not shippable alone.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_session_watcher.py`, next to the other reconcile tests:

```python
def test_reconcile_skips_a_frozen_file_until_it_grows(engine, tmp_path):
    """The cursor no longer drops a frozen file from the sweep — frozen_until does. And
    growth past the recorded ceiling is what re-opens it, with the parse resuming from the
    UNTOUCHED cursor rather than wherever a ratchet would have left it."""
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
        assert handler.reconcile() == 1        # first sweep: never seen -> enqueued
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] == size
        assert handler.reconcile() == 0, "a frozen file that has not grown must be skipped"

        # the session resumes and closes its turn: the file grows past the ceiling
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        _mark_idle(jsonl)
        assert handler.reconcile() == 1, "growth past frozen_until must re-open the file"


def test_reconcile_still_selects_a_never_seen_file_with_only_a_frozen_fact(engine, tmp_path):
    """A file whose FIRST examination froze has an entry with no end_offset at all. The
    cheap-skip arm evaluates (entry.get('end_offset') or 0) >= size -> 0 >= size is false,
    so it must fall through to the frozen gate and be judged there, not skipped by accident
    nor re-enqueued forever."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "firstfreeze.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)

    assert "end_offset" not in handler._state[rel], \
        "the freeze must not create a cursor for a file that was never ingested"
    assert handler._state[rel]["frozen_until"] == jsonl.stat().st_size
    assert handler.reconcile() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "frozen_file_until_it_grows or never_seen_file_with_only_a_frozen_fact" -v`

Expected: both FAIL — the second `reconcile()` returns `1`, because nothing skips the file now
that the cursor stays at 0.

One assumption to check while you are here: the second test asserts `"end_offset" not in
handler._state[rel]`. It rests on the freeze being the *only* writer for a file that never
ingested anything — which is what the production census found (75 entries holding `end_offset`
and nothing else). If that assertion fails, print the entry: some other path is creating a
cursor for a never-ingested file, and that is a finding worth reporting before continuing, not
a test to loosen.

- [ ] **Step 3: Add the gate**

In `reconcile`, immediately after the existing cheap-skip arm at `:1626-1631`, add a third arm:

```python
            elif (entry.get("end_offset") or 0) >= st.st_size and not entry.get(
                "shrink_pending"
            ):
                # Fully consumed -> skip cheaply. EXCEPT a shrink_pending entry (task 4):
                # between tick 1 and tick 2 the durable cursor is still above EOF -- skipping
                # here would drop the file from the sweep and tick 2 would never arrive,
                # stranding the marker itself.
                continue
            elif (entry.get("frozen_until") or 0) >= st.st_size:
                # Frozen and not grown since that examination: the last parse of this file
                # closed nothing, so re-selecting it would produce the same dead-letter and
                # nothing else. Growth past the ceiling re-opens it (ADR-0004, 2026-08-12).
                # A SEPARATE arm on purpose: the one above carries the shrink_pending
                # exception, and folding two independent gates into one expression ties
                # them together.
                continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "frozen_file_until_it_grows or never_seen_file_with_only_a_frozen_fact" -v`

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
git commit -m "fix(watcher): reconcile skips a frozen transcript until it grows

The cursor used to drop a frozen file from the sweep as a side effect of
claiming its bytes. With the cursor left alone, frozen_until takes that job:
a separate cheap-skip arm, so the shrink_pending exception above it stays
independent.

Refs ADR-0004"
```

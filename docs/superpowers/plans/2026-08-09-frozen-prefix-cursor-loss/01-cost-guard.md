# Task 1: Cost guard

Read `00-overview.md` first. Run everything inside `../ormah-wt-frozen-prefix`.

**Why first:** this test protects the fix from the moment it lands. Without it, Task 2's change could turn every benign `NO_PROGRESS` — a file already fully consumed — into an infinite retry loop. It must be green before AND after.

**Files:**
- Modify: `tests/test_background/test_session_watcher.py` — append after `test_idle_file_with_no_safe_boundary_is_dead_lettered`, which currently ends at line 2690.

**Interfaces:**
- Consumes: `_make_jsonl`, `_mark_idle`, `_drain_all`, `_handler_with_spool`, `_LLM_PATCH`, `_LLM_RESPONSE` — all already defined in this file.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the guard test**

```python
def test_fully_consumed_file_completes_and_is_not_requeued(engine, tmp_path):
    """Cost guard for the frozen-prefix fix: a file whose cursor already sits at EOF
    returns NO_PROGRESS with NOTHING left to close. That must still COMPLETE the job.
    Requeueing it would turn every benign no-op into an endless retry loop."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "done.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    size = jsonl.stat().st_size
    handler.spool.enqueue(jsonl, boundary=size, reason="nudge")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)
    assert handler._state[rel]["end_offset"] == size, "precondition: first pass consumed it"

    # Second pass over the SAME unchanged, fully-consumed file.
    handler.spool.enqueue(jsonl, boundary=size, reason="reconcile")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    assert handler.spool.pending_count() == 0, "a consumed file must not be requeued"
    assert not list((handler.spool.root / "failed").glob("*.json")), \
        "a consumed file must not be dead-lettered either"
```

- [ ] **Step 2: Run it — it must PASS on unmodified code**

```bash
python -m pytest tests/test_background/test_session_watcher.py::test_fully_consumed_file_completes_and_is_not_requeued -v
```

Expected: `1 passed`.

If it FAILS, **stop and report**. The baseline is not what this plan assumes, and Task 2 rests on that baseline. Do not adjust the test to make it green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_background/test_session_watcher.py
git commit -m "test(ingest): pin that a fully consumed file completes instead of requeueing"
```

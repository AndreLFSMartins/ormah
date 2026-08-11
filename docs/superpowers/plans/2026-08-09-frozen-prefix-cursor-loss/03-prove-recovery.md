# Task 3: Prove the recovery

Read `00-overview.md` first. Run everything inside `../ormah-wt-frozen-prefix`. Task 2 must be committed and green.

**Why:** Task 2 proves the cursor stops moving. This proves what that buys — the prompt survives and is paired when the response finally closes.

**Files:**
- Modify: `tests/test_background/test_session_watcher.py` — append after the tests from Task 2.

**Interfaces:**
- Consumes: `_partial_unterminated`, `_mark_idle`, `_drain_all`, `_handler_with_spool`, `_LLM_PATCH`, `_LLM_RESPONSE`.

- [ ] **Step 1: Write the recovery test**

```python
def test_unclosed_prefix_is_ingested_with_its_prompt_once_it_closes(engine, tmp_path):
    """The payoff: after the response closes, the ORIGINAL user turn is still ingestable.
    While the cursor was advanced past it, that prompt was gone -- production recorded
    user_turns=7 on a transcript whose whole-file parse yields 8."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "grows.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)
    assert handler._state.get(rel) is None, "precondition: nothing consumed yet"

    # The response finally closes.
    with jsonl.open("a") as fh:
        fh.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "and here is the closing answer"}]},
        }) + "\n")
    _mark_idle(jsonl)
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="reconcile")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    entry = handler._state[rel]
    assert entry["user_turns"] == 1, "the ORIGINAL prompt must be in the ingested slice"
    assert entry["node_ids"], "memories must have been created"
    assert entry["end_offset"] == jsonl.stat().st_size
```

- [ ] **Step 2: Run it**

```bash
python -m pytest tests/test_background/test_session_watcher.py::test_unclosed_prefix_is_ingested_with_its_prompt_once_it_closes -v
```

Expected: `1 passed` (Task 2's fix is already in).

- [ ] **Step 3: Honesty check — confirm it actually fails without the fix**

Do not skip this. A test that would pass either way proves nothing.

```bash
git stash push src/ormah/background/session_watcher.py
python -m pytest tests/test_background/test_session_watcher.py::test_unclosed_prefix_is_ingested_with_its_prompt_once_it_closes -v
git stash pop
```

Expected: FAIL without the fix.

**If it PASSES without the fix:** the orphan-recovery rewind (`should_rewind`) happens to rescue this small fixture even though it demonstrably does not rescue the production cases. **Do NOT bend the test to force red.** Keep it as a regression guard, and record the limitation verbatim in the Step 5 commit message:

```
Note: this fixture is also rescued by the orphan-recovery rewind, so it
passes pre-fix. Kept as a regression guard; the proof of the defect is in
test_frozen_prefix_never_advances_the_cursor.
```

Report which branch you took either way.

- [ ] **Step 4: Full background suite + lint**

```bash
python -m pytest tests/test_background/ -q
ruff check src/ tests/
```

Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_background/test_session_watcher.py
git commit -m "test(ingest): the prompt behind an unclosed prefix survives until the turn closes"
```

(Append the Step 3 note to this message if the honesty check came out green pre-fix.)

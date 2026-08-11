# Session Watcher Incremental Ingestion (#33) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the session watcher from re-extracting an entire transcript every time an active file changes; ingest only the turns appended since the last ingest.

**Architecture:** `parse_transcript` already supports incremental reads (`start_offset` arg + `TranscriptResult.end_offset`). The watcher never used them. Wire the persisted `end_offset` into `_ingest_session`: re-open from the stored offset, ingest only the new slice, advance the cursor. Apply the `min_turns` gate to the *new* slice so small appends defer until enough new signal accumulates. Reset the cursor when a file shrinks (compaction/rewrite).

**Tech Stack:** Python 3.11, pytest (`asyncio_mode=auto`), watchdog. No new dependencies.

**Scope:** One source file (`src/ormah/background/session_watcher.py`) + its test file. The parser is unchanged.

**Known limitation (document, do not fix here):** an in-place prefix rewrite that does *not* shrink the file (rare; `/compact` shrinks) is not detected by the size-based reset and would ingest from the stale offset. Tracked separately if it ever surfaces.

---

## Task 1: Persist and reuse the byte cursor (incremental ingest)

**Files:**
- Modify: `src/ormah/background/session_watcher.py:59-125` (`_ingest_session`)
- Test: `tests/test_background/test_session_watcher.py`

### Behavior contract

- First ingest of a file (`existing is None`): `prev_offset = 0` → parse whole file → `min_turns` gate against full `user_turn_count` (unchanged from today).
- Re-ingest of a changed file: `prev_offset = existing["end_offset"]` → `parse_transcript(path, start_offset=prev_offset)` → only appended turns are parsed. `min_turns` gate applies to the **new** slice's `user_turn_count`.
- On ingest, persist `end_offset = result.end_offset` and a cumulative `user_turns`; accumulate `node_ids` (now non-overlapping).
- On skip (too few new turns), leave state untouched so the turns are reconsidered on the next change.
- If `path.stat().st_size < prev_offset` (file shrank — compaction/rewrite), reset `prev_offset = 0` and re-ingest the whole file.

- [ ] **Step 1: Write the failing test — only new turns are re-ingested**

```python
def test_incremental_only_new_turns(engine, tmp_path):
    """After the first ingest, a later change feeds ONLY the appended turns to ingest."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
        first_offset = state[str(jsonl.relative_to(watch_dir))]["end_offset"]
        assert first_offset > 0

        _make_jsonl(jsonl, user_turns=12)  # rewrites identical first 6 turns + appends 6 new
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True

    # second call's content holds only the appended turns
    assert "User message 0 " not in captured[1]
    assert "User message 6 " in captured[1]
    assert state[str(jsonl.relative_to(watch_dir))]["end_offset"] > first_offset
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python -m pytest tests/test_background/test_session_watcher.py::test_incremental_only_new_turns -v`
Expected: FAIL — today the second call re-sends the full conversation ("User message 0 " IS present), and `end_offset` is absent from state (KeyError).

- [ ] **Step 3: Write the failing test — too-few new turns defers**

```python
def test_incremental_defers_small_append(engine, tmp_path):
    """A change adding fewer than min_turns new turns does not trigger a second ingest."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
        saved = dict(state[str(jsonl.relative_to(watch_dir))])

        _make_jsonl(jsonl, user_turns=8)  # only 2 new turns < min_turns
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is False

    assert calls == 1  # no second extraction
    assert state[str(jsonl.relative_to(watch_dir))] == saved  # state untouched
```

- [ ] **Step 4: Write the failing test — shrink resets the cursor**

```python
def test_shrink_resets_cursor(engine, tmp_path):
    """A file that shrinks below the stored offset is re-ingested from the start."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=10)

    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True

        _make_jsonl(jsonl, user_turns=5)  # smaller file → size < stored end_offset
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True

    assert "User message 0 " in captured[1]  # re-ingested from the top
```

- [ ] **Step 5: Run all three, verify they fail**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "incremental or shrink" -v`
Expected: FAIL (KeyError on `end_offset` / full-content re-sends / second call fires).

- [ ] **Step 6: Implement the incremental cursor in `_ingest_session`**

Replace the body from the hash check through the `state[rel] = {...}` / `_save_state` block:

```python
    existing = state.get(rel)
    if existing and existing.get("hash") == h:
        return False

    # Incremental: only parse the turns appended since the last ingest.
    prev_offset = existing.get("end_offset", 0) if existing else 0
    try:
        size = path.stat().st_size
    except OSError as e:
        logger.warning("Cannot stat %s: %s", path, e)
        return False
    if prev_offset > size:
        prev_offset = 0  # file shrank (compaction/rewrite) → re-ingest whole

    try:
        result = parse_transcript(path, start_offset=prev_offset)
    except Exception as e:
        logger.warning("Session transcript parse error for %s: %s", path, e)
        return False

    if result.user_turn_count < min_turns:
        return False  # too few NEW turns; offset unchanged so they're reconsidered later

    # Detect space from parent directory encoding
    space = _space_from_encoded_dir(path.parent.name)

    try:
        ingested = engine.ingest_conversation(
            content=result.conversation,
            space=space,
            agent_id="session-watcher",
            extra_tags=["session-transcript"],
        )
        if isinstance(ingested, str):
            logger.warning("Session watcher ingestion failed for %s: %s", path, ingested)
            return False
        count = len(ingested) if isinstance(ingested, list) else 0
    except Exception as e:
        logger.warning("Session watcher ingestion error for %s: %s", path, e)
        return False

    new_node_ids = [m["node_id"] for m in ingested] if isinstance(ingested, list) else []
    prev_node_ids = existing.get("node_ids", []) if existing else []
    # prev_offset == 0 means a fresh/whole re-ingest; don't carry stale cumulative turns.
    prev_turns = existing.get("user_turns", 0) if (existing and prev_offset > 0) else 0

    state[rel] = {
        "hash": h,
        "end_offset": result.end_offset,
        "last_ingested": datetime.now(timezone.utc).isoformat(),
        "session_id": result.session_id,
        "space": space,
        "user_turns": prev_turns + result.user_turn_count,
        "node_ids": prev_node_ids + new_node_ids,
    }
    _save_state(watch_dir, state)

    logger.info(
        "Session watcher ingested %s (%d new turns, %d memories extracted)",
        rel, result.user_turn_count, count,
    )
    return True
```

- [ ] **Step 7: Run the new tests, verify they pass**

Run: `python -m pytest tests/test_background/test_session_watcher.py -k "incremental or shrink" -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Run the full watcher suite — no regressions**

Run: `python -m pytest tests/test_background/test_session_watcher.py -v`
Expected: PASS — existing tests still green. `test_ingest_session_basic` still sees `user_turns == 6` (first ingest, `prev_offset == 0`); `test_min_turns_filter` still skips (3 < 5); `test_unchanged_session_skipped` still skips on equal hash; `test_state_persistence` unaffected (state JSON is generic).

- [ ] **Step 9: Lint**

Run: `ruff check src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(session-watcher): ingest only appended turns via byte cursor (#33)"
```

---

## Self-review checklist (run before opening the PR)

- [ ] `parse_transcript(path, start_offset=prev_offset)` is the only parse call; `end_offset` persisted every successful ingest.
- [ ] `min_turns` now gates the new slice; first-ever ingest unchanged.
- [ ] Shrink (`size < prev_offset`) resets to 0; cumulative `user_turns` not double-counted on reset.
- [ ] No change to `parser.py`, `scheduler.py`, or config.
- [ ] Full suite: `python -m pytest tests/ -v` green (excluding pre-existing unrelated failures).

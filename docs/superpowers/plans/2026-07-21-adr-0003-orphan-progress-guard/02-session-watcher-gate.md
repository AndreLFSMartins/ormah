# Task 2: Gate the session-watcher rewind

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (the `leading_orphan` block inside
  `_ingest_session`, ~line 774 on this branch)
- Test: `tests/test_background/test_session_watcher.py` (two new module-level tests)

**Interfaces:**
- Consumes: `should_rewind(result, start_offset) -> bool` from Task 1
  (`from ormah.transcript.parser import parse_transcript, should_rewind`).
- Produces: nothing new — behavior change only. The state entry's `end_offset` becomes
  strictly monotonic for the #149 byte pattern.

Existing helpers in the test file (do not redefine): `_mark_idle(path)`, `_LLM_PATCH`,
`_LLM_RESPONSE`; `parse_transcript` is already imported at the top; `_ingest_session` and
`IngestResult` come from the `from ormah.background.session_watcher import (...)` block —
add them there if missing. Add `import logging` if the file does not import it.

- [ ] **Step 1: Write the failing regression test (the #149 loop)**

```python
def test_api_error_orphan_advances_without_reingest(engine, tmp_path, caplog):
    """ADR-0003 regression (bug #149): an assistant 'API Error' record right after a
    terminal end_turn flags leading_orphan on the next tick. The watcher must NOT rewind
    to 0 (36x whole-file re-extractions); it drops the fragment, ingests the tail past
    the boundary, and the following tick is a cheap NO_PROGRESS."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"

    first_turn = [
        {"type": "user", "message": {"content": "Prompt one"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer one"}]}},
    ]
    tail = [
        {"type": "assistant", "message": {"stop_reason": "stop_sequence",
            "content": [{"type": "text",
                "text": "API Error: Connection closed mid-response."}]}},
        {"type": "user", "message": {"content": "continue"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in first_turn:
            f.write(json.dumps(line) + "\n")
    boundary = parse_transcript(jsonl).safe_end_offset  # where tick N parked the cursor
    with open(jsonl, "a") as f:
        for line in tail:
            f.write(json.dumps(line) + "\n")
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": boundary, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 1)
        assert r1 == IngestResult.OK
        assert "recovering legacy mid-response cursor" not in caplog.text  # no rewind
        assert state[rel]["end_offset"] == jsonl.stat().st_size            # tail consumed
        assert state[rel]["end_offset"] > boundary                          # monotonic
        assert mock_llm.call_count == 1
        prompt = str(mock_llm.call_args_list[0])
        assert "Answer one" not in prompt   # slice before the cursor NOT re-ingested
        assert "API Error" not in prompt    # orphan fragment dropped, not committed
        assert "continue" in prompt         # previously-stranded tail IS ingested

        r2 = _ingest_session(engine, jsonl, state, watch_dir, 1)
        assert r2 == IngestResult.NO_PROGRESS   # second tick: nothing re-extracted
        assert mock_llm.call_count == 1
        assert state[rel]["end_offset"] == jsonl.stat().st_size
```

- [ ] **Step 2: Write the failing companion test (legacy recovery preserved)**

```python
def test_no_progress_orphan_still_rewinds(engine, tmp_path, caplog):
    """A genuine legacy mid-response cursor (orphan AND no forward progress) still
    triggers the one-time whole-file recovery, re-pairing the tail with its prompt."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    records = [
        {"type": "user", "message": {"content": "Prompt about the architecture decision"}},
        {"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": "First part"}]}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Second part"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in records:
            f.write(json.dumps(line) + "\n")
    raw = jsonl.read_bytes().splitlines(keepends=True)
    mid = len(raw[0]) + len(raw[1])  # cursor parked mid-response by an older version
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": mid, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 1)
    assert r1 == IngestResult.OK
    assert "recovering legacy mid-response cursor" in caplog.text
    prompt = str(mock_llm.call_args_list[0])
    assert "Prompt about the architecture decision" in prompt  # re-paired from offset 0
    assert state[rel]["end_offset"] == jsonl.stat().st_size
```

- [ ] **Step 2b: Write the residual-case test (ADR consequence: cheap no-op below min_turns)**

```python
def test_below_min_turns_orphan_reparse_is_cheap_noop(engine, tmp_path, caplog):
    """ADR-0003 residual: with the guard, an advanced-but-below-min_turns payload on an
    ACTIVE file defers (TRANSIENT) and re-parses on later ticks as a parse-only no-op —
    no rewind, no LLM call, no duplication — until it idles or crosses min_turns."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"

    first_turn = [
        {"type": "user", "message": {"content": "Prompt one"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer one"}]}},
    ]
    tail = [
        {"type": "assistant", "message": {"stop_reason": "stop_sequence",
            "content": [{"type": "text",
                "text": "API Error: Connection closed mid-response."}]}},
        {"type": "user", "message": {"content": "continue"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in first_turn:
            f.write(json.dumps(line) + "\n")
    boundary = parse_transcript(jsonl).safe_end_offset
    with open(jsonl, "a") as f:
        for line in tail:
            f.write(json.dumps(line) + "\n")
    # NO _mark_idle: mtime is fresh, so the file is ACTIVE and 1 turn < min_turns=5 defers.

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": boundary, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 5)
        r2 = _ingest_session(engine, jsonl, state, watch_dir, 5)
    assert r1 == IngestResult.TRANSIENT and r2 == IngestResult.TRANSIENT  # defer, retry later
    assert "recovering legacy mid-response cursor" not in caplog.text     # never rewinds
    assert mock_llm.call_count == 0                                       # parse-only no-op
    assert state[rel]["end_offset"] == boundary                           # cursor held, not lost
```

- [ ] **Step 2c: Write the accepted-loss pinning test (council ajuste #1)**

```python
def test_legacy_orphan_with_later_turns_advances_and_drops(engine, tmp_path, caplog):
    """ADR-0003 accepted-loss pinning (watcher level): a genuine legacy mid-response cursor
    in a file that ALSO has later closed turns → no rewind, the fragment tail is dropped
    (bounded, one-time loss), the later turn is ingested, cursor reaches EOF."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    records = [
        {"type": "user", "message": {"content": "Prompt one"}},
        {"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": "First part"}]}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Second part"}]}},
        {"type": "user", "message": {"content": "Prompt two"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in records:
            f.write(json.dumps(line) + "\n")
    raw = jsonl.read_bytes().splitlines(keepends=True)
    mid = len(raw[0]) + len(raw[1])  # legacy cursor parked mid-response
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": mid, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 1)
    assert r1 == IngestResult.OK
    assert "recovering legacy mid-response cursor" not in caplog.text  # ADR: no rewind
    assert state[rel]["end_offset"] == jsonl.stat().st_size
    prompt = str(mock_llm.call_args_list[0])
    assert "Second part" not in prompt   # the accepted, bounded loss
    assert "Prompt one" not in prompt    # pre-cursor content not re-ingested
    assert "Prompt two" in prompt        # later turn ingested normally
```

- [ ] **Step 3: Run all four — verify 1, 2b and 2c fail, the legacy one passes**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_session_watcher.py::test_api_error_orphan_advances_without_reingest \
  tests/test_background/test_session_watcher.py::test_below_min_turns_orphan_reparse_is_cheap_noop \
  tests/test_background/test_session_watcher.py::test_legacy_orphan_with_later_turns_advances_and_drops \
  tests/test_background/test_session_watcher.py::test_no_progress_orphan_still_rewinds -v )
```

Expected: `test_api_error_orphan_advances_without_reingest`,
`test_below_min_turns_orphan_reparse_is_cheap_noop` and
`test_legacy_orphan_with_later_turns_advances_and_drops` FAIL on
`assert "recovering legacy mid-response cursor" not in caplog.text` (the unguarded rewind
fires today); `test_no_progress_orphan_still_rewinds` PASSES (documents current legacy
behavior).

- [ ] **Step 4: Gate the rewind**

In `src/ormah/background/session_watcher.py`, find the import of `parse_transcript` and
extend it to also import `should_rewind`. Then replace, inside `_ingest_session`:

```python
        result = parse_transcript(path, start_offset=prev_offset)
        if result.leading_orphan:
            # A cursor left mid-response by an older version: re-parse the whole file so
            # the dropped tail is recovered and re-paired with its prompt. A one-time
            # re-ingest of this file; the background dedup jobs reconcile any overlap.
            logger.info("Session watcher recovering legacy mid-response cursor for %s", rel)
            prev_offset = 0
            result = parse_transcript(path, start_offset=0)
```

with:

```python
        result = parse_transcript(path, start_offset=prev_offset)
        if should_rewind(result, prev_offset):
            # Orphan with NO forward progress: a genuine cursor left mid-response by an
            # older version. Re-parse the whole file so the dropped tail is re-paired with
            # its prompt. With forward progress the orphan is a false positive (ADR-0003,
            # #149): the fragment is dropped and the cursor advances — rewinding there
            # would re-ingest the whole file on every tick forever.
            logger.info("Session watcher recovering legacy mid-response cursor for %s", rel)
            prev_offset = 0
            result = parse_transcript(path, start_offset=0)
```

- [ ] **Step 5: Run the file's full suite — verify green**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_session_watcher.py -q )
```

Expected: all pass — including the two new tests and every pre-existing recovery test.

- [ ] **Step 6: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py && \
  git commit -m "fix(session-watcher): drop orphan fragment on progress instead of rewinding (#149)" )
```

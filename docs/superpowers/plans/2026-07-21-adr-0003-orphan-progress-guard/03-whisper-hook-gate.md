# Task 3: Gate the whisper-hook rewind

**Files:**
- Modify: `src/ormah/adapters/cli_adapter.py` (the `leading_orphan` block inside
  `cmd_whisper_store`, ~line 447 on this branch)
- Test: `tests/test_whisper/test_whisper_out.py` (one new test in `TestWhisperStoreCursor`)

**Interfaces:**
- Consumes: `should_rewind(result, start_offset) -> bool` from Task 1.
- Produces: nothing new — behavior change only. The whisper cursor becomes strictly
  monotonic for the #149 byte pattern.

Existing helpers in the test file (do not redefine): `_run_cli(args, monkeypatch, stdin_text)`,
`_mock_response(data)`; `httpx` and `json` are already imported. The existing test
`TestWhisperStoreCursor::test_legacy_mid_response_cursor_recovered` covers the genuine
legacy case (orphan + no progress → rewind) and MUST keep passing untouched.

- [ ] **Step 1: Write the failing test**

Add to `class TestWhisperStoreCursor`:

```python
    def test_api_error_orphan_advances_cursor_without_full_reextract(
        self, monkeypatch, tmp_path
    ):
        """ADR-0003 regression (bug #149, hook path): a false-positive leading_orphan —
        an assistant 'API Error' record right after the end_turn boundary the cursor is
        parked on — must not re-send the whole transcript. The orphan is dropped and only
        the tail past the cursor is sent; the cursor advances to EOF."""
        monkeypatch.setattr("ormah.adapters.cli_adapter.settings.whisper_out_min_turns", 1)
        transcript = tmp_path / "session.jsonl"
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
        transcript.write_text("\n".join(json.dumps(r) for r in first_turn) + "\n")
        from ormah.transcript.parser import parse_transcript
        boundary = parse_transcript(transcript).safe_end_offset
        with transcript.open("a") as f:
            for r in tail:
                f.write(json.dumps(r) + "\n")

        from ormah.adapters.cli_adapter import _WHISPER_CURSOR_DIR, _WHISPER_CURSOR_FILE
        _WHISPER_CURSOR_DIR.mkdir(parents=True, exist_ok=True)
        _WHISPER_CURSOR_FILE.write_text(json.dumps({"sess1": boundary}))

        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return _mock_response({"status": "processed", "extracted": 1, "memories": []})

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "ormah.adapters.cli_adapter._whisper_store_client",
            lambda: httpx.Client(transport=transport, base_url="http://test"),
        )
        hook_input = json.dumps({
            "transcript_path": str(transcript), "cwd": "/tmp",
            "session_id": "sess1", "trigger": "auto",
        })

        _run_cli(["whisper", "store"], monkeypatch, stdin_text=hook_input)

        assert len(bodies) == 1
        assert "Answer one" not in bodies[0]["content"]  # no whole-file re-extract
        assert "API Error" not in bodies[0]["content"]   # orphan fragment dropped
        assert "continue" in bodies[0]["content"]        # stranded tail recovered
        cursors = json.loads(_WHISPER_CURSOR_FILE.read_text())
        assert cursors["sess1"] == transcript.stat().st_size  # cursor monotonic, at EOF
```

- [ ] **Step 2: Run it — verify it fails for the right reason**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  "tests/test_whisper/test_whisper_out.py::TestWhisperStoreCursor::test_api_error_orphan_advances_cursor_without_full_reextract" -v )
```

Expected: FAIL on `assert "Answer one" not in bodies[0]["content"]` — the unguarded rewind
re-parses from 0 and re-sends the whole transcript.

- [ ] **Step 3: Gate the rewind**

In `src/ormah/adapters/cli_adapter.py`, inside `cmd_whisper_store`, replace:

```python
    from ormah.transcript.parser import parse_transcript

    try:
        result = parse_transcript(path, start_offset=start_offset)
        if result.leading_orphan:
            # Cursor left mid-response by an older version: re-parse from the start to
            # recover the dropped tail with its prompt (one-time full re-extract).
            start_offset = 0
            result = parse_transcript(path, start_offset=0)
    except Exception:
        sys.exit(0)
```

with:

```python
    from ormah.transcript.parser import parse_transcript, should_rewind

    try:
        result = parse_transcript(path, start_offset=start_offset)
        if should_rewind(result, start_offset):
            # Orphan with NO forward progress: a genuine cursor left mid-response by an
            # older version — re-parse from the start to recover the dropped tail with its
            # prompt. With forward progress the orphan is a false positive (ADR-0003,
            # #149): drop the fragment and advance, or every hook fire re-extracts the
            # whole transcript.
            start_offset = 0
            result = parse_transcript(path, start_offset=0)
    except Exception:
        sys.exit(0)
```

- [ ] **Step 4: Run the whisper suite — verify green (including the legacy test)**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_whisper/test_whisper_out.py -q )
```

Expected: all pass — `test_legacy_mid_response_cursor_recovered` (no-progress → still
rewinds) and the new false-positive test both green.

- [ ] **Step 5: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  git add src/ormah/adapters/cli_adapter.py tests/test_whisper/test_whisper_out.py && \
  git commit -m "fix(whisper-hook): drop orphan fragment on progress instead of rewinding (#149)" )
```

# Task 1: `should_rewind` predicate in the parser

**Files:**
- Modify: `src/ormah/transcript/parser.py` (add one function after `parse_transcript`)
- Test: `tests/test_transcript/test_parser.py` (new class `TestShouldRewind`)

**Interfaces:**
- Consumes: `parse_transcript(path, start_offset=0) -> TranscriptResult` (existing);
  `TranscriptResult.leading_orphan: bool`, `TranscriptResult.safe_end_offset: int` (existing).
- Produces: `should_rewind(result: TranscriptResult, start_offset: int) -> bool` — Tasks 2 e 3
  importam exatamente `from ormah.transcript.parser import parse_transcript, should_rewind`.

- [ ] **Step 0: Create the worktree** (one-time setup for the whole plan; skip if it exists)

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch upstream
git -C /Users/andre/Documents/GitHub/Tools/ormah worktree add \
  /Users/andre/Documents/GitHub/Tools/ormah-wt-149 \
  -b fix/leading-orphan-progress-guard upstream/main
```

Expected: `Preparing worktree (new branch 'fix/leading-orphan-progress-guard')`. Do NOT touch
the main clone's checkout. All subsequent steps run inside
`/Users/andre/Documents/GitHub/Tools/ormah-wt-149`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcript/test_parser.py`. Update the import at the top of the file to:

```python
from ormah.transcript.parser import extract_user_prompts, parse_transcript, should_rewind
```

Then add (module level, after the existing classes):

```python
class TestShouldRewind:
    """ADR-0003: rewind only on NO forward progress; an orphan-with-progress is dropped."""

    def _api_error_lines(self):
        return [
            {"type": "user", "message": {"content": "Prompt one"}},
            {"type": "assistant", "message": {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Answer one"}]}},
            {"type": "assistant", "message": {"stop_reason": "stop_sequence",
                "content": [{"type": "text",
                    "text": "API Error: Connection closed mid-response."}]}},
            {"type": "user", "message": {"content": "continue"}},
            {"type": "assistant", "message": {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Answer two"}]}},
        ]

    def test_api_error_orphan_with_progress_does_not_rewind(self, tmp_path):
        """The #149 byte pattern: end_turn boundary, then an assistant 'API Error' record
        before the next user turn. The orphan flag fires (false positive) but the parse
        still advances the safe boundary — so no rewind, and the tail is usable."""
        lines = self._api_error_lines()
        path = _write_jsonl(tmp_path, lines[:2])
        boundary = parse_transcript(path).safe_end_offset
        assert boundary == path.stat().st_size  # cursor parks exactly on the end_turn boundary
        with open(path, "a") as f:
            for line in lines[2:]:
                f.write(json.dumps(line) + "\n")

        result = parse_transcript(path, start_offset=boundary)
        assert result.leading_orphan is True          # the false positive is still flagged
        assert result.safe_end_offset > boundary      # but the parse made forward progress
        assert should_rewind(result, boundary) is False
        assert result.safe_user_turn_count == 1
        assert "API Error" not in result.safe_conversation  # orphan fragment dropped

    def test_no_progress_orphan_rewinds(self, tmp_path):
        """A genuine legacy cursor parked mid-response: orphan AND no forward progress."""
        lines = [
            {"type": "user", "message": {"content": "Prompt one"}},
            {"type": "assistant", "message": {"stop_reason": "tool_use",
                "content": [{"type": "text", "text": "First part"}]}},
            {"type": "assistant", "message": {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Second part"}]}},
        ]
        path = _write_jsonl(tmp_path, lines)
        raw = path.read_bytes().splitlines(keepends=True)
        mid = len(raw[0]) + len(raw[1])  # cursor saved mid-response by an older version

        result = parse_transcript(path, start_offset=mid)
        assert result.leading_orphan is True
        assert result.safe_end_offset == mid          # nothing closed: no progress
        assert should_rewind(result, mid) is True

    def test_no_orphan_never_rewinds_even_without_progress(self, tmp_path):
        """No-progress alone (in-flight tail) must not rewind — only orphan+no-progress does."""
        path = _write_jsonl(tmp_path, [{"type": "user", "message": {"content": "hi"}}])
        result = parse_transcript(path, start_offset=0)
        assert result.leading_orphan is False
        assert result.safe_end_offset == 0
        assert should_rewind(result, 0) is False

    def test_large_orphan_with_progress_does_not_rewind(self, tmp_path):
        """ADR-0003 large-orphan variant: a giant orphan fragment before the first user turn
        still yields progress (boundary reaches the closed turn after it) — no rewind."""
        big = "x" * 50_000
        prefix = self._api_error_lines()[:2]
        tail = [
            {"type": "assistant", "message": {"stop_reason": "tool_use",
                "content": [{"type": "text", "text": big}]}}
            for _ in range(3)
        ] + self._api_error_lines()[3:]  # user("continue") + assistant(end_turn)
        path = _write_jsonl(tmp_path, prefix)
        boundary = parse_transcript(path).safe_end_offset
        with open(path, "a") as f:
            for line in tail:
                f.write(json.dumps(line) + "\n")

        result = parse_transcript(path, start_offset=boundary)
        assert result.leading_orphan is True
        assert should_rewind(result, boundary) is False

    def test_legacy_orphan_with_later_turns_drops_fragment(self, tmp_path):
        """ADR-0003 accepted-loss pinning (council R1, Cursor+Codex): a GENUINE legacy
        cursor mid-response whose file also contains later closed turns. The fragment tail
        is dropped (its head was already ingested before the cursor; the loss is bounded
        and one-time) and the cursor advances — deliberately NO rewind. If this assertion
        ever needs to change, re-open ADR-0003 first."""
        lines = [
            {"type": "user", "message": {"content": "Prompt one"}},
            {"type": "assistant", "message": {"stop_reason": "tool_use",
                "content": [{"type": "text", "text": "First part"}]}},
            {"type": "assistant", "message": {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Second part"}]}},
            {"type": "user", "message": {"content": "Prompt two"}},
            {"type": "assistant", "message": {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Answer two"}]}},
        ]
        path = _write_jsonl(tmp_path, lines)
        raw = path.read_bytes().splitlines(keepends=True)
        mid = len(raw[0]) + len(raw[1])  # legacy cursor parked mid-response

        result = parse_transcript(path, start_offset=mid)
        assert result.leading_orphan is True
        assert result.safe_end_offset > mid                    # later turn closed → progress
        assert should_rewind(result, mid) is False             # ADR-0003: drop, don't rewind
        assert "Second part" not in result.safe_conversation   # the accepted, bounded loss
        assert "Prompt two" in result.safe_conversation        # later turn fully usable
        assert "Answer two" in result.safe_conversation
```

- [ ] **Step 2: Run the tests — verify they fail for the right reason**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_transcript/test_parser.py::TestShouldRewind -v )
```

Expected: collection error `ImportError: cannot import name 'should_rewind'`. (An assertion
failure instead of the ImportError means the import line was not updated — fix that first.)

- [ ] **Step 3: Implement the predicate**

In `src/ormah/transcript/parser.py`, immediately AFTER the end of `parse_transcript`:

```python
def should_rewind(result: TranscriptResult, start_offset: int) -> bool:
    """Gate the leading-orphan recovery on forward progress (ADR-0003, bug #149).

    Rewind (re-parse from offset 0) only when the flagged parse made no forward
    progress — the orphan consumed the whole slice, i.e. a genuine legacy
    mid-response cursor. When the safe boundary still advanced past the cursor,
    the orphan is a false positive (e.g. an "API Error" assistant record right
    after a terminal stop_reason): the fragment is dropped and the cursor moves
    on. Rewinding there re-ingests the whole file on every tick forever, because
    the trigger is a permanent property of the file's bytes.
    """
    return result.leading_orphan and result.safe_end_offset <= start_offset
```

- [ ] **Step 4: Run the tests — verify they pass**

Same command as Step 2. Expected: `5 passed`. Also run the whole parser suite:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-149/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_transcript/test_parser.py -q )
```

Expected: all pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-149 && \
  git add src/ormah/transcript/parser.py tests/test_transcript/test_parser.py && \
  git commit -m "feat(parser): should_rewind gates orphan recovery on forward progress (#149)" )
```

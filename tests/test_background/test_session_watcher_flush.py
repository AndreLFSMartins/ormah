import json

import pytest
from pydantic import ValidationError

from ormah.config import Settings


def _write_turns(path, turns: int = 4, pad: int = 20000) -> None:
    lines = []
    for i in range(turns):
        lines.append({"type": "user", "message": {"role": "user", "content": f"u{i} " + "x" * pad}})
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": f"a{i}"}], "stop_reason": "end_turn"}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_flush_defaults():
    s = Settings()
    assert s.session_watcher_flush_bytes == 60000
    assert s.session_watcher_retry_seconds == 30.0     # decoupled from idle
    assert s.session_watcher_idle_threshold == 600.0   # policy A
    assert s.session_watcher_flush_bytes <= s.ingest_max_content_chars


def test_flush_bytes_over_cap_rejected():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=200000, ingest_max_content_chars=100000)


def test_flush_bytes_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_bytes=500)


def test_flush_bytes_equal_cap_allowed():
    s = Settings(session_watcher_flush_bytes=100000, ingest_max_content_chars=100000)
    assert s.session_watcher_flush_bytes == s.ingest_max_content_chars


def test_retry_seconds_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_retry_seconds=0)


def test_parse_transcript_max_bytes_breaks_before_overshoot(tmp_path):
    """A multi-turn slice must never exceed max_bytes — break BEFORE committing the
    turn that would push it over, not after."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "big.jsonl"
    _write_turns(p, turns=4, pad=20000)

    full = parse_transcript(p)
    capped = parse_transcript(p, max_bytes=60000)

    assert 0 < capped.safe_end_offset < full.safe_end_offset
    assert capped.safe_end_offset <= 60000        # start_offset == 0 here
    assert capped.capped is True
    assert capped.safe_user_turn_count < full.user_turn_count

    # Draining the remainder from the new cursor must make more progress and
    # eventually reach EOF (proves the left-behind turn isn't lost).
    next_slice = parse_transcript(p, start_offset=capped.safe_end_offset, max_bytes=60000)
    assert next_slice.safe_end_offset - capped.safe_end_offset <= 60000
    assert next_slice.safe_user_turn_count > 0


def test_parse_transcript_max_bytes_none_preserves_behavior(tmp_path):
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "small.jsonl"
    _write_turns(p, turns=2, pad=100)

    default = parse_transcript(p)
    explicit_none = parse_transcript(p, max_bytes=None)

    assert default.safe_end_offset == explicit_none.safe_end_offset
    assert default.capped is False
    assert explicit_none.capped is False


def test_parse_transcript_single_oversized_turn_commits_anyway(tmp_path):
    """A single turn bigger than max_bytes can't make empty progress — commit it as
    its own slice rather than starving the drain forever."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "oneturn.jsonl"
    _write_turns(p, turns=1, pad=20000)

    result = parse_transcript(p, max_bytes=5000)
    assert result.safe_user_turn_count == 1
    assert result.safe_end_offset > 5000  # unavoidable overshoot for a lone oversized turn

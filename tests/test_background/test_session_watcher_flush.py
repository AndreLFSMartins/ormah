import json
import os
import time
from types import SimpleNamespace

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


def test_byte_gate():
    from ormah.background.session_watcher import _pending_bytes, _should_flush

    assert _pending_bytes(prev_offset=0, payload_offset=5000) == 5000
    assert _should_flush(pending=5000, is_idle=False, flush_bytes=60000) is False
    assert _should_flush(pending=60000, is_idle=False, flush_bytes=60000) is True
    assert _should_flush(pending=10, is_idle=True, flush_bytes=60000) is True


class _FakeConn:
    """Minimal stand-in for engine.db.conn — no whisper_log rows, so usage-signal
    mining short-circuits immediately and session-id/space lookups return nothing."""

    def execute(self, *args, **kwargs):
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def commit(self):
        pass


class _FakeEngine:
    """Records the byte length of every content payload sent to ingestion."""

    def __init__(self, flush_bytes: int = 60000, idle_threshold: float = 600.0):
        self.settings = SimpleNamespace(
            feedback_llm_judge_enabled=False,
            llm_enabled=False,
            session_watcher_flush_bytes=flush_bytes,
            session_watcher_idle_threshold=idle_threshold,
        )
        self.db = SimpleNamespace(conn=_FakeConn())
        self.recorded_lengths: list[int] = []

    def ingest_conversation(self, content, **kwargs):
        self.recorded_lengths.append(len(content))
        return [{"node_id": "n"}]


def _write_big_backlog(path, turns: int = 8) -> None:
    """A JSONL transcript whose closed content is well over flush_bytes (60000)."""
    _write_turns(path, turns=turns, pad=20000)


def test_ingest_session_drain_continuation_self_triggers(tmp_path):
    """Production wiring: a cap-limited flush calls on_defer_active so the retry Timer
    drains the next slice, instead of stalling after one slice until the next append.

    Drives the SAME continuation the retry Timer would in production — on_defer_active
    re-invokes _ingest_session for the same path — rather than a test-only while loop,
    so this actually proves the code self-continues.
    """
    from ormah.background.session_watcher import IngestResult, _ingest_session
    from ormah.transcript.parser import parse_transcript

    watch_dir = tmp_path
    path = watch_dir / "big.jsonl"
    _write_big_backlog(path)

    # Backdate mtime so the session reads as idle: the gate flushes on every call
    # regardless of the byte threshold, so the backlog fully drains.
    now = time.time()
    os.utime(path, (now, now - 700))

    engine = _FakeEngine()
    flush_bytes = 60000
    state: dict = {}
    rel = str(path.relative_to(watch_dir))
    retrigger_count = 0

    def run(depth: int = 0) -> None:
        nonlocal retrigger_count
        assert depth < 20, "drain did not self-terminate"

        def on_defer_active() -> None:
            nonlocal retrigger_count
            retrigger_count += 1
            run(depth + 1)

        _ingest_session(
            engine, path, state, watch_dir, min_turns=1,
            flush_bytes=flush_bytes, on_defer_active=on_defer_active,
        )

    run()

    assert engine.recorded_lengths, "expected at least one ingest call"
    # Proves the cap-limited slice actually retriggered the drain (not a no-op wiring).
    assert retrigger_count > 0

    one_turn_margin = 200  # break-before caps a multi-turn slice strictly <= flush_bytes
    for length in engine.recorded_lengths:
        assert length <= flush_bytes + one_turn_margin

    full = parse_transcript(path)
    assert state[rel]["end_offset"] == full.safe_end_offset


def test_ingest_session_subcap_flush_does_not_retrigger(tmp_path):
    """A flush that drains the whole closed delta (sub-cap) must not re-schedule —
    there is nothing left to drain."""
    from ormah.background.session_watcher import _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "small.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi there"}},
        {"type": "assistant", "message": {"role": "assistant",
                  "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    now = time.time()
    os.utime(path, (now, now - 700))  # idle -> flushes despite being far under flush_bytes

    engine = _FakeEngine()
    state: dict = {}
    defer_calls = []
    result = _ingest_session(
        engine, path, state, watch_dir, min_turns=1,
        flush_bytes=60000, on_defer_active=lambda: defer_calls.append(True),
    )

    from ormah.background.session_watcher import IngestResult
    assert result == IngestResult.OK
    assert engine.recorded_lengths
    assert not defer_calls


def test_ingest_session_active_session_flushes_when_over_flush_bytes(tmp_path):
    """Primary production trigger: an active (non-idle) session whose closed content
    crosses flush_bytes flushes immediately, without waiting for idle."""
    from ormah.background.session_watcher import IngestResult, _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "active.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "u " + "x" * 70000}},
        {"type": "assistant", "message": {"role": "assistant",
                  "content": [{"type": "text", "text": "a"}], "stop_reason": "end_turn"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    # mtime left fresh (not backdated) — the file is NOT idle.

    engine = _FakeEngine()
    state: dict = {}
    result = _ingest_session(engine, path, state, watch_dir, min_turns=1, flush_bytes=60000)

    assert result == IngestResult.OK
    assert engine.recorded_lengths


def test_ingest_session_active_small_session_defers(tmp_path):
    """An active (non-idle) session below flush_bytes defers (TRANSIENT), then flushes
    once idle."""
    from ormah.background.session_watcher import IngestResult, _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "active_small.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi there"}},
        {"type": "assistant", "message": {"role": "assistant",
                  "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    # mtime fresh (not idle) — small transcript, well under flush_bytes.

    engine = _FakeEngine()
    state: dict = {}
    assert _ingest_session(
        engine, path, state, watch_dir, min_turns=1, flush_bytes=60000,
    ) == IngestResult.TRANSIENT
    assert not engine.recorded_lengths

    now = time.time()
    os.utime(path, (now, now - 700))
    assert _ingest_session(
        engine, path, state, watch_dir, min_turns=1, flush_bytes=60000,
    ) == IngestResult.OK
    assert engine.recorded_lengths


def test_scan_sessions_honors_settings_flush_bytes(tmp_path):
    """_scan_sessions must read flush_bytes/idle_threshold from engine.settings, not the
    _ingest_session defaults — otherwise a tuned (lowered) flush_bytes has no effect on the
    startup catch-up scan."""
    from ormah.background.session_watcher import _scan_sessions

    watch_dir = tmp_path
    path = watch_dir / "small.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "u " + "x" * 2000}},
        {"type": "assistant", "message": {"role": "assistant",
                  "content": [{"type": "text", "text": "a"}], "stop_reason": "end_turn"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    # Not idle and well below the function's default flush_bytes (60000), but above a
    # lowered setting — only flushes if _scan_sessions actually threads the setting through.
    engine = _FakeEngine(flush_bytes=1000, idle_threshold=600.0)

    count = _scan_sessions(engine, watch_dir, min_turns=1, lookback_hours=72)

    assert count == 1
    assert engine.recorded_lengths


def test_prompt_is_delta_first():
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT

    filled = _INGEST_LLM_PROMPT.format(conversation="SENTINEL_CONVO")
    assert filled.index("SENTINEL_CONVO") < filled.index("What to extract")


def test_extraction_truncation_is_logged(tmp_path, caplog):
    """A single closed turn whose cleaned text exceeds ingest_max_content_chars is still
    truncated (unavoidable for one oversized turn) — but the loss must be observable."""
    import logging
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(
        memory_dir=tmp_path, ingest_max_content_chars=1000, session_watcher_flush_bytes=1000,
    )
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate",
            return_value='{"memories": []}',
        ), caplog.at_level(logging.WARNING, logger="ormah.engine.memory_engine"):
            engine._extract_memories_llm("x" * 5000)
    finally:
        engine.shutdown()

    assert any("truncated" in r.message for r in caplog.records)

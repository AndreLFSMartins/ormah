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
    assert s.session_watcher_flush_chars == 60000   # ~15K tokens of CONVERSATION
    assert s.session_watcher_retry_seconds == 30.0     # decoupled from idle
    assert s.session_watcher_idle_threshold == 600.0   # policy A
    assert s.session_watcher_flush_chars <= s.ingest_max_content_chars


def test_flush_chars_over_cap_rejected():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=200000, ingest_max_content_chars=100000,
                 ingest_chunk_chars=200000)


def test_flush_chars_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=500)


def test_flush_chars_equal_cap_allowed():
    s = Settings(session_watcher_flush_chars=100000, ingest_max_content_chars=100000,
                 ingest_chunk_chars=100000)
    assert s.session_watcher_flush_chars == s.ingest_max_content_chars


@pytest.fixture(autouse=True)
def _reset_deprecation_warn_once():
    """The warning is once-per-process, so without this reset the SECOND deprecation test in a
    pytest session sees no record and fails (council R2, Cursor). Reset before and after so test
    order never matters."""
    import ormah.config as cfg

    cfg._warned_flush_bytes = False
    yield
    cfg._warned_flush_bytes = False


def test_deprecated_flush_bytes_env_var_warns_and_is_ignored(monkeypatch, caplog):
    """The unit changed, so the old value is not translatable. Honouring it would silently
    reinterpret a tuned number; swallowing it silently (today's `extra: ignore`) hides the
    change. Warn, and use the new default."""
    import logging

    monkeypatch.setenv("ORMAH_SESSION_WATCHER_FLUSH_BYTES", "200000")
    with caplog.at_level(logging.WARNING, logger="ormah.config"):
        s = Settings()

    assert s.session_watcher_flush_chars == 60000  # the stale value did NOT leak in
    assert any("ORMAH_SESSION_WATCHER_FLUSH_BYTES" in r.message for r in caplog.records)
    assert any("unit" in r.message.lower() for r in caplog.records)


def test_deprecated_flush_bytes_in_an_env_FILE_also_warns(tmp_path, monkeypatch, caplog):
    """Council R1 (Codex): Settings loads ~/.config/ormah/.env and ./.env (config.py:11-17), so
    checking os.environ alone misses the LIKELY case -- an operator who set the old key in a
    config file gets no warning, which is precisely the silent migration this task claims to
    prevent."""
    import logging

    import ormah.config as cfg

    env_file = tmp_path / ".env"
    env_file.write_text("ORMAH_SESSION_WATCHER_FLUSH_BYTES=200000\n")

    # Point the scanner at the SAME list Settings resolves. Passing only Settings(_env_file=...)
    # would leave the scanner reading the import-time list and the assertion would pass or fail
    # for the wrong reason (council R2, Cursor).
    monkeypatch.setattr(cfg, "_EXISTING_ENV_FILES", [str(env_file)])
    monkeypatch.delenv("ORMAH_SESSION_WATCHER_FLUSH_BYTES", raising=False)

    assert cfg._deprecated_key_present() is True   # the file path is what is under test

    with caplog.at_level(logging.WARNING, logger="ormah.config"):
        s = Settings(_env_file=str(env_file))

    assert s.session_watcher_flush_chars == 60000
    assert any("ORMAH_SESSION_WATCHER_FLUSH_BYTES" in r.message for r in caplog.records), (
        "the deprecated key was set in an env FILE and produced no warning"
    )


def test_deprecated_key_scanner_ignores_comments_and_partial_names(tmp_path):
    """Presence detection must not fire on a commented-out line or on a longer key that merely
    starts with the deprecated name."""
    import ormah.config as cfg

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# ORMAH_SESSION_WATCHER_FLUSH_BYTES=1\n"
        "ORMAH_SESSION_WATCHER_FLUSH_BYTES_OLD=2\n"
    )
    assert cfg._deprecated_key_present(env_files=[str(env_file)]) is False


def test_deprecated_key_scanner_warns_once_on_unreadable_source(tmp_path, caplog):
    """Review M-9: the repo owner's ordered fix (warn instead of silently `continue` on
    OSError) needs its own coverage -- an unreadable source must produce exactly one warning
    naming the path, not be swallowed."""
    import logging

    import ormah.config as cfg

    # A directory, not a file: Path.read_text() raises IsADirectoryError, a subclass of
    # OSError, without needing to fiddle with real filesystem permissions.
    unreadable = tmp_path / "not_a_file"
    unreadable.mkdir()

    with caplog.at_level(logging.WARNING, logger="ormah.config"):
        present = cfg._deprecated_key_present(env_files=[str(unreadable)])

    assert present is False  # the read failed; nothing was matched, but it must not raise
    matching = [r for r in caplog.records if str(unreadable) in r.message]
    assert len(matching) == 1, (
        f"expected exactly one warning naming {unreadable}, got {len(matching)}: "
        f"{[r.message for r in caplog.records]}"
    )


def test_raw_ceiling_far_below_the_measured_ratio_is_rejected():
    """Council R1 (Cursor): a floor of `>= flush_chars` compares bytes to chars and permits a
    ~200KB ceiling, which would close tool-heavy slices long before the char sweet spot --
    re-creating the axis error Amendment 3 exists to fix, one scale up."""
    with pytest.raises(ValidationError):
        Settings(session_watcher_flush_chars=60000, session_watcher_max_raw_bytes=200000)


def test_retry_seconds_floor():
    with pytest.raises(ValidationError):
        Settings(session_watcher_retry_seconds=0)


def _tool_heavy_turns(path, turns: int, text_chars: int = 500, noise_chars: int = 40000) -> None:
    """Raw bytes >> cleaned chars. See 01-content-budget.md for why plain-text padding is
    useless here: it passes identically under both units and tests nothing."""
    lines = []
    for i in range(turns):
        lines.append({"type": "user", "message": {"role": "user",
                      "content": f"u{i} " + "q" * text_chars}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"blob": "N" * noise_chars}}]}})
        lines.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "M" * noise_chars}]}})
        lines.append({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": f"a{i} " + "r" * text_chars}],
                      "stop_reason": "end_turn"}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_parse_transcript_breaks_before_overshooting_the_content_budget(tmp_path):
    """A multi-turn slice must never exceed the conversation budget — break BEFORE committing
    the turn that would push it over, not after."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "big.jsonl"
    _tool_heavy_turns(p, turns=30, text_chars=2000)

    full = parse_transcript(p)
    capped = parse_transcript(p, max_conversation_chars=60000)

    assert 0 < capped.safe_end_offset < full.safe_end_offset
    assert len(capped.safe_conversation) <= 60000
    # Lower bound, not just an upper one (review I-1): this fixture's raw span passes 60000
    # bytes after a SINGLE turn (noise_chars=40000 * 2 blocks), so a byte-axis cap would also
    # satisfy every assertion above with convo_len~4025/turns=1. Only a genuine char-axis cap
    # commits multiple turns and tens of thousands of cleaned chars -- require that.
    assert len(capped.safe_conversation) > 50_000
    assert capped.capped is True
    assert capped.safe_user_turn_count < full.user_turn_count
    assert capped.safe_user_turn_count > 5

    # Draining the remainder from the new cursor must make more progress and eventually reach
    # EOF (proves the left-behind turn isn't lost).
    next_slice = parse_transcript(
        p, start_offset=capped.safe_end_offset, max_conversation_chars=60000,
    )
    assert len(next_slice.safe_conversation) <= 60000
    assert next_slice.safe_user_turn_count > 0


def test_parse_transcript_no_budget_preserves_behavior(tmp_path):
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "small.jsonl"
    _write_turns(p, turns=2, pad=100)

    default = parse_transcript(p)
    explicit_none = parse_transcript(p, max_conversation_chars=None, max_raw_bytes=None)

    assert default.safe_end_offset == explicit_none.safe_end_offset
    assert default.capped is False
    assert explicit_none.capped is False


def test_parse_transcript_single_oversized_turn_commits_anyway(tmp_path):
    """A single turn bigger than the budget can't make empty progress — commit it as its own
    slice rather than starving the drain forever."""
    from ormah.transcript.parser import parse_transcript

    p = tmp_path / "oneturn.jsonl"
    _write_turns(p, turns=1, pad=20000)

    result = parse_transcript(p, max_conversation_chars=5000)
    assert result.safe_user_turn_count == 1
    assert len(result.safe_conversation) > 5000  # unavoidable for a lone oversized turn


def test_flush_gate():
    """The gate fires on the parser's own capped signal, not a pending-chars comparison:
    break-before capping pins a multi-turn slice's pending chars BELOW flush_chars, so a
    chars-threshold comparison would never fire for the common multi-turn case."""
    from ormah.background.session_watcher import _should_flush

    assert _should_flush(is_idle=False, capped=False) is False
    assert _should_flush(is_idle=False, capped=True) is True
    assert _should_flush(is_idle=True, capped=False) is True


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
    """Records the char length of every content payload sent to ingestion."""

    def __init__(self, flush_chars: int = 60000, idle_threshold: float = 600.0):
        self.settings = SimpleNamespace(
            feedback_llm_judge_enabled=False,
            llm_enabled=False,
            session_watcher_flush_chars=flush_chars,
            session_watcher_idle_threshold=idle_threshold,
        )
        self.db = SimpleNamespace(conn=_FakeConn())
        self.recorded_lengths: list[int] = []

    def ingest_conversation(self, content, **kwargs):
        self.recorded_lengths.append(len(content))
        return [{"node_id": "n"}]


def _write_big_backlog(path, turns: int = 8) -> None:
    """A JSONL transcript whose closed content is well over flush_chars (60000)."""
    _write_turns(path, turns=turns, pad=20000)


def test_ingest_session_drain_continuation_self_triggers(tmp_path):
    """Production wiring: a cap-limited flush calls on_defer_active so the retry Timer
    drains the next slice, instead of stalling after one slice until the next append.

    Drives the SAME continuation the retry Timer would in production — on_defer_active
    re-invokes _ingest_session for the same path — rather than a test-only while loop,
    so this actually proves the code self-continues.
    """
    from ormah.background.session_watcher import _ingest_session
    from ormah.transcript.parser import parse_transcript

    watch_dir = tmp_path
    path = watch_dir / "big.jsonl"
    _write_big_backlog(path)

    # Backdate mtime so the session reads as idle: the gate flushes on every call
    # regardless of the content threshold, so the backlog fully drains.
    now = time.time()
    os.utime(path, (now, now - 700))

    engine = _FakeEngine()
    flush_chars = 60000
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
            flush_chars=flush_chars, on_defer_active=on_defer_active,
        )

    run()

    assert engine.recorded_lengths, "expected at least one ingest call"
    # Proves the cap-limited slice actually retriggered the drain (not a no-op wiring).
    assert retrigger_count > 0

    one_turn_margin = 200  # break-before caps a multi-turn slice strictly <= flush_chars
    for length in engine.recorded_lengths:
        assert length <= flush_chars + one_turn_margin

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
    os.utime(path, (now, now - 700))  # idle -> flushes despite being far under flush_chars

    engine = _FakeEngine()
    state: dict = {}
    defer_calls = []
    result = _ingest_session(
        engine, path, state, watch_dir, min_turns=1,
        flush_chars=60000, on_defer_active=lambda: defer_calls.append(True),
    )

    from ormah.background.session_watcher import IngestResult
    assert result == IngestResult.OK
    assert engine.recorded_lengths
    assert not defer_calls


def test_ingest_session_raw_budget_caps_independently_of_flush_chars(tmp_path):
    """Review I-2: max_raw_bytes has to actually reach parse_transcript through
    _ingest_session's plumbing, not just Settings' ratio validator or a direct
    parse_transcript call. A generous flush_chars (60000) alone would let a tool-heavy
    slice through at convo_len~56384/14 turns (see the content-budget test above); a tight
    max_raw_bytes=8000 must instead bind first and commit a MUCH smaller slice
    (convo_len~4025/1 turn) -- proving the kwarg is wired all the way through, not dropped
    at any of the two _ingest_session call sites or the SessionHandler constructor."""
    from ormah.background.session_watcher import _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "raw_capped.jsonl"
    _tool_heavy_turns(path, turns=30, text_chars=2000)
    now = time.time()
    os.utime(path, (now, now - 700))  # idle -> the gate flushes regardless of which cap bound

    engine = _FakeEngine()
    state: dict = {}
    _ingest_session(
        engine, path, state, watch_dir, min_turns=1,
        flush_chars=60000, max_raw_bytes=8000,
    )

    assert engine.recorded_lengths, "expected at least one ingest call"
    # char_only(flush_chars=60000) commits ~56384 chars; if max_raw_bytes never reached the
    # parser, this test would see that number instead of the raw-bound ~4025.
    assert engine.recorded_lengths[-1] < 10_000, (
        "the committed slice looks bounded by flush_chars, not max_raw_bytes -- "
        "the kwarg likely never reached parse_transcript"
    )


def test_ingest_session_active_session_flushes_when_over_flush_chars(tmp_path):
    """Primary production trigger: an ACTIVE (non-idle) session with MULTIPLE closed turns
    totaling well over flush_chars flushes a full ~flush_chars batch immediately, without
    waiting for idle. This is the common case the content gate exists for — a single turn
    happening to exceed flush_chars is a degenerate edge case, not what this proves."""
    from ormah.background.session_watcher import IngestResult, _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "active.jsonl"
    _write_turns(path, turns=4, pad=20000)  # ~80KB closed content, well over flush_chars
    # mtime left fresh (not backdated) — the file is NOT idle.

    engine = _FakeEngine()
    state: dict = {}
    result = _ingest_session(engine, path, state, watch_dir, min_turns=1, flush_chars=60000)

    assert result == IngestResult.OK
    assert engine.recorded_lengths
    assert engine.recorded_lengths[-1] <= 60000  # break-before caps the committed slice


def test_ingest_session_active_multiturn_below_flush_chars_defers(tmp_path):
    """An active session whose total closed content stays below flush_chars never gets
    capped by the parser, so the gate correctly defers (waits for more or idle)."""
    from ormah.background.session_watcher import IngestResult, _ingest_session

    watch_dir = tmp_path
    path = watch_dir / "active_below_cap.jsonl"
    _write_turns(path, turns=2, pad=100)  # tiny — nowhere near flush_chars
    # mtime left fresh (not backdated) — the file is NOT idle.

    engine = _FakeEngine()
    state: dict = {}
    result = _ingest_session(engine, path, state, watch_dir, min_turns=1, flush_chars=60000)

    assert result == IngestResult.TRANSIENT
    assert not engine.recorded_lengths


def test_ingest_session_active_small_session_defers(tmp_path):
    """An active (non-idle) session below flush_chars defers (TRANSIENT), then flushes
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
    # mtime fresh (not idle) — small transcript, well under flush_chars.

    engine = _FakeEngine()
    state: dict = {}
    assert _ingest_session(
        engine, path, state, watch_dir, min_turns=1, flush_chars=60000,
    ) == IngestResult.TRANSIENT
    assert not engine.recorded_lengths

    now = time.time()
    os.utime(path, (now, now - 700))
    assert _ingest_session(
        engine, path, state, watch_dir, min_turns=1, flush_chars=60000,
    ) == IngestResult.OK
    assert engine.recorded_lengths


def test_prompt_is_delta_first():
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT

    filled = _INGEST_LLM_PROMPT.format(conversation="SENTINEL_CONVO")
    assert filled.index("SENTINEL_CONVO") < filled.index("What to extract")


def test_oversized_turn_is_split_not_truncated(tmp_path, caplog):
    """A single closed turn whose cleaned text exceeds ingest_max_content_chars is split into
    bounded pieces and every piece is extracted — never truncated (council-pr C2). The split must
    be observable."""
    import logging
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(
        memory_dir=tmp_path, ingest_max_content_chars=1000, session_watcher_flush_chars=1000,
    )
    engine = MemoryEngine(settings)
    engine.startup()
    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ), caplog.at_level(logging.WARNING, logger="ormah.engine.memory_engine"):
            engine._extract_memories_llm("x" * 5000)
    finally:
        engine.shutdown()

    assert len(calls) >= 5  # 5000 chars / 1000 cap -> split into >=5 pieces, none truncated
    assert any("split into" in r.message for r in caplog.records)

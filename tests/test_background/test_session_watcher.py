"""Tests for the transcript watcher — auto-ingestion of agent transcripts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ormah.background.session_watcher import (
    SessionHandler,
    _ingest_session,
    _load_state,
    _record_whisper_usage_signals,
    _save_state,
    _scan_sessions,
    _space_from_encoded_dir,
    start_session_watcher,
    stop_session_watcher,
)
from ormah.engine.memory_engine import MemoryEngine
from ormah.models.node import CreateNodeRequest
from ormah.transcript.parser import parse_transcript

_LLM_PATCH = "ormah.background.llm_client.llm_generate"

_LLM_RESPONSE = json.dumps({"memories": [
    {
        "content": "Chose bge-base-en-v1.5 for embeddings because it needs no task prefixes.",
        "type": "decision",
        "title": "Embedding model choice",
        "tags": ["embeddings"],
    },
]})


def _make_jsonl(path: Path, user_turns: int = 6) -> None:
    """Write a minimal JSONL transcript with the given number of user turns."""
    lines = []
    for i in range(user_turns):
        lines.append(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"User message {i} with enough text to parse"},
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": "end_turn", "content": [
                {"type": "text", "text": f"Assistant response {i} with some detail"},
            ]},
        }))
    path.write_text("\n".join(lines) + "\n")


def _mark_idle(path: Path) -> None:
    """Backdate mtime so _ingest_session treats the transcript as finished (idle flush).

    A fresh file is considered active, so its trailing user+assistant block is held back
    until a following user turn (or the idle flush) confirms the response is complete.
    """
    now = time.time()
    os.utime(path, (now, now - 120))


def _write_turn_jsonl(path: Path, prompt: str, response: str) -> None:
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": prompt},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": response}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _write_codex_turn_jsonl(path: Path, prompt: str, response: str) -> None:
    lines = [
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": response}],
            },
        },
        {"type": "event_msg", "payload": {"type": "task_complete"}},  # closes the turn
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _insert_injected_whisper_log(
    engine: MemoryEngine,
    *,
    node_id: str,
    session_id: str,
    prompt: str,
    space: str = "myproject",
) -> int:
    cursor = engine.db.conn.execute(
        "INSERT INTO whisper_log "
        "(session_id, space, prompt_hash, prompt_text, prompt_vec, node_id, score, "
        "was_injected, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (session_id, space, "hash-abc", prompt, b"\x00" * 4, node_id, 0.9, 1),
    )
    engine.db.conn.commit()
    return cursor.lastrowid


# --- Test 1: Space detection from encoded directory names ---

@pytest.mark.parametrize("dirname,expected", [
    ("-Users-johndoe-Projects-ormah", "ormah"),
    ("-Users-alice-Code-my-app", "app"),
    ("-home-bob-projects-foo", "foo"),
    ("", None),
    ("-", None),
    ("simple", "simple"),
])
def test_space_from_encoded_dir(dirname, expected):
    assert _space_from_encoded_dir(dirname) == expected


# --- Test 2: Basic session ingestion ---

def test_ingest_session_basic(engine, tmp_path):
    """A JSONL transcript with enough turns gets ingested and state updated."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result is True
    rel = str(jsonl.relative_to(watch_dir))
    assert rel in state
    entry = state[rel]
    assert entry["session_id"] == "abc123"
    assert entry["source"] == "claude_code"
    assert entry["space"] == "myproject"
    assert entry["user_turns"] == 6
    assert len(entry["node_ids"]) == 1


def test_ingest_codex_session_resolves_rollout_session_id_and_space(engine, tmp_path):
    """Codex rollout filenames are matched back to the whisper_log hook session id."""
    watch_dir = tmp_path / ".codex" / "sessions"
    transcript_dir = watch_dir / "2026" / "06" / "24"
    transcript_dir.mkdir(parents=True)
    jsonl = transcript_dir / "rollout-2026-06-24T12-00-00-sess-456.jsonl"

    prompt = "Why is the Codex watcher less polished?"
    response = (
        "The Codex watcher should resolve rollout filenames through whisper_log session ids "
        "instead of trusting the transcript filename stem."
    )
    _write_codex_turn_jsonl(jsonl, prompt, response)
    _mark_idle(jsonl)  # finished single-turn session → idle flush

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Codex watcher rollout filenames should be resolved through whisper_log session ids.",
        type="fact",
        title="Codex watcher session id resolution",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="sess-456",
        prompt=prompt,
        space="ormah",
    )

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True

    rel = str(jsonl.relative_to(watch_dir))
    entry = state[rel]
    assert entry["session_id"] == "sess-456"
    assert entry["source"] == "codex"
    assert entry["space"] == "ormah"
    assert entry["signals_recorded"] == 1

    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal is not None
    assert signal["session_id"] == "sess-456"
    assert signal["agent_id"] == "codex"
    assert signal["polarity"] == 1


def test_ingest_codex_session_without_whisper_log_does_not_infer_date_space(engine, tmp_path):
    """Codex date folders are storage layout, not project space."""
    watch_dir = tmp_path / ".codex" / "sessions"
    transcript_dir = watch_dir / "2026" / "06" / "24"
    transcript_dir.mkdir(parents=True)
    jsonl = transcript_dir / "rollout-2026-06-24T12-00-00-no-log.jsonl"
    _write_codex_turn_jsonl(jsonl, "Prompt with enough content", "Response with enough content")
    _mark_idle(jsonl)  # finished single-turn session → idle flush

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True

    entry = state[str(jsonl.relative_to(watch_dir))]
    assert entry["source"] == "codex"
    assert entry["space"] is None


def test_record_whisper_usage_signal_promotes_clear_reference(engine, tmp_path):
    """Clear references in an assistant response create a signal and affinity row."""
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "usage-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="usage-session",
        prompt=prompt,
    )

    recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal is not None
    assert signal["signal_type"] == "whisper_referenced"
    assert signal["polarity"] == 1
    assert signal["source"] == "transcript_watcher_heuristic"
    assert signal["surface"] == "transcript_watcher"
    assert signal["agent_id"] == "claude_code"

    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["node_id"] == node_id
    assert affinity["signal"] == 1
    assert affinity["source"] == "auto_heuristic"


def test_record_whisper_usage_signal_keeps_unreferenced_neutral(engine, tmp_path):
    """Unreferenced whispers are observable but do not become negative affinity."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "neutral-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="neutral-session",
        prompt=prompt,
    )

    recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal is not None
    assert signal["signal_type"] == "whisper_unreferenced"
    assert signal["polarity"] == 0

    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is None


def test_llm_judge_disabled_by_default(engine, tmp_path):
    """The transcript watcher does not call the LLM unless the judge is enabled."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-disabled-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-disabled-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"

    mock_llm = MagicMock(return_value=json.dumps({"verdicts": []}))
    with patch(_LLM_PATCH, mock_llm):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    mock_llm.assert_not_called()


def test_llm_judge_promotes_used_verdict(engine, tmp_path):
    """A confident LLM 'used' verdict creates positive affinity for an ambiguous row."""
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-used-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-used-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response) as mock_llm:
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2
    call_kwargs = mock_llm.call_args.kwargs
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert call_kwargs["response_format"]["json_schema"]["name"] == "whisper_feedback_verdicts"
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["max_tokens"] == 512

    judge_signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()
    assert judge_signal is not None
    assert judge_signal["signal_type"] == "whisper_judged_used"
    assert judge_signal["polarity"] == 1
    assert judge_signal["strength"] == 0.88

    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["signal"] == 1
    assert affinity["source"] == "auto_llm_judge"


def test_llm_judge_falls_back_to_json_object_mode(engine, tmp_path):
    """Providers that reject JSON Schema can still use the JSON-object fallback."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-schema-fallback-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-schema-fallback-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "irrelevant",
            "confidence": 0.91,
        }]
    })
    mock_llm = MagicMock(side_effect=[None, llm_response])
    with patch(_LLM_PATCH, mock_llm):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2
    assert mock_llm.call_count == 2
    first_kwargs = mock_llm.call_args_list[0].kwargs
    second_kwargs = mock_llm.call_args_list[1].kwargs
    assert first_kwargs["response_format"]["type"] == "json_schema"
    assert first_kwargs["temperature"] == 0
    assert first_kwargs["max_tokens"] == 512
    assert "response_format" not in second_kwargs
    assert second_kwargs["json_mode"] is True
    assert second_kwargs["temperature"] == 0
    assert second_kwargs["max_tokens"] == 512

    judge_signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()
    assert judge_signal is not None
    assert judge_signal["signal_type"] == "whisper_judged_irrelevant"


def test_llm_judge_promotes_irrelevant_verdict_as_negative(engine, tmp_path):
    """A confident LLM irrelevant verdict is the automatic negative-feedback path."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-negative-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-negative-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "irrelevant",
            "confidence": 0.91,
            "reason": "The memory is about graph UI rendering, not feedback schema work.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2
    judge_signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()
    assert judge_signal is not None
    assert judge_signal["signal_type"] == "whisper_judged_irrelevant"
    assert judge_signal["polarity"] == -1

    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["signal"] == -1
    assert affinity["source"] == "auto_llm_judge"


def test_llm_judge_low_confidence_records_uncertain_without_affinity(engine, tmp_path):
    """Low-confidence LLM verdicts remain observable but do not affect ranking."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-low-confidence-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-low-confidence-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "irrelevant",
            "confidence": 0.4,
            "reason": "Maybe unrelated, but confidence is low.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 2
    judge_signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()
    assert judge_signal is not None
    assert judge_signal["signal_type"] == "whisper_judged_uncertain"
    assert judge_signal["polarity"] == 0

    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is None


def test_llm_judge_skips_clear_heuristic_positive(engine, tmp_path):
    """The optional judge does not spend an LLM call on clear heuristic positives."""
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "judge-skip-positive-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-skip-positive-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    mock_llm = MagicMock(return_value=json.dumps({"verdicts": []}))
    with patch(_LLM_PATCH, mock_llm):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    mock_llm.assert_not_called()


def test_llm_judge_is_idempotent(engine, tmp_path):
    """Once a judge signal exists, the same whisper row is not judged again."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-idempotent-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Graph rendering should use level of detail for large datasets.",
        type="fact",
        title="Large graph rendering performance",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine,
        node_id=node_id,
        session_id="judge-idempotent-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    mock_llm = MagicMock(return_value=json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "irrelevant",
            "confidence": 0.91,
            "reason": "The memory is about graph UI rendering.",
        }]
    }))
    with patch(_LLM_PATCH, mock_llm):
        assert _record_whisper_usage_signals(engine, transcript) == 2
        assert _record_whisper_usage_signals(engine, transcript) == 0

    assert mock_llm.call_count == 1
    signal_count = engine.db.conn.execute(
        "SELECT COUNT(*) AS count FROM signals WHERE whisper_log_id = ?",
        (whisper_log_id,),
    ).fetchone()["count"]
    affinity_count = engine.db.conn.execute(
        "SELECT COUNT(*) AS count FROM affinity WHERE whisper_log_id = ?",
        (whisper_log_id,),
    ).fetchone()["count"]
    assert signal_count == 2
    assert affinity_count == 1


# --- Test 3: Min turns filter ---

def test_min_turns_filter(engine, tmp_path):
    """A session with too few turns is skipped."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "short.jsonl"
    _make_jsonl(jsonl, user_turns=3)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result is False
    assert str(jsonl.relative_to(watch_dir)) not in state


# --- Test 4: Unchanged session skipped ---

def test_unchanged_session_skipped(engine, tmp_path):
    """Same hash → session not re-ingested."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "session.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is False


# --- Test 5: Scan respects lookback ---

def test_scan_respects_lookback(engine, tmp_path):
    """Old files are skipped during catch-up scan, recent ones ingested."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)

    recent = project_dir / "recent.jsonl"
    _make_jsonl(recent, user_turns=6)

    old = project_dir / "old.jsonl"
    _make_jsonl(old, user_turns=6)
    # Set mtime to 200 hours ago (beyond 72h lookback)
    import os
    old_time = time.time() - (200 * 3600)
    os.utime(old, (old_time, old_time))

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        count = _scan_sessions(engine, watch_dir, min_turns=5, lookback_hours=72)

    assert count == 1  # only recent
    state = _load_state(watch_dir)
    assert str(recent.relative_to(watch_dir)) in state
    assert str(old.relative_to(watch_dir)) not in state


# --- Test 6: Debounce coalesces writes ---

def test_debounce_coalesces_writes(engine, tmp_path):
    """5 rapid events → 1 ingestion call."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)

    handler = SessionHandler(engine, watch_dir, debounce_seconds=0.3, min_turns=5)
    jsonl = project_dir / "active.jsonl"

    call_count = 0
    original_ingest = _ingest_session

    def counting_ingest(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_ingest(*args, **kwargs)

    with patch("ormah.background.session_watcher._ingest_session", side_effect=counting_ingest):
        for i in range(5):
            _make_jsonl(jsonl, user_turns=6 + i)
            from watchdog.events import FileModifiedEvent
            handler.on_modified(FileModifiedEvent(str(jsonl)))
            time.sleep(0.05)

        # Wait for debounce
        time.sleep(0.5)

    assert call_count == 1


# --- Test 7: Lifecycle start/stop ---

def test_lifecycle_start_stop(engine, tmp_path):
    """Observer starts and stops cleanly."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()

    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_debounce_seconds = 10.0

    observers = start_session_watcher(engine)
    try:
        assert len(observers) == 1
        assert observers[0].is_alive()
    finally:
        stop_session_watcher(observers)

    # Give observer thread a moment to stop
    time.sleep(0.1)
    assert not observers[0].is_alive()


def test_lifecycle_includes_codex_sessions_when_using_default_agent_dir(
    engine,
    tmp_path,
    monkeypatch,
):
    """Default watcher setup starts observers for existing Claude and Codex session dirs."""
    home = tmp_path / "home"
    claude_dir = home / ".claude" / "projects"
    codex_dir = home / ".codex" / "sessions"
    claude_dir.mkdir(parents=True)
    codex_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = Path("~/.claude/projects")
    engine.settings.session_watcher_debounce_seconds = 10.0

    observers = start_session_watcher(engine)
    try:
        assert len(observers) == 2
        assert all(observer.is_alive() for observer in observers)
    finally:
        stop_session_watcher(observers)


# --- Test 8: Disabled returns empty ---

def test_disabled_returns_empty(engine, tmp_path):
    """session_watcher_enabled=False → empty list."""
    engine.settings.session_watcher_enabled = False
    observers = start_session_watcher(engine)
    assert observers == []


# --- Test 9: State persistence ---

def test_state_persistence(tmp_path):
    """State file survives save/load roundtrip."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()

    state = {
        "proj/abc.jsonl": {
            "hash": "deadbeef",
            "last_ingested": "2024-01-01T00:00:00",
            "session_id": "abc",
            "space": "proj",
            "user_turns": 10,
            "node_ids": ["id-1", "id-2"],
        }
    }
    _save_state(watch_dir, state)

    loaded = _load_state(watch_dir)
    assert loaded == state
    assert loaded["proj/abc.jsonl"]["hash"] == "deadbeef"
    assert loaded["proj/abc.jsonl"]["node_ids"] == ["id-1", "id-2"]


# --- Test 10: Nonexistent watch dir ---

def test_nonexistent_watch_dir(engine, tmp_path):
    """Nonexistent watch dir returns empty, no crash."""
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = tmp_path / "does-not-exist"

    observers = start_session_watcher(engine)
    assert observers == []


# --- Test 11: Incremental — only appended turns are re-ingested ---

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

        _make_jsonl(jsonl, user_turns=12)  # identical first 6 turns + 6 appended
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True

    assert "User message 0 " not in captured[1]
    assert "User message 6 " in captured[1]
    assert state[str(jsonl.relative_to(watch_dir))]["end_offset"] > first_offset


# --- Test 12: Incremental — too-few new turns defers ---

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

    assert calls == 1
    assert state[str(jsonl.relative_to(watch_dir))] == saved


# --- Test 13: Shrink resets the cursor ---

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

    assert "User message 0 " in captured[1]


# --- New tests: safe-payload ingest, idle flush + retry, in-flight guard ---


def _append_pair(path, i):
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"User message {i} with enough text to parse"},
        }) + "\n")
        f.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": "end_turn", "content": [
                {"type": "text", "text": f"Assistant response {i} with some detail"},
            ]},
        }) + "\n")


def _append_user(path, i):
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"User message {i} with enough text to parse"},
        }) + "\n")


def _append_assistant(path, i, stop_reason="end_turn"):
    """Append one assistant text record. stop_reason=None / "tool_use" marks it as a
    non-terminal record of a still-open response (more records to come)."""
    with path.open("a") as f:
        f.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": stop_reason, "content": [
                {"type": "text", "text": f"Assistant response {i} with some detail"},
            ]},
        }) + "\n")


def _append_codex_turn(path, i, *, records=1, complete=True):
    """Append a Codex turn: a user message, `records` assistant text records (multi-record
    when >1), and a task_complete event unless `complete=False` (still in flight)."""
    with path.open("a") as f:
        f.write(json.dumps({"type": "response_item", "payload": {"type": "message",
            "role": "user", "content": [
                {"type": "input_text", "text": f"User message {i} with enough text to parse"}]}}) + "\n")
        for r in range(records):
            f.write(json.dumps({"type": "response_item", "payload": {"type": "message",
                "role": "assistant", "content": [
                    {"type": "output_text", "text": f"Assistant response {i} part {r} detail"}]}}) + "\n")
        if complete:
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")


def test_inflight_multirecord_response_not_split(engine, tmp_path):
    """An in-flight response (non-terminal stop_reason) is held back until its terminal
    record arrives, so a multi-record assistant response is never split from its prompt.
    Claude Code detects completion via stop_reason, not the next user turn.
    """
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _make_jsonl(jsonl, user_turns=6)  # 6 complete (end_turn) pairs
    state = {}
    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        # Every pair is terminal -> all committed; the cursor sits after the last one.
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
        cursor1 = state[rel]["end_offset"]

        # New turn: prompt + a FIRST assistant record still in flight (tool_use). The
        # response is not complete, so nothing new commits and the cursor must not move
        # into the middle of the response.
        _append_user(jsonl, 6)
        _append_assistant(jsonl, 6, stop_reason="tool_use")
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is False
        assert state[rel]["end_offset"] == cursor1

        # The response completes with a terminal record: prompt + BOTH assistant records
        # commit together — never split.
        _append_assistant(jsonl, 6, stop_reason="end_turn")
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True

    committed = captured[-1]
    assert "User message 6 " in committed
    assert committed.count("Assistant response 6 ") == 2  # both records, not split
    assert state[rel]["end_offset"] > cursor1


def test_codex_multirecord_turn_committed_whole_via_task_complete(engine, tmp_path):
    """A multi-record Codex turn commits as one block at its task_complete; an in-flight
    turn (no task_complete yet) is held back, never split."""
    watch_dir = tmp_path / ".codex" / "sessions"
    transcript_dir = watch_dir / "2026" / "06" / "25"
    transcript_dir.mkdir(parents=True)
    jsonl = transcript_dir / "rollout-2026-06-25T12-00-00-sess-multi.jsonl"

    _append_codex_turn(jsonl, 0, records=3, complete=True)
    _append_codex_turn(jsonl, 1, records=2, complete=True)
    # In-flight final turn: two assistant records, no task_complete yet.
    _append_codex_turn(jsonl, 2, records=2, complete=False)

    state = {}
    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        # Fresh/active: the two task_complete turns commit whole; the in-flight one waits.
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True

    committed = captured[-1]
    assert committed.count("Assistant response 0 part ") == 3  # turn 0 not split
    assert committed.count("Assistant response 1 part ") == 2  # turn 1 not split
    assert "User message 2 " not in committed                  # in-flight turn held back


def test_legacy_mid_response_cursor_recovered(engine, tmp_path):
    """A watcher cursor an older version left BETWEEN two assistant records of one response
    triggers a full re-parse so the tail is recovered with its prompt — not orphaned."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    records = [
        {"type": "user", "message": {"role": "user",
            "content": "Prompt with the memory detail and enough text to parse"}},
        {"type": "assistant", "message": {"role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "text", "text": "First part of the response"}]}},
        {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Second part with the actual answer"}]}},
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    # A legacy state cursor saved mid-response (after the first assistant record), with the
    # CORRECT file hash — the file is unchanged. Recovery must still fire because the stored
    # offset is behind EOF (the hash short-circuit only skips a fully-consumed file).
    from ormah.background.session_watcher import _file_hash
    raw = jsonl.read_bytes().splitlines(keepends=True)
    mid = len(raw[0]) + len(raw[1])
    state = {rel: {"end_offset": mid, "hash": _file_hash(jsonl), "node_ids": [], "user_turns": 1}}

    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True

    committed = captured[-1]
    assert "Prompt with the memory detail" in committed   # prompt recovered
    assert "First part of the response" in committed       # both response records,
    assert "Second part with the actual answer" in committed  # paired with the prompt
    assert state[rel]["end_offset"] > mid

    # Recovery is one-time: the cursor is now a safe boundary (file fully consumed), so a
    # second pass on the unchanged file skips without re-recovering.
    assert state[rel]["end_offset"] == jsonl.stat().st_size
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is False


def test_codex_inflight_turn_not_split_on_idle(engine, tmp_path):
    """An in-flight Codex turn (no task_complete yet) is held back even when the file
    looks idle — there is no idle flush that could split it."""
    watch_dir = tmp_path / ".codex" / "sessions"
    transcript_dir = watch_dir / "2026" / "06" / "25"
    transcript_dir.mkdir(parents=True)
    jsonl = transcript_dir / "rollout-2026-06-25T12-30-00-sess-sticky.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _append_codex_turn(jsonl, 0, records=2, complete=True)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) is True
    cursor = state[rel]["end_offset"]

    # In-flight multi-record turn, file now idle. The turn has no closure signal, so it is
    # held back — never flushed mid-response.
    _append_codex_turn(jsonl, 1, records=2, complete=False)
    now = time.time()
    os.utime(jsonl, (now, now - 120))
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1,
                               idle_threshold=30) is False
    assert state[rel]["end_offset"] == cursor


def test_idle_tail_with_dangling_user_no_duplicate(engine, tmp_path):
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"

    _make_jsonl(jsonl, user_turns=6)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)
    _append_user(jsonl, 8)
    now = time.time()
    os.utime(jsonl, (now, now - 120))

    captured = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5, idle_threshold=30
        ) is True
        assert "User message 8 " not in captured[-1]

        _append_assistant(jsonl, 8)
        now2 = time.time()
        os.utime(jsonl, (now2, now2 - 120))
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=1, idle_threshold=30
        ) is True

    joined = "\n".join(captured)
    assert joined.count("User message 8 ") == 1


def test_session_tail_idle_ingested(engine, tmp_path):
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"

    _make_jsonl(jsonl, user_turns=6)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)
    now = time.time()
    os.utime(jsonl, (now, now - 120))

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5, idle_threshold=30
        ) is True
    assert calls == 1


def test_retry_fires_and_ingests_after_idle(engine, tmp_path):
    from ormah.background import session_watcher as sw

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"

    _make_jsonl(jsonl, user_turns=6)

    captured_timers = []

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            self.delay = delay
            self.fn = fn
            self.args = args
            self.daemon = False
        def start(self):
            captured_timers.append(self)
        def cancel(self):
            pass

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    # Seed state outside counting context so the initial 6-pair ingest is not counted.
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "Timer", FakeTimer):
        handler = sw.SessionHandler(
            engine, watch_dir, debounce_seconds=60, min_turns=5, idle_threshold=30,
        )
        sw._ingest_session(engine, jsonl, handler._state, watch_dir, min_turns=5)

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting), \
         patch.object(sw, "Timer", FakeTimer):
        handler._do_ingest(jsonl)
        assert calls == 0
        assert len(captured_timers) == 1
        assert captured_timers[0].delay == 30

        now = time.time()
        os.utime(jsonl, (now, now - 120))
        timer = captured_timers[0]
        timer.fn(*timer.args)

    assert calls == 1


def test_concurrent_ingest_skipped(engine, tmp_path):
    import threading
    from ormah.background import session_watcher as sw

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_ingest(content, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return []

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=blocking_ingest):
        handler = sw.SessionHandler(
            engine, watch_dir, debounce_seconds=60, min_turns=5, idle_threshold=30,
        )
        t1 = threading.Thread(target=handler._do_ingest, args=(jsonl,))
        t1.start()
        assert started.wait(timeout=5)
        handler._do_ingest(jsonl)
        release.set()
        t1.join(timeout=5)

    assert calls == 1


# --- Test 19: in-flight skip reschedules the dropped event (no lost tail) ---

def test_inflight_skip_reschedules(engine, tmp_path):
    """A modify event skipped because an ingest is in flight must be rescheduled, not dropped."""
    import threading

    from ormah.background import session_watcher as sw

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)

    scheduled = []

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            self.delay = delay
            self.fn = fn
            self.args = args
            self.daemon = False
        def start(self):
            scheduled.append(self)
        def cancel(self):
            pass

    started = threading.Event()
    release = threading.Event()

    def blocking_ingest(content, **kwargs):
        started.set()
        release.wait(timeout=5)
        return []

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=blocking_ingest), \
         patch.object(sw, "Timer", FakeTimer):
        handler = sw.SessionHandler(
            engine, watch_dir, debounce_seconds=60, min_turns=5, idle_threshold=30,
        )
        t1 = threading.Thread(target=handler._do_ingest, args=(jsonl,))
        t1.start()
        assert started.wait(timeout=5)   # ingest A is in flight
        handler._do_ingest(jsonl)        # skipped — must mark pending
        assert scheduled == []           # nothing rescheduled while A still runs
        release.set()
        t1.join(timeout=5)

    # After A finishes, the skipped event was rescheduled as a fresh debounce
    assert len(scheduled) == 1
    assert scheduled[0].delay == 60


# --- Test 20: shrink resets node_ids provenance, not just turn count ---

def test_shrink_resets_node_ids(engine, tmp_path):
    """A file that shrinks below the stored offset must not carry stale node_ids forward."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _make_jsonl(jsonl, user_turns=10)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True
    first_nodes = list(state[rel]["node_ids"])
    assert first_nodes  # first ingest produced at least one node

    _make_jsonl(jsonl, user_turns=5)  # smaller file → size < stored end_offset → full re-ingest
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) is True

    # Full re-ingest (prev_offset reset to 0): stale node_ids must not be concatenated,
    # so the stored provenance carries no duplicates.
    nodes = state[rel]["node_ids"]
    assert len(nodes) == len(set(nodes))


def test_catchup_concurrency_must_be_positive():
    from ormah.config import Settings
    assert Settings().session_watcher_catchup_concurrency == 1
    with pytest.raises(ValueError):
        Settings(session_watcher_catchup_concurrency=0)


def test_ingest_session_accepts_state_lock(engine, tmp_path):
    import threading
    from ormah.background.session_watcher import _ingest_session
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        ok = _ingest_session(engine, f, state, wd, 5, state_lock=threading.Lock())
    assert ok is True
    assert "p/s.jsonl" in state


def test_semaphore_bounds_catchup_and_live(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    a = wd / "p" / "a.jsonl"; b = wd / "p" / "b.jsonl"
    for f in (a, b):
        _make_jsonl(f); _mark_idle(f)
    cur = {"n": 0, "max": 0}; lk = threading.Lock(); real = sw._ingest_session
    def instrumented(*args, **kw):
        with lk:
            cur["n"] += 1; cur["max"] = max(cur["max"], cur["n"])
        time.sleep(0.05)
        with lk:
            cur["n"] -= 1
        return real(*args, **kw)
    sem = threading.Semaphore(1)
    handler = sw.SessionHandler(engine, wd, 0.1, 5, extraction_semaphore=sem)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", instrumented):
        t1 = threading.Thread(target=handler._do_ingest, args=(a,))
        t2 = threading.Thread(target=handler.catchup_ingest, args=(b,))
        t1.start(); t2.start(); t1.join(); t2.join()
    assert cur["max"] == 1


def test_ingest_after_stop_is_rejected(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    stop = threading.Event()
    handler = sw.SessionHandler(engine, wd, 0.1, 5, stop_event=stop)
    stop.set()                                   # shutdown already in progress
    calls = {"n": 0}; real = sw._ingest_session
    def counting(*a, **k):
        calls["n"] += 1; return real(*a, **k)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", counting):
        result = handler._do_ingest(f)           # a timer that fired during shutdown
        status = handler.catchup_ingest(f)
    assert result is False
    assert status == "stopped"
    assert calls["n"] == 0                        # neither path touched _ingest_session / the DB
    assert handler.in_flight_count() == 0


def test_catchup_ingests_each_tail_exactly_once(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    stop = threading.Event()
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        sw._run_catchup([(wd, handler)], stop, 72)
        first = _load_state(wd)["p/s.jsonl"]["end_offset"]
        sw._run_catchup([(wd, handler)], stop, 72)   # unchanged -> no re-ingest
        second = _load_state(wd)["p/s.jsonl"]["end_offset"]
    assert first == second


def test_catchup_ingest_reports_in_flight(engine, tmp_path):
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    handler = sw.SessionHandler(engine, wd, 0.1, 5)
    handler._ingesting.add(str(f))               # pretend a live ingest owns it
    assert handler.catchup_ingest(f) == "in_flight"


# --- Task 5: off-bind-path catch-up + drain-before-close ---

def test_start_returns_without_blocking_on_catchup(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_debounce_seconds = 10.0
    started = threading.Event(); release = threading.Event(); real = sw._ingest_session
    def blocking(*a, **k):
        started.set(); release.wait(5); return real(*a, **k)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        t0 = time.monotonic()
        handle = sw.start_session_watcher(engine)
        elapsed = time.monotonic() - t0
        try:
            assert elapsed < 1.0
            assert started.wait(2)
        finally:
            release.set(); sw.stop_session_watcher(handle)


def test_live_append_during_catchup_ingests_tail_once(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f, user_turns=6); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_debounce_seconds = 10.0
    real = sw._ingest_session
    in_ingest = threading.Event(); release = threading.Event()
    true_returns = {"n": 0}; lk = threading.Lock()
    def gated(*a, **k):
        in_ingest.set(); release.wait(5)
        r = real(*a, **k)
        if r:
            with lk:
                true_returns["n"] += 1
        return r
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", gated):
        handle = sw.start_session_watcher(engine)
        assert in_ingest.wait(2)
        for h in handle.handlers:
            h._do_ingest(f)                      # live ingest of the SAME file mid-catch-up
        release.set()
        time.sleep(0.5)
        sw.stop_session_watcher(handle)
    assert true_returns["n"] == 1


def test_stop_drains_live_inflight_ingest(engine, tmp_path):
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    f = wd / "p" / "s.jsonl"; _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_lookback_hours = -1   # catch-up skips never-seen -> only live
    started = threading.Event(); release = threading.Event()
    def blocking(*a, **k):
        started.set(); release.wait(5); return False
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        handle = sw.start_session_watcher(engine)
        live = threading.Thread(target=handle.handlers[0]._do_ingest, args=(f,))
        live.start()
        assert started.wait(2)
        done = threading.Event()
        stopper = threading.Thread(target=lambda: (sw.stop_session_watcher(handle), done.set()))
        stopper.start()
        assert not done.wait(0.5)                # stop BLOCKS on the live in-flight ingest
        release.set()
        assert done.wait(3)                       # stop returns after it finishes
        live.join()
    assert all(h.in_flight_count() == 0 for h in handle.handlers)


def test_stop_drains_ingest_blocked_on_semaphore(engine, tmp_path):
    """An ingest that claimed _ingesting but is waiting on the K=1 semaphore when stop fires is
    counted in_flight and drained — not abandoned (council round 4 #1/#5)."""
    import threading
    import ormah.background.session_watcher as sw
    wd = tmp_path / "projects"; (wd / "p").mkdir(parents=True)
    a = wd / "p" / "a.jsonl"; b = wd / "p" / "b.jsonl"
    for f in (a, b):
        _make_jsonl(f); _mark_idle(f)
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = wd
    engine.settings.session_watcher_lookback_hours = -1       # only the two live ingests below
    started = threading.Event(); release = threading.Event(); count = {"done": 0}; lk = threading.Lock()
    def blocking(*ar, **kw):
        started.set(); release.wait(5)
        with lk:
            count["done"] += 1
        return False
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(sw, "_ingest_session", blocking):
        handle = sw.start_session_watcher(engine)
        h = handle.handlers[0]
        ta = threading.Thread(target=h._do_ingest, args=(a,))  # acquires the K=1 semaphore, blocks
        ta.start(); assert started.wait(2)
        tb = threading.Thread(target=h._do_ingest, args=(b,))  # claims _ingesting[b], waits on semaphore
        tb.start(); time.sleep(0.2)
        assert h.in_flight_count() == 2                         # both claimed before stop
        done = threading.Event()
        stopper = threading.Thread(target=lambda: (sw.stop_session_watcher(handle), done.set()))
        stopper.start()
        assert not done.wait(0.5)                               # stop waits for BOTH to drain
        release.set()
        assert done.wait(5)
        ta.join(); tb.join()
    assert count["done"] == 2                                   # both completed, none abandoned
    assert h.in_flight_count() == 0

"""Tests for the transcript watcher — auto-ingestion of agent transcripts."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ormah.background.session_watcher import (
    MAX_EXTRACT_FAILURES,
    IngestResult,
    SessionHandler,
    _ingest_session,
    _load_state,
    _record_whisper_usage_signals,
    _save_state,
    _space_from_encoded_dir,
    _expand_watch_dir,
    run_session_reconcile,
    start_session_watcher,
    stop_session_watcher,
)
from ormah.engine.memory_engine import MemoryEngine
from ormah.models.node import CreateNodeRequest
from ormah.transcript.parser import parse_transcript

_LLM_PATCH = "ormah.background.llm_client.ingest_llm_generate"
# A slice-specific extraction failure: the LLM responds but the content is unparseable, so
# _extract_memories_llm raises during json.loads and returns its generic error string. This is the
# DETERMINISTIC failure that counts toward the per-slice cap (unlike a provider-wide call failure /
# None, which is transient and never skips the slice — council-pr H1).
_UNPARSEABLE = "this is not json at all"
# The whisper-usage LLM judge uses the global llm_generate (maintenance path), NOT the
# extraction-only ingest_llm_generate. Judge tests patch this; ingest tests patch _LLM_PATCH.
_JUDGE_PATCH = "ormah.background.llm_client.llm_generate"

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

    Recedes past the default session_watcher_idle_threshold (600s, see _ingest_session)
    so callers relying on either that default or a smaller explicit idle_threshold see the
    file as idle.
    """
    now = time.time()
    os.utime(path, (now, now - 700))


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


# --- ADR-0004 always-on-worker test helpers -----------------------------------

def _wait_until(pred, timeout=6.0, interval=0.02):
    """Poll ``pred`` until true or ``timeout`` elapses; return the final truthiness."""
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


def _spool_idle(spool):
    """True once the spool holds no pending work and nothing is mid-flight in running/."""
    running = spool.root / "running"
    running_empty = not any(p.name.endswith(".json") for p in running.iterdir())
    return spool.pending_count() == 0 and running_empty


def _drain_all(handler, timeout=20.0):
    """Drain the spool synchronously through the ONE ingestion path (deterministic, no
    thread). Stops when no due job remains (a backed-off job is left queued)."""
    end = time.time() + timeout
    while time.time() < end:
        job = handler.spool.claim_next()
        if job is None:
            return
        handler._run_job(job)


def _handler_with_spool(engine, watch_dir, spool_dir, **overrides):
    from ormah.background.ingest_spool import IngestSpool

    spool = IngestSpool(spool_dir)
    kw = dict(debounce_seconds=60.0, min_turns=5, idle_threshold=30.0, lookback_hours=9999)
    kw.update(overrides)
    return SessionHandler(
        engine, watch_dir, kw["debounce_seconds"], kw["min_turns"],
        kw["idle_threshold"], kw["lookback_hours"], spool=spool,
    )


@pytest.fixture(autouse=True)
def _no_default_acceptance_roots(monkeypatch):
    """D8: the real ~/.claude/projects and ~/.codex/sessions exist on the dev machine, so
    without this the suite would build watches over real home. Default acceptance roots come
    only from tests that set them explicitly."""
    monkeypatch.setattr(
        "ormah.background.session_watcher._default_acceptance_roots", lambda: []
    )



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
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result == IngestResult.OK
    rel = str(jsonl.relative_to(watch_dir))
    assert rel in state
    entry = state[rel]
    assert entry["session_id"] == "abc123"
    assert entry["source"] == "claude_code"
    assert entry["space"] == "myproject"
    assert entry["user_turns"] == 6
    assert len(entry["node_ids"]) == 1


def test_ingest_none_is_transient_and_does_not_advance(engine, tmp_path):
    """LLM unavailable (adapter returns None) -> TRANSIENT, cursor must not advance."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    state = {}
    # "LLM unavailable" == no provider configured: the failure stays TRANSIENT and is never
    # counted toward the per-slice cap, so no state entry is written. Patch the provider check
    # explicitly so the result does not depend on a cached ingest adapter left by an earlier test.
    with patch(_LLM_PATCH, return_value=None), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=False):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result == IngestResult.TRANSIENT
    rel = str(jsonl.relative_to(watch_dir))
    assert rel not in state  # no provider -> failure never counted, cursor never written


def test_toxic_slice_skipped_after_max_extract_failures(engine, tmp_path):
    """A slice that fails extraction MAX_EXTRACT_FAILURES times (provider present) must advance
    the cursor past it — not re-drive ingestion forever (the 1393x loop)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    # Provider IS configured; the slice deterministically fails extraction (unparseable output).
    with patch(_LLM_PATCH, return_value=_UNPARSEABLE), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for i in range(1, MAX_EXTRACT_FAILURES):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
            assert state[rel]["extract_fail_count"] == i
            assert state[rel]["end_offset"] == 0  # cursor NOT advanced yet
        # Capped: skip the toxic slice forward. The cursor advanced -> progress, so this is OK,
        # not NO_PROGRESS (which would bump the reconcile-park counter for a slice that just
        # progressed).
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

    assert state[rel]["end_offset"] > 0            # cursor advanced past the toxic slice
    assert "extract_fail_count" not in state[rel]  # counter cleared after skip
    # Durable quarantine trail: the skipped range is recorded, not just logged, so it can be
    # replayed after the provider issue is fixed.
    skipped = state[rel]["skipped_slices"]
    assert len(skipped) == 1
    assert skipped[0]["start"] == 0
    assert skipped[0]["end"] == state[rel]["end_offset"]
    assert skipped[0]["reason"] == "extract_failed_x3"


def test_capped_skip_schedules_drain_continuation(engine, tmp_path):
    """When the toxic slice is a CAPPED batch (more closed content follows), the skip must call
    on_defer_active so the rest of the transcript drains on the next tick, not only via reconcile.
    (Council adjustment #3 for Task 04 — mirrors the success-path capped continuation.)"""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=12)  # large enough that a small flush_bytes caps the first batch
    _mark_idle(jsonl)
    state = {}
    defer_calls: list[int] = []

    result = None
    with patch(_LLM_PATCH, return_value=_UNPARSEABLE), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES):
            result = _ingest_session(
                engine, jsonl, state, watch_dir, min_turns=1,
                flush_bytes=300,  # small -> the first closed batch is capped (content past it)
                on_defer_active=lambda: defer_calls.append(1),
            )

    assert result == IngestResult.OK          # capped slice skipped after the cap
    assert defer_calls, "on_defer_active must fire on a capped skip to drain the remainder"


def test_no_provider_failure_never_burns_the_slice(engine, tmp_path):
    """Without a provider, a failure must stay TRANSIENT and never advance the cursor or count —
    the data must survive until a provider returns."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    with patch(_LLM_PATCH, return_value=None), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=False):
        for _ in range(MAX_EXTRACT_FAILURES + 2):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

    # Never counted, never advanced: either no entry, or an entry with cursor still at 0 and no counter.
    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0
    assert "extract_fail_count" not in entry


def test_extract_fail_count_persists_across_restart(engine, tmp_path):
    """The per-slice failure counter must survive a process restart (persisted state), not just
    live in-memory — otherwise a restarted watcher resets the cap and the loop never breaks."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    with patch(_LLM_PATCH, return_value=_UNPARSEABLE), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for i in range(1, MAX_EXTRACT_FAILURES):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

        assert state[rel]["extract_fail_count"] == MAX_EXTRACT_FAILURES - 1

        # Simulate a restart: reload state from disk into a fresh dict.
        reloaded_state = _load_state(watch_dir)
        assert reloaded_state[rel]["extract_fail_count"] == MAX_EXTRACT_FAILURES - 1

        # The (MAX_EXTRACT_FAILURES)th failure, on the reloaded state, must still trip the cap.
        assert _ingest_session(engine, jsonl, reloaded_state, watch_dir, min_turns=5) == IngestResult.OK

    assert reloaded_state[rel]["end_offset"] > 0
    assert "extract_fail_count" not in reloaded_state[rel]


def test_success_after_cap_preserves_skipped_slices(engine, tmp_path):
    """A capped slice records a durable skipped_slices entry; a LATER successful slice must not
    wipe that quarantine trail. The success-path state write was building the entry from scratch
    (dropping skipped_slices) while the cap path copied existing state (council-pr C1)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=12)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    # Phase 1: the first (capped) batch deterministically fails extraction MAX_EXTRACT_FAILURES
    # times (slice-specific, unparseable) -> quarantined + skipped.
    with patch(_LLM_PATCH, return_value=_UNPARSEABLE), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES):
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=1, flush_bytes=300)
    assert state[rel]["skipped_slices"], "precondition: first slice quarantined"
    quarantined = list(state[rel]["skipped_slices"])

    # Phase 2: the NEXT batch extracts successfully and writes fresh success state.
    ok = json.dumps({"memories": [{"content": "a genuine memory to store", "type": "fact",
                                   "title": "t"}]})
    with patch(_LLM_PATCH, return_value=ok), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=1, flush_bytes=300)

    assert result == IngestResult.OK
    # The durable quarantine trail must survive the successful write.
    assert state[rel]["skipped_slices"] == quarantined


def test_ingest_exception_counts_toward_cap(engine, tmp_path):
    """A DETERMINISTIC exception in ingest_conversation must count toward the per-slice cap and
    eventually skip the slice — otherwise it pins the cursor forever, the same loop the string
    path already guards against (council-pr I1)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    with patch.object(engine, "ingest_conversation", side_effect=RuntimeError("boom")), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for i in range(1, MAX_EXTRACT_FAILURES):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
            assert state[rel]["extract_fail_count"] == i
            assert state[rel]["end_offset"] == 0  # cursor pinned until capped
        # The capped attempt skips the slice forward instead of looping forever.
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

    assert state[rel]["end_offset"] > 0
    skipped = state[rel]["skipped_slices"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "ingest_exception_x3"  # distinguishable from extract failures (M1)


def test_transient_storage_exception_never_skips_slice(engine, tmp_path):
    """A retryable storage exception (SQLite lock under WAL contention) must stay TRANSIENT forever
    and never advance the cursor or count toward the cap — else a lock that clears later loses the
    slice permanently (council-pr H2). Only DETERMINISTIC exceptions may be capped."""
    import sqlite3

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    with patch.object(engine, "ingest_conversation",
                      side_effect=sqlite3.OperationalError("database is locked")), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES + 2):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0        # cursor never advanced
    assert "extract_fail_count" not in entry      # never counted toward the cap
    assert "skipped_slices" not in entry          # never quarantined -> no data loss


def test_provider_wide_call_failure_never_skips_slice(engine, tmp_path):
    """A provider-wide LLM call failure (binary/auth/network/timeout -> raw is None -> CALL_FAILED)
    must stay TRANSIENT and never count toward the cap: during an outage every slice would otherwise
    be skipped after the cap = mass silent loss (council-pr H1). Only slice-specific parse failures
    are capped."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    # Both provider checks TRUE + call returns None -> _extract_memories_llm returns CALL_FAILED
    # (a provider-wide failure, not a slice defect).
    with patch(_LLM_PATCH, return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES + 3):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0    # cursor never advanced during the outage
    assert "extract_fail_count" not in entry  # provider-wide failure never counts toward the cap
    assert "skipped_slices" not in entry       # nothing skipped -> no data loss


def test_repeated_cancellations_never_skip_a_slice(engine, tmp_path):
    """ADR-0004 slice 2, Step 3b: a shutdown-cancelled extraction (LlmCancelledError) must map
    to EXTRACT_ERR_CALL_FAILED -> TRANSIENT and NEVER count toward the per-slice cap, even
    across many restarts hitting the same offset -- otherwise repeated restarts during the same
    slice's extraction would eventually SKIP a healthy slice (data loss)."""
    from ormah.background.llm_errors import LlmCancelledError

    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    state = {}

    def _raise(*a, **k):
        raise LlmCancelledError("shutdown")

    with patch(_LLM_PATCH, side_effect=_raise), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES + 3):
            assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

    entry = state.get(rel, {})
    assert entry.get("end_offset", 0) == 0    # cursor never advanced across restarts
    assert "extract_fail_count" not in entry  # a cancel never counts toward the cap
    assert "skipped_slices" not in entry       # nothing skipped -> no data loss


def test_ingest_valid_empty_memories_advances(engine, tmp_path):
    """A valid {"memories": []} extraction is a SUCCESS: the slice is consumed and the
    cursor advances, so session_watcher never re-processes a no-memory turn forever."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    state = {}
    with patch(_LLM_PATCH, return_value='{"memories": []}'):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result == IngestResult.OK
    rel = str(jsonl.relative_to(watch_dir))
    entry = state[rel]
    assert entry["end_offset"] > 0  # cursor advanced past the consumed slice
    assert entry["node_ids"] == []


def test_ingest_null_optional_fields_does_not_wedge_cursor(engine, tmp_path):
    """Cursor-wedge regression: the fallback extraction path is not --json-schema-
    constrained, so tags/about_self/confidence can arrive as null. That must not raise
    inside ingest_conversation -> propagate as an error string -> TRANSIENT forever."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    null_fields_response = json.dumps({"memories": [
        {"content": "x", "type": "fact", "title": "t",
         "tags": None, "about_self": None, "confidence": None},
    ]})

    state = {}
    with patch(_LLM_PATCH, return_value=null_fields_response):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result == IngestResult.OK
    rel = str(jsonl.relative_to(watch_dir))
    entry = state[rel]
    assert entry["end_offset"] > 0  # cursor advanced, not wedged
    assert len(entry["node_ids"]) == 1


def test_subagent_transcript_is_not_ingested(engine, tmp_path):
    """Subagent transcripts (<uuid>/subagents/agent-*.jsonl) are internal agent scratch.

    They must never be ingested as memories, even with turns above min_turns — otherwise
    every Task-tool spawn balloons the store with low-value granular memories.
    """
    watch_dir = tmp_path / "projects"
    sub_dir = watch_dir / "-Users-alice-Code-myproject" / "abc123" / "subagents"
    sub_dir.mkdir(parents=True)
    jsonl = sub_dir / "agent-deadbeef.jsonl"
    _make_jsonl(jsonl, user_turns=6)  # well above min_turns

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)

    assert result == IngestResult.NO_PROGRESS
    assert state == {}


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
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK

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
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK

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
    with patch(_JUDGE_PATCH, mock_llm):
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
    with patch(_JUDGE_PATCH, return_value=llm_response) as mock_llm:
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


def test_llm_judge_no_schemaless_fallback_on_schema_failure(engine, tmp_path):
    """When the schema call fails, the judge gives up rather than retrying without a schema."""
    prompt = "How should we solve feedback collection?"
    response = "We should first fix the database uniqueness key."
    transcript_path = tmp_path / "judge-schema-failure-session.jsonl"
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
        session_id="judge-schema-failure-session",
        prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    mock_llm = MagicMock(return_value=None)
    with patch(_JUDGE_PATCH, mock_llm):
        recorded = _record_whisper_usage_signals(engine, transcript)

    assert recorded == 1
    assert mock_llm.call_count == 1

    judge_signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ? "
        "AND source = 'transcript_watcher_llm_judge'",
        (whisper_log_id,),
    ).fetchone()
    assert judge_signal is None


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
    with patch(_JUDGE_PATCH, return_value=llm_response):
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
    with patch(_JUDGE_PATCH, return_value=llm_response):
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
    with patch(_JUDGE_PATCH, mock_llm):
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
    with patch(_JUDGE_PATCH, mock_llm):
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

    # A short ACTIVE window below min_turns defers (noise cut) rather than extracting —
    # retry until it crosses min_turns, crosses flush_bytes, or the session idles.
    assert result == IngestResult.TRANSIENT
    assert str(jsonl.relative_to(watch_dir)) not in state


def test_min_turns_skips_short_active_window(engine, tmp_path):
    """A window below min_turns that is NOT idle must defer, not extract (noise cut)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)  # below min_turns=5
    # NOT marked idle -> active short window

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
    assert result != IngestResult.OK
    assert state == {}


def test_min_turns_still_flushes_short_idle_session(engine, tmp_path):
    """A short but FINISHED (idle) session must still be captured — not stranded."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)
    _mark_idle(jsonl)  # finished

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
    assert result == IngestResult.OK


# --- Test 4: Unchanged session skipped ---

def test_unchanged_session_skipped(engine, tmp_path):
    """Same hash → session not re-ingested."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "session.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.NO_PROGRESS



# --- Test 6: Debounce coalesces writes ---

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
        assert observers[0].observer.is_alive()
    finally:
        stop_session_watcher(observers)

    # Give observer thread a moment to stop
    time.sleep(0.1)
    assert not observers[0].observer.is_alive()


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
        assert all(w.observer.is_alive() for w in observers)
    finally:
        stop_session_watcher(observers)


# --- Test 8: Disabled returns empty ---

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

# --- Test 11: Incremental — only appended turns are re-ingested ---

def test_incremental_only_new_turns(engine, tmp_path):
    """After the first ingest, a later change feeds ONLY the appended turns to ingest."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
        first_offset = state[str(jsonl.relative_to(watch_dir))]["end_offset"]
        assert first_offset > 0

        _make_jsonl(jsonl, user_turns=12)  # identical first 6 turns + 6 appended
        _mark_idle(jsonl)  # appended session, below flush_bytes → idle flush
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

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
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

    calls = 0
    real_ingest = engine.ingest_conversation

    def counting(content, **kwargs):
        nonlocal calls
        calls += 1
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=counting):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
        saved = dict(state[str(jsonl.relative_to(watch_dir))])

        _make_jsonl(jsonl, user_turns=8)  # only 2 new turns < min_turns, file still active → TRANSIENT defer
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT

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
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

        _make_jsonl(jsonl, user_turns=5)  # smaller file → size < stored end_offset
        _mark_idle(jsonl)  # shrunk session, below flush_bytes → idle flush
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

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
    _mark_idle(jsonl)  # finished-so-far session, below flush_bytes → idle flush
    state = {}
    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        # Every pair is terminal -> all committed; the cursor sits after the last one.
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
        cursor1 = state[rel]["end_offset"]

        # New turn: prompt + a FIRST assistant record still in flight (tool_use). The
        # response is not complete, so nothing new commits and the cursor must not move
        # into the middle of the response. Mark idle too: this must hold back regardless
        # of idle, because the trailing record is genuinely incomplete (not just small).
        _append_user(jsonl, 6)
        _append_assistant(jsonl, 6, stop_reason="tool_use")
        _mark_idle(jsonl)
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) != IngestResult.OK
        assert state[rel]["end_offset"] == cursor1

        # The response completes with a terminal record: prompt + BOTH assistant records
        # commit together — never split.
        _append_assistant(jsonl, 6, stop_reason="end_turn")
        _mark_idle(jsonl)
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK

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
    _mark_idle(jsonl)  # below flush_bytes → idle flush for the closed turns

    state = {}
    captured: list[str] = []
    real_ingest = engine.ingest_conversation

    def capture(content, **kwargs):
        captured.append(content)
        return real_ingest(content=content, **kwargs)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         patch.object(engine, "ingest_conversation", side_effect=capture):
        # Fresh/active: the two task_complete turns commit whole; the in-flight one waits.
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK

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
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush

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
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK

    committed = captured[-1]
    assert "Prompt with the memory detail" in committed   # prompt recovered
    assert "First part of the response" in committed       # both response records,
    assert "Second part with the actual answer" in committed  # paired with the prompt
    assert state[rel]["end_offset"] > mid

    # Recovery is one-time: the cursor is now a safe boundary (file fully consumed), so a
    # second pass on the unchanged file skips without re-recovering.
    assert state[rel]["end_offset"] == jsonl.stat().st_size
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.NO_PROGRESS


def test_codex_inflight_turn_not_split_on_idle(engine, tmp_path):
    """An in-flight Codex turn (no task_complete yet) is held back even when the file
    looks idle — there is no idle flush that could split it."""
    watch_dir = tmp_path / ".codex" / "sessions"
    transcript_dir = watch_dir / "2026" / "06" / "25"
    transcript_dir.mkdir(parents=True)
    jsonl = transcript_dir / "rollout-2026-06-25T12-30-00-sess-sticky.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _append_codex_turn(jsonl, 0, records=2, complete=True)
    _mark_idle(jsonl)  # finished-so-far turn, below flush_bytes → idle flush
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1) == IngestResult.OK
    cursor = state[rel]["end_offset"]

    # In-flight multi-record turn, file now idle. The turn has no closure signal, so it is
    # held back — never flushed mid-response.
    _append_codex_turn(jsonl, 1, records=2, complete=False)
    now = time.time()
    os.utime(jsonl, (now, now - 120))
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=1,
                               idle_threshold=30) == IngestResult.NO_PROGRESS
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
        ) == IngestResult.OK
        assert "User message 8 " not in captured[-1]

        _append_assistant(jsonl, 8)
        now2 = time.time()
        os.utime(jsonl, (now2, now2 - 120))
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=1, idle_threshold=30
        ) == IngestResult.OK

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
        ) == IngestResult.OK
    assert calls == 1


# --- ADR-0003 (#149): gate the rewind on forward progress ---


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
        {"type": "user", "message": {"content": "continue with the previous response"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text",
                "text": "Answer two continues with additional detail"}]}},
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
        {"type": "user", "message": {"content": "Prompt two continues the architecture discussion"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two follows up with more detail"}]}},
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


def test_inflight_orphan_rewind_parks_without_reingest(engine, tmp_path, caplog):
    """ADR-0003 critical regression (Codex review, #149): an orphan with NO forward
    progress whose rewind (full re-parse) ALSO makes no progress — because the tail is a
    still-open (in-flight) response, not a genuinely recoverable one — must park
    (NO_PROGRESS) rather than re-extract the closed prefix on every tick."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"

    closed_turn = [
        {"type": "user", "message": {"content": "Prompt about the release plan"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer about the release plan"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in closed_turn:
            f.write(json.dumps(line) + "\n")
    boundary = parse_transcript(jsonl).safe_end_offset  # cursor parked here by tick N

    # An in-flight response fragment: text-bearing, non-terminal stop_reason, no
    # following user turn and no closure — the response is genuinely still being written.
    with open(jsonl, "a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": "In-flight fragment"}]}}) + "\n")
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": boundary, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 1)
        r2 = _ingest_session(engine, jsonl, state, watch_dir, 1)

    assert r1 == IngestResult.NO_PROGRESS
    assert r2 == IngestResult.NO_PROGRESS
    assert mock_llm.call_count == 0                       # never re-ingested
    assert state[rel]["end_offset"] == boundary            # cursor left untouched


# --- Test 19: in-flight skip reschedules the dropped event (no lost tail) ---

# --- Test 20: shrink resets node_ids provenance, not just turn count ---

def test_shrink_resets_node_ids(engine, tmp_path):
    """A file that shrinks below the stored offset must not carry stale node_ids forward."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    rel = str(jsonl.relative_to(watch_dir))

    _make_jsonl(jsonl, user_turns=10)
    _mark_idle(jsonl)  # finished session, below flush_bytes → idle flush
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
    first_nodes = list(state[rel]["node_ids"])
    assert first_nodes  # first ingest produced at least one node

    _make_jsonl(jsonl, user_turns=5)  # smaller file → size < stored end_offset → full re-ingest
    _mark_idle(jsonl)  # shrunk session, below flush_bytes → idle flush
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK

    # Full re-ingest (prev_offset reset to 0): stale node_ids must not be concatenated,
    # so the stored provenance carries no duplicates.
    nodes = state[rel]["node_ids"]
    assert len(nodes) == len(set(nodes))


# --- Adversarial regressions for the two HIGH council findings ---

# --- Council-PR H1/H2: change-token park key + TRANSIENT deprioritization ---

# --- Council-PR F2/F3: per-tick time budget + lookback<0 never-seen guard ---

# --- Merge of #52 (catch-up off bind path) onto the reconcile rework -------------------
# These cover the behavior the merge introduced that NEITHER prior suite tested:
# the off-bind startup catch-up and the shutdown drain that closes the use-after-close
# window (issue #52), now expressed on the reconcile API (list[SessionWatch] + _stop_event).


def test_large_orphan_beyond_flush_bytes_does_not_rewind(engine, tmp_path, caplog):
    """Beta byte-cap path (council R2): an orphan larger than flush_bytes must not make
    should_rewind true (the first boundary commit ignores the cap while nothing closed),
    and the post-rewind park probe must not mis-park a recoverable file. Cursor advances
    monotonically across ticks; no recovery rewind ever."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    big = "x" * 30_000
    first_turn = [
        {"type": "user", "message": {"content": "Prompt one about the original request"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer one with plenty of real text"}]}},
    ]
    tail = [
        {"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": big}]}},
        {"type": "user", "message": {"content": "continue with the previous response"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Answer two closing the conversation"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in first_turn:
            f.write(json.dumps(line) + "\n")
    boundary = parse_transcript(jsonl).safe_end_offset
    with open(jsonl, "a") as f:
        for line in tail:
            f.write(json.dumps(line) + "\n")
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": boundary, "hash": "stale", "user_turns": 1, "node_ids": []}}

    offsets = [boundary]
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        for _ in range(10):  # bounded drain: several capped ticks may be needed
            r = _ingest_session(engine, jsonl, state, watch_dir, 1, flush_bytes=8000)
            offsets.append(state[rel]["end_offset"])
            if r == IngestResult.NO_PROGRESS:
                break
    assert "recovering legacy mid-response cursor" not in caplog.text
    assert offsets == sorted(offsets)                        # never-regressing cursor
    assert state[rel]["end_offset"] == jsonl.stat().st_size  # fully drained


# ======================================================================================
# ADR-0004 slice 1 — always-on ingest worker; Observer & reconcile become producers.
# The disposition (02-always-on-worker.md) rewrote/deleted the old cursor-flag tests below.
# ======================================================================================


def _partial_unterminated(path):
    """A single user+assistant turn with NO terminal stop_reason -> no safe boundary."""
    path.write_text(
        json.dumps({"type": "user", "message": {"content": "a single prompt with enough text to parse here"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "a partial answer that never closed with a stop reason"}]}})
        + "\n"
    )


# --- Structural: worker always on, Observer opt-in (Step 1) ----------------------------

def test_worker_starts_with_watcher_disabled(engine, tmp_path):
    """session_watcher_enabled=False still yields a live handler + drain, but NO Observer."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        assert len(watches) == 1
        assert watches[0].observer is None
        assert watches[0].handler is not None
        assert watches[0].spool is not None
        assert watches[0].handler._drain_thread.is_alive()
    finally:
        stop_session_watcher(watches)


def test_observer_attached_only_when_enabled(engine, tmp_path):
    """enabled=True keeps today's behavior: Observer scheduled and alive."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        assert watches[0].observer is not None and watches[0].observer.is_alive()
    finally:
        stop_session_watcher(watches)


def test_disabled_yields_worker_without_observer(engine, tmp_path):
    """Row 21 rename of test_disabled_returns_empty: disabled now returns a worker (not [])."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        assert len(watches) == 1
        assert watches[0].observer is None
        assert watches[0].handler is not None
    finally:
        stop_session_watcher(watches)


def test_absent_watch_dir_is_created(engine, tmp_path):
    """Row 22 rename of test_nonexistent_watch_dir: an absent watch root is CREATED and still
    yields a handler (council R4/R5) so a later nudge under it is accepted, not 422'd."""
    missing = tmp_path / "does-not-exist"
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = missing
    watches = start_session_watcher(engine)
    try:
        assert len(watches) == 1
        assert watches[0].watch_dir == _expand_watch_dir(missing)
        assert missing.is_dir()
        assert watches[0].handler is not None
        assert watches[0].observer is None
    finally:
        stop_session_watcher(watches)


def test_configured_but_absent_dir_still_yields_a_handler(engine, tmp_path):
    """council R4/R5 (Step 1, verbatim intent): session_watcher_dir points at a path that does
    not exist yet — start_session_watcher must still return one SessionWatch."""
    missing = tmp_path / "later-appears"
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = missing
    watches = start_session_watcher(engine)
    try:
        assert len(watches) == 1
        assert watches[0].watch_dir == _expand_watch_dir(missing)
        assert missing.is_dir()
        assert watches[0].handler is not None
        assert watches[0].observer is None
    finally:
        stop_session_watcher(watches)


# --- Consent is structural: the queue IS the intent (Step 1) ---------------------------

def test_disabled_worker_ingests_only_what_the_spool_holds(engine, tmp_path):
    """With the watcher disabled the worker drains the queue and nothing else. A transcript
    nobody nudged is never touched — no reconcile scope rule, no discover flag."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    never_seen = proj / "never.jsonl"
    _make_jsonl(never_seen, user_turns=6)
    _mark_idle(never_seen)
    nudged = proj / "nudged.jsonl"
    _make_jsonl(nudged, user_turns=6)
    _mark_idle(nudged)

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        rel_nudged = str(nudged.relative_to(watch_dir))
        rel_never = str(never_seen.relative_to(watch_dir))
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.spool.enqueue(nudged, boundary=nudged.stat().st_size, reason="nudge")
            w.handler.wake()
            assert _wait_until(lambda: rel_nudged in _load_state(watch_dir), timeout=8)
        state = _load_state(watch_dir)
        assert rel_nudged in state
        assert rel_never not in state, \
            "a disabled watcher must not ingest transcripts nobody asked for"
    finally:
        stop_session_watcher(watches)


def test_disabled_worker_ignores_growth_after_the_accepted_boundary(engine, tmp_path):
    """After a nudged transcript drains, APPENDING more turns must not be ingested while the
    watcher is off — new content needs a new nudge (here: an empty queue means no work)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "known.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
            w.handler.wake()
            assert _wait_until(lambda: rel in _load_state(watch_dir), timeout=8)
        first_offset = _load_state(watch_dir)[rel]["end_offset"]
        assert first_offset > 0

        _make_jsonl(jsonl, user_turns=12)          # the session grew; nobody nudged
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            w.handler.wake()
            time.sleep(0.5)
            assert not llm.called, "an empty queue means no work, even with new bytes on disk"
        assert _load_state(watch_dir)[rel]["end_offset"] == first_offset
    finally:
        stop_session_watcher(watches)


def test_a_capped_batch_re_enqueues_the_remainder(engine, tmp_path):
    """The drain must finish a boundary larger than flush_bytes on its own, across several
    capped batches — no sticky flag needed."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "big.jsonl"
    _make_jsonl(jsonl, user_turns=12)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    boundary = jsonl.stat().st_size

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_flush_bytes = 400        # force several capped batches
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            w.spool.enqueue(jsonl, boundary=boundary, reason="nudge")
            w.handler.wake()
            assert _wait_until(
                lambda: (_load_state(watch_dir).get(rel, {}).get("end_offset", 0)) >= boundary,
                timeout=25,
            ), "the drain must reach the accepted boundary across capped batches"
            assert _wait_until(lambda: _spool_idle(w.spool), timeout=5)
    finally:
        stop_session_watcher(watches)


def test_a_transient_failure_keeps_the_job_queued(engine, tmp_path):
    """A failed attempt must not consume the intent, and an OUTAGE must never dead-letter
    (ADR-0004 H1)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        with patch(_LLM_PATCH, return_value=None), \
             patch("ormah.background.session_watcher.ingest_provider_configured",
                   return_value=True):
            w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
            w.handler.wake()
            # the attempt fails (provider "down"); the job is requeued with backoff, not lost
            time.sleep(1.0)
            assert w.spool.pending_count() == 1
        state = _load_state(watch_dir)
        assert rel not in state or state[rel].get("end_offset", 0) == 0
        assert not list((w.spool.root / "failed").iterdir()), \
            "an outage must never dead-letter an accepted job"
    finally:
        stop_session_watcher(watches)


def test_crash_recovery_requeues_an_in_flight_job(engine, tmp_path):
    """A job left in running/ by a killed process must come back on the next start."""
    from ormah.background.ingest_spool import IngestSpool, root_key, spool_root

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    # simulate the previous process: enqueue, claim, then die without completing
    pre = IngestSpool(spool_root(engine.settings) / root_key(_expand_watch_dir(watch_dir)))
    pre.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    assert pre.claim_next() is not None
    assert pre.pending_count() == 0

    watches = start_session_watcher(engine)          # <- the restart
    try:
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _wait_until(
                lambda: _load_state(watch_dir).get(rel, {}).get("end_offset", 0) > 0,
                timeout=12,
            ), "a job orphaned in running/ must be recovered and drained"
    finally:
        stop_session_watcher(watches)


def test_observer_and_drain_never_ingest_the_same_transcript(engine, tmp_path):
    """council R12: the Observer must ENQUEUE, not ingest. With both a file event and a nudge
    racing on one transcript, exactly ONE extraction may run at a time."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    engine.settings.session_watcher_enabled = True       # Observer ON -- the risky config
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_debounce_seconds = 0.05
    concurrent, active = [], []
    lock = threading.Lock()

    def _slow_llm(*a, **kw):
        with lock:
            if active:
                concurrent.append(1)
            active.append(1)
        time.sleep(0.3)
        with lock:
            active.pop()
        return _LLM_RESPONSE

    watches = start_session_watcher(engine)
    try:
        w = watches[0]
        with patch(_LLM_PATCH, side_effect=_slow_llm):
            w.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
            w.handler.wake()
            _make_jsonl(jsonl, user_turns=12)        # file event -> Observer produces too
            time.sleep(2.0)
        assert not concurrent, \
            f"two extractions overlapped on one transcript ({len(concurrent)} times)"
    finally:
        stop_session_watcher(watches)


# --- Discovery vs acceptance roots (council R10/R11) -----------------------------------

def test_acceptance_only_root_is_never_swept_while_enabled(engine, tmp_path, monkeypatch):
    """council R12 (codex): with a CUSTOM session_watcher_dir, the default roots exist only so
    an explicit nudge is not 422'd. They must get no Observer and no reconcile."""
    custom = tmp_path / "custom"
    (custom / "p").mkdir(parents=True)
    default_root = tmp_path / "claude-projects"
    (default_root / "p").mkdir(parents=True)
    stray = default_root / "p" / "nobody-nudged.jsonl"
    _make_jsonl(stray, user_turns=6)
    _mark_idle(stray)

    monkeypatch.setattr(
        "ormah.background.session_watcher._default_acceptance_roots",
        lambda: [_expand_watch_dir(default_root)],
    )
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = custom
    watches = start_session_watcher(engine)
    try:
        acc = next(w for w in watches if w.watch_dir == _expand_watch_dir(default_root))
        assert acc.discover is False
        assert acc.observer is None
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            run_session_reconcile(watches)
            time.sleep(0.3)  # give any (wrongly) enqueued drain a chance to run
            assert not llm.called, "an acceptance-only root must never be swept"
        assert str(stray.relative_to(default_root)) not in _load_state(default_root)
    finally:
        stop_session_watcher(watches)


def test_custom_watch_dir_still_accepts_default_root_nudges(engine, tmp_path, monkeypatch):
    """council R10: a custom session_watcher_dir replaces discovery, but the default Claude/
    Codex roots must still be ACCEPTED (a handler exists) so a nudge under them is not 422'd."""
    custom = tmp_path / "custom"
    custom.mkdir()
    default_root = tmp_path / "claude-projects"
    default_root.mkdir()
    monkeypatch.setattr(
        "ormah.background.session_watcher._default_acceptance_roots",
        lambda: [_expand_watch_dir(default_root)],
    )
    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = custom
    watches = start_session_watcher(engine)
    try:
        dirs = {w.watch_dir for w in watches}
        assert _expand_watch_dir(custom) in dirs
        assert _expand_watch_dir(default_root) in dirs
        acc = next(w for w in watches if w.watch_dir == _expand_watch_dir(default_root))
        assert acc.discover is False and acc.handler is not None
        cus = next(w for w in watches if w.watch_dir == _expand_watch_dir(custom))
        assert cus.discover is True
    finally:
        stop_session_watcher(watches)


def test_overlapping_roots_are_collapsed_to_one(engine, tmp_path, monkeypatch):
    """council R11: an ancestor acceptance root nested with a discovery root collapses to one,
    so a transcript can never get two cursors (single-cursor invariant)."""
    parent = tmp_path / "claude"
    parent.mkdir()
    child = parent / "projects"
    child.mkdir()
    monkeypatch.setattr(
        "ormah.background.session_watcher._default_acceptance_roots",
        lambda: [_expand_watch_dir(parent)],
    )
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = child
    watches = start_session_watcher(engine)
    try:
        assert [w.watch_dir for w in watches] == [_expand_watch_dir(child)]
    finally:
        stop_session_watcher(watches)


# --- Atomic state file -----------------------------------------------------------------

def test_save_state_is_atomic_under_a_torn_write(tmp_path, monkeypatch):
    """A torn write must not discard the cursor file: os.replace raising leaves the ORIGINAL
    intact (measured: 7081 torn reads on a direct write vs 0 via replace)."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    good = {f"proj/f{i}.jsonl": {"end_offset": i, "hash": "h", "node_ids": []} for i in range(300)}
    _save_state(watch_dir, good)
    assert _load_state(watch_dir) == good

    def _boom(src, dst):
        raise OSError("simulated torn write")

    monkeypatch.setattr("ormah.background.session_watcher.os.replace", _boom)
    with pytest.raises(OSError):
        _save_state(watch_dir, {"different": {"end_offset": 999}})
    # every prior entry survives, still valid JSON
    assert _load_state(watch_dir) == good


# --- Rewrites of the reconcile suite (now a producer that enqueues) --------------------

def test_reconcile_ingests_file_the_live_path_missed(engine, tmp_path):
    """A changed, idle transcript whose fsevent never reached the handler is ENQUEUED by the
    sweep and then ingested by the drain."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    rel = str(jsonl.relative_to(watch_dir))
    assert rel not in handler._state
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1          # producer: enqueued the missed file
        _drain_all(handler)
    assert rel in handler._state
    assert handler._state[rel]["user_turns"] == 6


def test_reconcile_skips_subagents_keeps_primary(engine, tmp_path):
    """reconcile's discovery walk enqueues the primary session transcript but skips sibling
    subagent transcripts. Migrated from the dead direct-ingest catch-up scan (ADR-0004
    R12 cleanup) — same assertion, driven through reconcile()+drain instead of the
    orphaned function."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    sub_dir = project_dir / "abc123" / "subagents"
    sub_dir.mkdir(parents=True)
    primary = project_dir / "abc123.jsonl"
    _make_jsonl(primary, user_turns=6)
    _mark_idle(primary)  # finished session, below flush_bytes → idle flush
    _make_jsonl(sub_dir / "agent-deadbeef.jsonl", user_turns=6)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1  # only the primary is a candidate
        _drain_all(handler)

    rel = str(primary.relative_to(watch_dir))
    sub_rel = str((sub_dir / "agent-deadbeef.jsonl").relative_to(watch_dir))
    assert rel in handler._state
    assert sub_rel not in handler._state


def test_reconcile_respects_lookback_for_never_seen_files(engine, tmp_path):
    """A positive lookback cutoff excludes an old never-seen file from the reconcile sweep
    while a recent never-seen file is enqueued and ingested. Migrated from the dead
    direct-ingest catch-up scan (ADR-0004 R12 cleanup) — reconcile's lookback_hours>0
    cutoff branch (as opposed to the lookback_hours<0 disabled case already covered by
    test_reconcile_skips_never_seen_when_lookback_negative) had no direct test before this."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)

    recent = project_dir / "recent.jsonl"
    _make_jsonl(recent, user_turns=6)
    _mark_idle(recent)  # finished session, below flush_bytes → idle flush

    old = project_dir / "old.jsonl"
    _make_jsonl(old, user_turns=6)
    old_time = time.time() - (200 * 3600)  # beyond the 72h lookback below
    os.utime(old, (old_time, old_time))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool", lookback_hours=72)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1  # only recent enqueued
        _drain_all(handler)

    rel_recent = str(recent.relative_to(watch_dir))
    rel_old = str(old.relative_to(watch_dir))
    assert rel_recent in handler._state
    assert rel_old not in handler._state


def test_reconcile_skips_fully_consumed_file_on_second_pass(engine, tmp_path):
    """A second sweep does not re-enqueue a file already consumed to EOF."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1
        _drain_all(handler)
        assert handler.reconcile() == 0          # fully consumed -> no duplicate enqueue


def test_reconcile_does_not_reingest_what_live_path_already_took(engine, tmp_path):
    """reconcile shares handler state, so a file already drained is not re-enqueued."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    rel = str(jsonl.relative_to(watch_dir))
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")   # the live path enqueues it
        _drain_all(handler)
        node_count = len(handler._state[rel]["node_ids"])
        assert handler.reconcile() == 0            # not re-enqueued
    assert len(handler._state[rel]["node_ids"]) == node_count


def test_reconcile_logs_recovery_heartbeat(engine, tmp_path, caplog):
    """reconcile emits the functional heartbeat, now counting ENQUEUED (not ingested)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with caplog.at_level("INFO", logger="ormah.background.session_watcher"):
        handler.reconcile()
    assert any("reconcile enqueued" in r.message for r in caplog.records)


def test_reconcile_recovers_partial_tail_without_mtime_change(engine, tmp_path):
    """A grown tail with an UNCHANGED mtime is still enqueued (cursor != size, not mtime)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1
        _drain_all(handler)
        old_mtime = jsonl.stat().st_mtime
        _make_jsonl(jsonl, user_turns=12)             # append 6 more (size grows)
        os.utime(jsonl, (old_mtime, old_mtime))       # mtime unchanged on purpose
        assert handler.reconcile() == 1               # picked up via end_offset != size
        _drain_all(handler)
    assert handler._state[rel]["end_offset"] == jsonl.stat().st_size


def test_reconcile_while_live_ingesting_does_not_double_enqueue(engine, tmp_path):
    """reconcile no longer touches _ingesting; a path already queued at its current boundary
    is not double-enqueued (enqueue is idempotent per (path, boundary))."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    assert handler.spool.pending_count() == 1
    handler.reconcile()                               # producer must not double-queue
    assert handler.spool.pending_count() == 1


def test_reconcile_skips_never_seen_when_lookback_negative(engine, tmp_path):
    """lookback_hours < 0 (catch-up disabled): never-seen files are not enqueued."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool", lookback_hours=-1)
    rel = str(jsonl.relative_to(watch_dir))
    assert rel not in handler._state
    assert handler.reconcile() == 0
    assert handler.spool.pending_count() == 0
    assert rel not in handler._state


def test_reconcile_respects_per_tick_enqueue_cap(engine, tmp_path):
    """D3: the per-tick budget survives as the producer-side ENQUEUE cap — a sweep over more
    candidates than the cap enqueues exactly the cap."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.engine.settings.session_watcher_reconcile_max_per_tick = 2
    for i in range(5):
        p = proj / f"session-{i:02d}.jsonl"
        _make_jsonl(p, user_turns=6)
        _mark_idle(p)
    assert handler.reconcile() == 2
    assert handler.spool.pending_count() == 2


def test_reconcile_does_not_starve_valid_file_behind_stuck_never_seen_files(engine, tmp_path):
    """D3: > cap never-seen files that dead-letter must not starve a later valid transcript —
    once they leave the candidate set the valid file gets through under the enqueue cap."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.engine.settings.session_watcher_reconcile_max_per_tick = 3
    now = time.time()
    for i in range(3):                                # oldest -> enqueued first
        p = proj / f"stuck-{i:03d}.jsonl"
        _partial_unterminated(p)
        os.utime(p, (now - 1000 + i, now - 1000 + i))
    valid = proj / "zz-valid.jsonl"                   # newer than the stuck files -> sorts last
    _make_jsonl(valid, user_turns=6)
    os.utime(valid, (now - 100, now - 100))           # idle (age > threshold) yet newest
    rel_valid = str(valid.relative_to(watch_dir))

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        for _ in range(4):
            handler.reconcile()
            _drain_all(handler)
            if rel_valid in handler._state:
                break
    assert rel_valid in handler._state                # reached, not starved


def test_a_due_job_is_claimed_ahead_of_a_backed_off_one(engine, tmp_path):
    """T-N1: a due valid job is ingested and does not stall behind an external-failure job
    whose not_before is in the future (replaces the deprioritization FIFO coverage)."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    valid = proj / "valid.jsonl"
    _make_jsonl(valid, user_turns=6)
    _mark_idle(valid)
    stuck = proj / "stuck.jsonl"
    _make_jsonl(stuck, user_turns=6)
    _mark_idle(stuck)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    rel_valid = str(valid.relative_to(watch_dir))

    spool.enqueue(stuck, boundary=stuck.stat().st_size, reason="nudge")
    stuck_job = spool.claim_next()
    spool.requeue(stuck_job, failure_class="external")   # not_before ~ now + backoff
    spool.enqueue(valid, boundary=valid.stat().st_size, reason="nudge")

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)                              # claims the due one, skips the backed-off
    assert rel_valid in handler._state
    assert spool.pending_count() == 1                    # the backed-off job is still queued
    assert not list((spool.root / "failed").iterdir())   # not dead-lettered


def test_reconcile_enqueues_at_most_the_per_tick_cap(engine, tmp_path):
    """T-N2: a sweep over more than the cap enqueues exactly the cap, OLDEST-first."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.engine.settings.session_watcher_reconcile_max_per_tick = 3
    now = time.time()
    files = []
    for i in range(5):
        p = proj / f"s-{i}.jsonl"
        _make_jsonl(p, user_turns=6)
        os.utime(p, (now - (100 - i), now - (100 - i)))   # i=0 oldest .. i=4 newest
        files.append(p)

    assert handler.reconcile() == 3
    assert handler.spool.pending_count() == 3
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)
    state = handler._state
    for p in files[:3]:                                   # the 3 oldest
        assert str(p.relative_to(watch_dir)) in state
    for p in files[3:]:                                   # the 2 newest were not enqueued
        assert str(p.relative_to(watch_dir)) not in state


def test_idle_file_with_no_safe_boundary_is_dead_lettered(engine, tmp_path):
    """T-N3: an idle transcript whose bytes never reach a safe boundary (a single unterminated
    turn) dead-letters with a distinct reason instead of silently completing."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "partial.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    assert list((spool.root / "failed").glob("*.json")), \
        "an idle file with no safe boundary must be dead-lettered, not silently completed"
    assert spool.pending_count() == 0
    assert not any(p.name.endswith(".json") for p in (spool.root / "running").iterdir())
    errs = list((spool.root / "failed").glob("*.error"))
    assert errs and "no_safe_boundary" in errs[0].read_text()


def test_frozen_prefix_advance_never_passes_the_accepted_boundary(engine, tmp_path):
    """council-pr F1: a nudge accepted boundary B; the live file then grew to S>B, still an
    unterminated single turn, and went idle. The frozen-prefix advance must stop the cursor
    at B (the accepted boundary), NEVER at raw EOF S -- bytes [B,S] were never accepted nor
    extracted, so a later nudge at S must still be able to re-examine them."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "partial.jsonl"

    def _user(t):
        return json.dumps({"type": "user", "message": {"content": t}})

    def _asst_open(t):  # no stop_reason, no following user -> never a safe boundary
        return json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}
        )

    prefix = _user("prompt one long enough to parse here") + "\n" \
        + _asst_open("answer one still streaming and open") + "\n"
    jsonl.write_text(prefix)
    boundary = jsonl.stat().st_size          # B: exactly what the nudge measured

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    spool.enqueue(jsonl, boundary=boundary, reason="nudge")   # the nudge accepted exactly B

    # the LIVE session grew PAST the accepted boundary, still with no safe boundary anywhere
    jsonl.write_text(
        prefix + _asst_open("more streaming tokens appended after the boundary") + "\n"
    )
    size = jsonl.stat().st_size               # S
    assert size > boundary
    _mark_idle(jsonl)                         # ...then went idle with the turn still open

    rel = str(jsonl.relative_to(watch_dir))
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)

    cursor = _load_state(watch_dir).get(rel, {}).get("end_offset", 0)
    assert cursor <= boundary, (
        f"frozen-prefix advance jumped the cursor to {cursor} (S={size}); it must never "
        f"pass the accepted boundary B={boundary}, or bytes [B,S] are skipped forever"
    )
    # [B,S] was not permanently consumed: a second nudge at S can still claim it for work.
    spool.enqueue(jsonl, boundary=size, reason="nudge")
    assert spool.claim_next() is not None, "the second nudge at S must be claimable"


def test_unexpected_exception_requeues_instead_of_stranding_in_running(engine, tmp_path):
    """council-pr F2: an unexpected exception AFTER the job is claimed into running/ must not
    strand it there until the next restart's recover(). The drain loop requeues it as an
    EXTERNAL failure (persisted backoff) so it returns to pending/ and retries -- never
    dead-lettered (H1)."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")

    orig_run = SessionHandler._run_job
    state = {"raised": False}

    def flaky(self, job):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("unexpected mid-ingest failure after the claim")
        return orig_run(self, job)

    running = spool.root / "running"

    def running_json():
        return [p for p in running.iterdir() if p.name.endswith(".json")]

    try:
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), \
             patch.object(SessionHandler, "_run_job", flaky):
            handler.start_drain()
            handler.wake()
            assert _wait_until(
                lambda: state["raised"] and not running_json(), timeout=8
            ), "the claimed job was stranded in running/ after an unexpected exception"
            assert _wait_until(lambda: spool.pending_count() >= 1, timeout=8), \
                "the job must be back in pending/ (requeued with backoff), not lost"
            assert not list((spool.root / "failed").iterdir()), \
                "a transient/unexpected error must never dead-letter accepted work (H1)"
    finally:
        handler._stop_event.set()
        handler.wake()
        handler.join_drain(timeout=5)


def test_observer_job_respects_min_turns_but_nudge_force_flushes(engine, tmp_path):
    """council-pr F3: force-flush is the NUDGE's intent, not every producer's. An Observer
    job for a fresh, below-min_turns, NON-idle transcript must NOT bypass the min_turns gate
    (it would fragment an active session); the same transcript via a NUDGE job DOES
    force-flush and ingest a short just-ended session."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)

    # Fresh (NOT idle) + below min_turns=5 -> the min_turns accumulation gate applies.
    obs_file = proj / "obs.jsonl"
    _make_jsonl(obs_file, user_turns=2)       # 2 < 5, mtime is now -> active
    rel_obs = str(obs_file.relative_to(watch_dir))
    spool.enqueue(obs_file, boundary=obs_file.stat().st_size, reason="observer", force_flush=False)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
        _drain_all(handler)
    assert rel_obs not in _load_state(watch_dir), \
        "an Observer job must not force-flush past the min_turns gate on an active session"
    assert not llm.called, "no extraction may run for a deferred below-min_turns Observer job"

    # The SAME shape via a NUDGE force-flushes: a SessionEnd/PreCompact is an explicit ask.
    nudge_file = proj / "nudge.jsonl"
    _make_jsonl(nudge_file, user_turns=2)     # also below min_turns and active
    rel_nudge = str(nudge_file.relative_to(watch_dir))
    spool.enqueue(nudge_file, boundary=nudge_file.stat().st_size, reason="nudge", force_flush=True)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _drain_all(handler)
    assert rel_nudge in _load_state(watch_dir), \
        "a nudge job must force-flush a short just-ended session past the min_turns gate"


def test_frozen_prefix_advance_never_moves_the_cursor_backward(engine, tmp_path):
    """council-pr R2 F2: _mark_frozen_prefix_consumed must be monotonic. A stale or
    out-of-order boundary job (boundary < the current cursor) must NEVER rewind the cursor --
    that would re-open already-consumed bytes for duplicate extraction. The prior
    ``end_offset = min(boundary, size)`` wrote the lower boundary directly."""
    from ormah.background.ingest_spool import IngestSpool
    from ormah.background.session_watcher import _commit_state

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    jsonl.write_text("x" * 5000)
    rel = str(jsonl.relative_to(watch_dir))

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    # cursor already well past, persisted to BOTH memory and disk
    _commit_state(handler._state, rel, {"end_offset": 4000}, handler._state_lock, watch_dir)

    handler._mark_frozen_prefix_consumed(jsonl, rel, boundary=1000)   # stale, LOWER boundary
    assert handler._state[rel]["end_offset"] == 4000, (
        "a boundary below the current cursor must never rewind it (duplicate re-ingestion)"
    )
    assert _load_state(watch_dir).get(rel, {}).get("end_offset") == 4000, (
        "the rewind must not be persisted to disk either"
    )


def test_capped_continuation_inherits_the_producer_force_flush(engine, tmp_path):
    """council-pr R2 F4: a capped batch's 'drain' continuation must inherit the ORIGINATING
    producer's force_flush, not force-flush unconditionally. An Observer's capped remainder
    must continue NON-forcing (else it fragments an active session past its gates); a nudge's
    remainder stays forcing."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool", min_turns=1)
    handler.flush_bytes = 300      # small -> the first closed batch caps (content past it)
    spool = handler.spool

    obs_file = proj / "obs.jsonl"
    _make_jsonl(obs_file, user_turns=12)       # large -> flush_bytes=300 caps the first batch
    _mark_idle(obs_file)
    spool.enqueue(obs_file, boundary=obs_file.stat().st_size, reason="observer", force_flush=False)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        job = spool.claim_next()
        handler._run_job(job)                  # OK + capped -> enqueues a 'drain' continuation
    conts = [json.loads(p.read_text()) for p in (spool.root / "pending").glob("*.json")]
    assert conts, "a capped Observer batch must enqueue a drain continuation"
    assert all(c["reason"] == "drain" for c in conts)
    assert all(c["force_flush"] is False for c in conts), (
        "an Observer-originated continuation must NOT force-flush the remainder"
    )

    nudge_file = proj / "nudge.jsonl"
    _make_jsonl(nudge_file, user_turns=12)
    spool.enqueue(nudge_file, boundary=nudge_file.stat().st_size, reason="nudge", force_flush=True)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        job = spool.claim_next()
        handler._run_job(job)
    n_conts = [
        json.loads(p.read_text())
        for p in (spool.root / "pending").glob("*.json")
        if "nudge" in Path(json.loads(p.read_text())["path"]).name
    ]
    assert n_conts, "a capped nudge batch must enqueue a drain continuation"
    assert all(c["force_flush"] is True for c in n_conts), (
        "a nudge-originated continuation must keep force-flushing the remainder"
    )


def test_live_drain_recovers_a_job_stranded_in_running(engine, tmp_path):
    """council-pr R2 F1: a job orphaned in running/ (a requeue that itself failed on an FS
    fault) is invisible to claim_next, which scans only pending/. The live drain must
    periodically recover running/ back to pending/ WITHOUT waiting for a process restart."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge", force_flush=True)
    claimed = spool.claim_next()               # moves it into running/
    assert claimed is not None and spool.pending_count() == 0
    # deliberately do NOT complete/requeue -> stranded in running/, invisible to a pending scan
    handler._idle_poll_seconds = 0.05          # tick the idle recover fast for the test
    handler._recover_stale_seconds = 0.0       # recover regardless of age (default 60s gate)

    try:
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            handler.start_drain()
            handler.wake()
            assert _wait_until(
                lambda: _spool_idle(spool) and rel in _load_state(watch_dir), timeout=8
            ), "the stranded running/ job was never recovered and ingested by the live drain"
    finally:
        handler._stop_event.set()
        handler.wake()
        handler.join_drain(timeout=5)


# --- Debounce coalescing now happens on the producer (enqueue), not the ingest ---------

def test_debounce_coalesces_writes(engine, tmp_path):
    """5 rapid events -> 1 ENQUEUE (the debounce coalesces on the Observer, the drain would
    then ingest once)."""
    from watchdog.events import FileModifiedEvent

    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-proj"
    proj.mkdir(parents=True)
    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 0.3, 5, spool=spool)
    jsonl = proj / "active.jsonl"

    for i in range(5):
        _make_jsonl(jsonl, user_turns=6 + i)
        handler.on_modified(FileModifiedEvent(str(jsonl)))
        time.sleep(0.05)
    time.sleep(0.5)                                        # let the single debounced timer fire

    assert spool.pending_count() == 1


def test_retry_fires_and_ingests_after_idle(engine, tmp_path):
    """The idle refire now ENQUEUES; the appended tail is ingested through the drain path."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-proj"
    proj.mkdir(parents=True)
    jsonl = proj / "active.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool", idle_threshold=30)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
    first_offset = handler._state[rel]["end_offset"]
    assert first_offset > 0

    _append_pair(jsonl, 6)
    _append_pair(jsonl, 7)
    _mark_idle(jsonl)                                     # grew, then went idle
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
    assert handler._state[rel]["end_offset"] > first_offset


# --- Shutdown / lifecycle against the drain thread -------------------------------------

def test_drain_rejected_after_stop_event(engine, tmp_path):
    """Once _stop_event is set, the drain refuses to ingest before touching the engine —
    the use-after-close guard at shutdown (issue #52), now on the drain claim step."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl)
    _mark_idle(jsonl)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    handler._stop_event.set()
    spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    job = spool.claim_next()
    assert job is not None

    with patch("ormah.background.session_watcher._ingest_session") as mock_ingest:
        handler._run_job(job)

    mock_ingest.assert_not_called()
    assert handler.in_flight_count() == 0


def test_stop_session_watcher_drains_inflight_ingest(engine, tmp_path):
    """stop_session_watcher blocks until an in-flight drain ingest finishes, so nothing writes
    to the DB after engine.shutdown() (use-after-close guard, issue #52)."""
    from ormah.background.ingest_spool import IngestSpool
    from ormah.background.session_watcher import SessionWatch

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-proj"
    proj.mkdir(parents=True)
    jsonl = proj / "x.jsonl"
    _make_jsonl(jsonl)
    _mark_idle(jsonl)

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)

    entered = threading.Event()
    release = threading.Event()

    def blocking_ingest(*a, **k):
        entered.set()
        release.wait(5)
        return IngestResult.OK

    spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    with patch("ormah.background.session_watcher._ingest_session", side_effect=blocking_ingest):
        handler.start_drain()
        handler.wake()
        assert entered.wait(5)                     # an ingest is now in-flight on the drain
        assert handler.in_flight_count() == 1

        watch = SessionWatch(
            watch_dir=watch_dir, handler=handler, observer=MagicMock(),
            spool=spool, discover=False,
        )
        stop_returned = threading.Event()

        def stopper():
            stop_session_watcher([watch])
            stop_returned.set()

        s = threading.Thread(target=stopper)
        s.start()
        assert not stop_returned.wait(0.5)         # stop must NOT return while ingest is in-flight
        release.set()                              # let the ingest finish
        assert stop_returned.wait(5)               # now the drain completes and stop returns
        s.join(5)
    assert handler.in_flight_count() == 0


# --- ADR-0004 slice 2: bounded shutdown (cancel in-flight LLM extractions) -------------

def test_late_built_adapter_is_still_cancelled_bounded(monkeypatch):
    """HIGH-C (council R2, Codex): a job that starts AFTER the first cancel pass lazily builds
    a fresh (clean, instance-scoped) adapter and only becomes cancellable once _stop_and_drain's
    fence loop cancels it AGAIN. The loop must still terminate in bounded time — not rely on a
    FIXED number of passes: the fake here only reports the drain dead on the THIRD
    cancel_active_llm_calls() call, which a hardcoded two-pass "cancel; join; cancel; join"
    implementation (the design HIGH-C rejected) cannot satisfy — only a real while-loop that
    keeps cancelling until the drain is actually dead can. See I-1 discrimination proof in the
    task-2 report for a run of this exact test against a rejected two-pass implementation."""
    from ormah.background.session_watcher import SessionWatch, _stop_and_drain

    calls = {"cancel": 0}
    alive = {"value": True}

    class _FakeHandler:
        def __init__(self):
            self._stop_event = threading.Event()

        def cancel_pending_timers(self):
            pass

        def wake(self):
            pass

        def drain_alive(self):
            return alive["value"]

        def join_drain(self, timeout=None):
            time.sleep(min(timeout or 0, 0.05))

    def _fake_cancel_active_llm_calls():
        calls["cancel"] += 1
        if calls["cancel"] >= 3:
            alive["value"] = False  # the late-built adapter is now cancelled -> drain exits
        return 1

    monkeypatch.setattr(
        "ormah.background.session_watcher.cancel_active_llm_calls", _fake_cancel_active_llm_calls
    )
    monkeypatch.setattr("ormah.background.session_watcher.resume_llm_adapters", lambda: None)
    monkeypatch.setattr("ormah.background.session_watcher._drain_handlers", lambda handlers: None)

    handler = _FakeHandler()
    watch = SessionWatch(watch_dir=Path("/tmp/late-adapter"), handler=handler, observer=None,
                          spool=None, discover=False)

    start = time.monotonic()
    _stop_and_drain([watch])
    elapsed = time.monotonic() - start

    assert calls["cancel"] >= 3, (
        "at least a THIRD cancel pass was needed to catch the late-built adapter -- a fixed "
        "two-pass implementation (cancel; join; cancel; join) cannot reach this, only a real "
        "while-loop that keeps cancelling until drain_alive() reports dead can"
    )
    assert elapsed < 5.0, "the fence loop must be bounded, not wait out a full extraction budget"


def test_startup_rollback_drains_failing_roots_own_inflight_extraction(engine, tmp_path, monkeypatch):
    """HIGH-B (council R1, Codex): start_session_watcher registers a PROVISIONAL SessionWatch
    for each root BEFORE observer.start() -- so when a later root's Observer.start() raises,
    the FAILING root's own already-draining handler (genuinely mid-extraction, not just
    registered) is still inside `watches`: the rollback CANCELS it, JOINS its drain thread, and
    nothing touches the engine again afterward (#52 use-after-close). A pre-seeded, blocked
    extraction on root2 -- root2 is the root whose OWN Observer.start() raises -- proves the
    rollback actually drains, not merely registers: a no-op `_stop_and_drain` would leave
    drain_alive()/in_flight_count() nonzero and would not need to wait for `release`."""
    import ormah.background.session_watcher as sw_mod
    from ormah.background.ingest_spool import IngestSpool, root_key, spool_root

    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()
    monkeypatch.setattr(
        "ormah.background.session_watcher._resolve_acceptance_roots",
        lambda settings: [(root1, True), (root2, True)],
    )

    # Pre-seed root2's spool with a job BEFORE start_session_watcher runs, so root2's drain
    # thread claims and starts extracting it the instant handler.start_drain() fires -- racing
    # root2's own (later, in the same loop iteration) Observer.start() failure.
    proj = root2 / "-Users-alice-Code-proj"
    proj.mkdir(parents=True)
    jsonl = proj / "abc.jsonl"
    _make_jsonl(jsonl)
    _mark_idle(jsonl)
    seed_spool = IngestSpool(spool_root(engine.settings) / root_key(root2))
    seed_spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge", force_flush=True)

    entered = threading.Event()   # the pre-seeded job is now genuinely mid-extraction on root2
    release = threading.Event()   # let the blocked extraction return

    ingest_calls = []

    def _blocking_ingest(*a, **k):
        ingest_calls.append(1)
        entered.set()
        release.wait(5)
        return IngestResult.OK

    captured = {}
    real_stop_and_drain = sw_mod._stop_and_drain

    def _spy(watches, **kw):
        captured["watches"] = list(watches)
        captured["kwargs"] = kw
        return real_stop_and_drain(watches, **kw)

    monkeypatch.setattr("ormah.background.session_watcher._stop_and_drain", _spy)

    class _FailingObserver:
        _n = 0

        def __init__(self):
            type(self)._n += 1
            self._fail = type(self)._n == 2  # the SECOND root's (root2's own) Observer fails

        def schedule(self, *a, **k):
            pass

        def start(self):
            if self._fail:
                # root2's own extraction must be genuinely in-flight before its Observer fails
                # -- otherwise this would not exercise a real drain/join race at all.
                assert entered.wait(5), "root2's in-flight extraction never started"
                raise RuntimeError("observer boom")

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

    outcome = {}

    def _run():
        try:
            with patch(
                "ormah.background.session_watcher._ingest_session", side_effect=_blocking_ingest
            ), patch("ormah.background.session_watcher.Observer", _FailingObserver):
                start_session_watcher(engine)
        except RuntimeError as e:
            outcome["exc"] = e

    t = threading.Thread(target=_run)
    t.start()

    assert entered.wait(5), "root2's pre-seeded job never reached the blocking ingest"
    # The rollback has now been entered (Observer.start() raised right after seeing `entered`)
    # and _stop_and_drain is inside its fence loop, waiting on this exact drain thread.
    assert _wait_until(lambda: "watches" in captured, timeout=5)
    by_dir = {w.watch_dir: w for w in captured["watches"]}
    root2_handler = by_dir[root2].handler
    # The extraction is STILL genuinely in-flight while the rollback is (supposedly) draining
    # it -- proves the rollback is actually waiting on it, not a no-op that already returned.
    assert root2_handler.in_flight_count() == 1
    assert root2_handler.drain_alive() is True
    # The sharpest discriminator: start_session_watcher (running on `t`) must still be BLOCKED
    # inside the rollback at this point -- a no-join `_stop_and_drain` would already have
    # returned and raised, and `t` would already be dead, well before we ever release the
    # extraction below.
    assert t.is_alive(), (
        "the rollback must still be draining root2's in-flight extraction -- it must not have "
        "already returned/raised before the extraction was even released"
    )

    release.set()  # let the blocked extraction finish
    t.join(timeout=10)

    assert not t.is_alive(), "start_session_watcher must return once the drain is fully joined"
    assert isinstance(outcome.get("exc"), RuntimeError)
    assert len(captured["watches"]) == 2, (
        "both root1 (fully started) and root2 (whose Observer.start() failed) must be in "
        "`watches` -- a provisional registration must own the root it is constructing"
    )
    assert by_dir[root1].observer is not None   # root1's own observer started fine
    # M-3: the observer is assigned onto the watch BEFORE start() is called, so even though
    # root2's own start() raised, `watch.observer` is still populated -- the rollback's
    # _stop_and_drain can stop()/join() it instead of leaking a half-started Observer.
    assert by_dir[root2].observer is not None
    assert captured["kwargs"].get("rearm") is True

    # The rollback actually DRAINED root2's in-flight extraction, not just registered it:
    assert root2_handler.drain_alive() is False, "root2's drain thread must be joined by rollback"
    assert root2_handler.in_flight_count() == 0, "no in-flight ingest may survive the rollback"
    assert len(ingest_calls) == 1, "no extraction may run again after the stop event is set (#52)"


def test_startup_rollback_rearms_adapters_and_serves(engine, tmp_path, monkeypatch):
    """HIGH-A (council R1, Cursor): the transactional startup rollback must
    resume_llm_adapters() -- the process keeps serving after a rollback (main.lifespan catches
    the failure), so leaving an adapter cancelled would poison every later maintenance/ingest
    LLM call until restart. A normal shutdown must NEVER do this (rearm=False by default)."""
    from ormah.background import llm_client
    from ormah.background.llm_errors import LlmCancelledError

    class _FakeAdapter:
        def __init__(self):
            self._cancelled = False

        def cancel_active(self):
            self._cancelled = True
            return 1

        def resume(self):
            self._cancelled = False

        def generate(self, *a, **k):
            if self._cancelled:
                raise LlmCancelledError("still cancelled")
            return "ok"

    fake = _FakeAdapter()
    fake.cancel_active()  # seed: a call already cancelled this adapter before the rollback runs
    assert fake._cancelled is True
    monkeypatch.setattr(llm_client, "_cached_adapter", fake)
    monkeypatch.setattr(llm_client, "_adapter_initialised", True)

    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()
    monkeypatch.setattr(
        "ormah.background.session_watcher._resolve_acceptance_roots",
        lambda settings: [(root1, True), (root2, True)],
    )

    class _FailingObserver:
        _n = 0

        def __init__(self):
            type(self)._n += 1
            self._fail = type(self)._n == 2

        def schedule(self, *a, **k):
            pass

        def start(self):
            if self._fail:
                raise RuntimeError("observer boom")

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

    with patch("ormah.background.session_watcher.Observer", _FailingObserver):
        with pytest.raises(RuntimeError):
            start_session_watcher(engine)

    assert fake._cancelled is False, "the adapter must be RE-ARMED after a rollback (HIGH-A)"
    assert llm_client.llm_generate(engine.settings, "prompt") == "ok"


def test_startup_rollback_rearms_even_when_observer_join_raises(engine, tmp_path, monkeypatch):
    """HIGH-3 (council-pr, Codex): the HIGH-B fix assigns watch.observer BEFORE observer.start(),
    so a provisional Observer whose start() raised is a NEVER-STARTED thread; its join() raises
    RuntimeError('cannot join thread before it is started'). That exception must NOT escape
    _stop_and_drain and skip resume_llm_adapters() on the rollback path — otherwise main.lifespan
    keeps serving with adapters permanently cancelled (ingest AND maintenance dead until restart).
    """
    from ormah.background import llm_client
    from ormah.background.llm_errors import LlmCancelledError

    class _FakeAdapter:
        def __init__(self):
            self._cancelled = False

        def cancel_active(self):
            self._cancelled = True
            return 1

        def resume(self):
            self._cancelled = False

        def generate(self, *a, **k):
            if self._cancelled:
                raise LlmCancelledError("still cancelled")
            return "ok"

    fake = _FakeAdapter()
    fake.cancel_active()  # seed: cancelled before the rollback runs
    assert fake._cancelled is True
    monkeypatch.setattr(llm_client, "_cached_adapter", fake)
    monkeypatch.setattr(llm_client, "_adapter_initialised", True)

    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()
    monkeypatch.setattr(
        "ormah.background.session_watcher._resolve_acceptance_roots",
        lambda settings: [(root1, True), (root2, True)],
    )

    class _JoinRaisingObserver:
        """Second observer's start() raises (never-started thread); its join() then raises the
        real RuntimeError a threading.Thread raises when joined before it is started."""

        _n = 0

        def __init__(self):
            type(self)._n += 1
            self._started = False
            self._fail = type(self)._n == 2

        def schedule(self, *a, **k):
            pass

        def start(self):
            if self._fail:
                raise RuntimeError("observer boom")
            self._started = True

        def stop(self):
            pass  # watchdog's stop() on a never-started observer is a no-op; join() is the trap

        def join(self, timeout=None):
            if not self._started:
                raise RuntimeError("cannot join thread before it is started")

    with patch("ormah.background.session_watcher.Observer", _JoinRaisingObserver):
        with pytest.raises(RuntimeError):
            start_session_watcher(engine)

    assert fake._cancelled is False, \
        "adapters must be RE-ARMED after a rollback even when observer.join() raised (HIGH-3)"
    assert llm_client.llm_generate(engine.settings, "prompt") == "ok"


def test_start_session_watcher_recovers_backlog_off_bind(engine, tmp_path):
    """start_session_watcher makes the Observer live immediately (no synchronous scan blocks the
    bind) and the pre-existing backlog is recovered off-bind via the startup discovery sweep +
    drain — not a synchronous bind-time scan (issue #52)."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    engine.settings.session_watcher_enabled = True
    engine.settings.session_watcher_dir = watch_dir
    engine.settings.session_watcher_lookback_hours = 9999

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        watches = start_session_watcher(engine)
        try:
            assert len(watches) == 1
            assert watches[0].observer is not None and watches[0].observer.is_alive()
            assert watches[0].spool is not None   # the always-on worker owns recovery now
            assert _wait_until(lambda: rel in watches[0].handler._state, timeout=12), \
                "the startup backlog must be recovered off the bind path"
        finally:
            stop_session_watcher(watches)


# --- run_session_reconcile: Observer opt-in, sweep gated on discover -------------------

def test_run_session_reconcile_recreates_dead_observer(engine, tmp_path):
    """A dead Observer is stopped/joined and recreated; the sweep is gated on discover."""
    from ormah.background.ingest_spool import IngestSpool
    from ormah.background.session_watcher import SessionWatch

    watch_dir = tmp_path / "projects"
    watch_dir.mkdir(parents=True)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999,
                             spool=IngestSpool(tmp_path / "spool"))

    dead = MagicMock()
    dead.is_alive.return_value = False
    watch = SessionWatch(watch_dir=watch_dir, handler=handler, observer=dead,
                         spool=handler.spool, discover=False)

    with patch("ormah.background.session_watcher.Observer") as MockObserver:
        new_obs = MockObserver.return_value
        total = run_session_reconcile([watch])

    dead.stop.assert_called_once()
    dead.join.assert_called_once()
    new_obs.schedule.assert_called_once()
    new_obs.start.assert_called_once()
    assert watch.observer is new_obs
    assert total == 0  # discover=False -> the sweep is skipped


def test_run_session_reconcile_runs_reconcile_even_when_recreate_fails(engine, tmp_path):
    """If recreating a dead Observer raises, a discover watch still runs its reconcile sweep."""
    from ormah.background.ingest_spool import IngestSpool
    from ormah.background.session_watcher import SessionWatch

    watch_dir = tmp_path / "projects"
    watch_dir.mkdir(parents=True)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999,
                             spool=IngestSpool(tmp_path / "spool"))
    handler.reconcile = MagicMock(return_value=0)

    dead = MagicMock()
    dead.is_alive.return_value = False
    watch = SessionWatch(watch_dir=watch_dir, handler=handler, observer=dead,
                         spool=handler.spool, discover=True)

    with patch("ormah.background.session_watcher.Observer", side_effect=RuntimeError("boom")):
        total = run_session_reconcile([watch])

    handler.reconcile.assert_called_once()  # safety net ran despite recreate failure
    assert total == 0


def test_run_session_reconcile_skips_observer_recreation_when_none(engine, tmp_path):
    """run_session_reconcile on an observer-less watch does NOT create an Observer."""
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    engine.settings.session_watcher_enabled = False
    engine.settings.session_watcher_dir = watch_dir
    watches = start_session_watcher(engine)          # disabled -> observer None
    try:
        run_session_reconcile(watches)
        assert watches[0].observer is None
    finally:
        stop_session_watcher(watches)


# --- ADR-0004 Task 3: force-flush + the accepted-boundary hard ceiling ---


def test_force_flush_ingests_fresh_small_transcript(engine, tmp_path):
    """A JUST-written transcript (not idle) with fewer than min_turns user turns is ingested
    when force_flush is set (the nudge's intent), and is NOT ingested without it — that gap
    is what makes a SessionEnd nudge useless otherwise. force_flush is now decoupled from the
    boundary ceiling (council-pr F3): the boundary caps how far a parse reads; only the
    explicit force_flush bypasses the min_turns/idle gate."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)          # below min_turns, and NOT _mark_idle'd
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # A boundary ALONE (Observer/reconcile job) must not force past the min_turns gate.
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5,
            boundary=jsonl.stat().st_size) != IngestResult.OK
        # The nudge lane force-flushes: below min_turns and not idle, it still ingests.
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5,
            boundary=jsonl.stat().st_size, force_flush=True) == IngestResult.OK


def test_ingest_never_reads_past_the_accepted_boundary(engine, tmp_path):
    """council R11: PreCompact nudges a LIVE session. If the transcript grows between the
    nudge and the worker running it, turns nobody nudged must not be ingested — that is
    the consent violation, and parse_transcript has no absolute ceiling of its own."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=4)
    boundary = jsonl.stat().st_size
    _make_jsonl(jsonl, user_turns=12)         # grew AFTER the nudge was accepted
    rel = str(jsonl.relative_to(watch_dir))
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5,
            boundary=boundary, force_flush=True,   # the nudge lane: force-flush + ceiling
        )
    assert state[rel]["end_offset"] <= boundary


# NOTE: the capped-drain case is owned by Task 2 and is implemented there as
# test_a_capped_batch_re_enqueues_the_remainder — do not duplicate it here.


def test_rewind_recovery_honours_the_accepted_boundary(engine, tmp_path, caplog):
    """The ADR-0003 orphan-recovery rewind (re-parse from offset 0) must carry the same
    ceiling as the happy path — otherwise the recovery path becomes the consent leak.
    A genuine legacy mid-response cursor triggers the rewind; the file ALSO has closed
    turns past the accepted boundary that must NOT be re-ingested."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    records = [
        {"type": "user", "message": {"content": "Prompt about the architecture decision"}},
        {"type": "assistant", "message": {"stop_reason": "tool_use",
            "content": [{"type": "text", "text": "First part"}]}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Second part closing the first turn"}]}},
        {"type": "user", "message": {"content": "A LATER prompt appended after the nudge"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": "A later answer nobody nudged"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in records:
            f.write(json.dumps(line) + "\n")
    raw = jsonl.read_bytes().splitlines(keepends=True)
    mid = len(raw[0]) + len(raw[1])            # cursor parked mid-response by an older version
    boundary = mid + len(raw[2])               # accepted EOF = end of the first closed turn
    _mark_idle(jsonl)

    rel = str(jsonl.relative_to(watch_dir))
    state = {rel: {"end_offset": mid, "hash": "stale", "user_turns": 1, "node_ids": []}}

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as mock_llm, \
         caplog.at_level(logging.INFO, logger="ormah.background.session_watcher"):
        r1 = _ingest_session(engine, jsonl, state, watch_dir, 1, boundary=boundary)
    assert r1 == IngestResult.OK
    assert "recovering legacy mid-response cursor" in caplog.text     # the rewind ran
    prompt = str(mock_llm.call_args_list[0])
    assert "Prompt about the architecture decision" in prompt         # re-paired from 0
    assert "A LATER prompt appended after the nudge" not in prompt     # past the ceiling
    assert "A later answer nobody nudged" not in prompt               # never ingested
    assert state[rel]["end_offset"] <= boundary


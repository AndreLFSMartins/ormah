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

from ormah import signal_strength
from ormah.background.session_watcher import (
    MAX_EXTRACT_FAILURES,
    IngestResult,
    SessionHandler,
    _commit_state,
    _frozen_unchanged,
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
from ormah.background import llm_cancel
from ormah.engine.memory_engine import MemoryEngine
from ormah.models.node import CreateNodeRequest
from ormah.transcript.parser import parse_transcript

# NOTE: the module-level llm_cancel epoch is reset around every test by the autouse
# `_clean_llm_cancel_epoch` fixture in tests/conftest.py (this file exercises the REAL
# start_session_watcher/stop_session_watcher, which calls the REAL cancel_active_llm_calls()).

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

# A second, content-distinct extraction result. The engine dedups a memory whose content
# matches one already stored in the SAME store (_is_duplicate_memory), so a test that ingests
# twice against one shared `engine` fixture needs two different memories or the second
# ingest's node_ids comes back empty for a reason unrelated to what it is testing.
_ROTATED_LLM_RESPONSE = json.dumps({"memories": [
    {
        "content": "The rotated transcript records a fresh decision distinct from the original.",
        "type": "decision",
        "title": "Rotated transcript decision",
        "tags": ["rotated"],
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


def _write_orphan_tail_jsonl(path: Path, pairs: int = 6, pad: int = 600) -> None:
    """#154 fixture: `pairs` closed user/assistant pairs, one final closed pair, then a
    TRAILING assistant(end_turn) WITH text and no user after it. Parsed from any cursor
    sitting just before the trailing record it is a leading orphan with no forward
    progress (rewind fires); parsed from 0 the same record CLOSES (safe boundary reaches
    EOF), so the uncapped probe authorises recovery. With flush_chars below the file's
    cleaned length the capped drain then lands BELOW the original cursor — the #154 loop
    trigger."""
    filler = "x" * pad
    lines = []
    for i in range(pairs):
        lines.append({"type": "user",
                      "message": {"role": "user", "content": f"User {i} {filler}"}})
        lines.append({"type": "assistant",
                      "message": {"role": "assistant", "stop_reason": "end_turn",
                                  "content": [{"type": "text", "text": f"Answer {i} {filler}"}]}})
    lines.append({"type": "user", "message": {"role": "user", "content": f"Final ask {filler}"}})
    lines.append({"type": "assistant",
                  "message": {"role": "assistant", "stop_reason": "end_turn",
                              "content": [{"type": "text", "text": f"Final answer {filler}"}]}})
    lines.append({"type": "assistant",
                  "message": {"role": "assistant", "stop_reason": "end_turn",
                              "content": [{"type": "text", "text": f"Trailing orphan {filler}"}]}})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
    _make_jsonl(jsonl, user_turns=12)  # large enough that a small flush_chars caps the first batch
    _mark_idle(jsonl)
    state = {}
    defer_calls: list[int] = []

    result = None
    with patch(_LLM_PATCH, return_value=_UNPARSEABLE), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        for _ in range(MAX_EXTRACT_FAILURES):
            result = _ingest_session(
                engine, jsonl, state, watch_dir, min_turns=1,
                flush_chars=300,  # small -> the first closed batch is capped (content past it)
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
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=1, flush_chars=300)
    assert state[rel]["skipped_slices"], "precondition: first slice quarantined"
    quarantined = list(state[rel]["skipped_slices"])

    # Phase 2: the NEXT batch extracts successfully and writes fresh success state.
    ok = json.dumps({"memories": [{"content": "a genuine memory to store", "type": "fact",
                                   "title": "t"}]})
    with patch(_LLM_PATCH, return_value=ok), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=1, flush_chars=300)

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
    # #218: strength is the judge's band position now, not its raw confidence.
    assert judge_signal["strength"] == pytest.approx(
        signal_strength.judge_strength(0.88, engine.settings.feedback_llm_judge_min_confidence, 1)
    )

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
    # retry until it crosses min_turns, crosses flush_chars, or the session idles.
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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
        _mark_idle(jsonl)  # appended session, below flush_chars → idle flush
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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
    """A file that shrinks below the stored offset is re-ingested from the start, once the
    shrink is confirmed on a second tick (task 4: a single stat() is not durable proof)."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-proj"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "active.jsonl"
    _make_jsonl(jsonl, user_turns=10)
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
        _mark_idle(jsonl)  # shrunk session, below flush_chars → idle flush
        # Tick 1: shrink observed but unconfirmed — marker persisted, no re-ingest yet.
        assert _ingest_session(engine, jsonl, state, watch_dir,
                               min_turns=5) == IngestResult.NO_PROGRESS
        # Tick 2: shrink confirmed — durable reset, full re-ingest.
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
    _mark_idle(jsonl)  # finished-so-far session, below flush_chars → idle flush
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
    _mark_idle(jsonl)  # below flush_chars → idle flush for the closed turns

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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush

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
    _mark_idle(jsonl)  # finished-so-far turn, below flush_chars → idle flush
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
    _mark_idle(jsonl)  # finished session, below flush_chars → idle flush
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
    first_nodes = list(state[rel]["node_ids"])
    assert first_nodes  # first ingest produced at least one node

    _make_jsonl(jsonl, user_turns=5)  # smaller file → size < stored end_offset → full re-ingest
    _mark_idle(jsonl)  # shrunk session, below flush_chars → idle flush
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # Tick 1: shrink observed but not yet confirmed — marker persisted, no re-ingest.
        assert _ingest_session(engine, jsonl, state, watch_dir,
                               min_turns=5) == IngestResult.NO_PROGRESS
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # Tick 2: shrink confirmed — durable reset, full re-ingest.
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


def test_large_orphan_beyond_flush_chars_does_not_rewind(engine, tmp_path, caplog):
    """Beta byte-cap path (council R2): an orphan larger than flush_chars must not make
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
            r = _ingest_session(engine, jsonl, state, watch_dir, 1, flush_chars=8000)
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
    """The drain must finish a boundary larger than flush_chars on its own, across several
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
    engine.settings.session_watcher_flush_chars = 400        # force several capped batches
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
    _mark_idle(primary)  # finished session, below flush_chars → idle flush
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
    _mark_idle(recent)  # finished session, below flush_chars → idle flush

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


def test_reconcile_selects_marked_file_whose_cursor_is_above_eof(engine, tmp_path):
    """Task 4 / trap 3: between tick 1 and tick 2 the durable cursor is still above EOF —
    the reset has not committed yet. The fully-consumed skip predicate must not drop a
    shrink_pending entry from the sweep, or tick 2 never arrives and the marker becomes
    the very stranding bug it exists to avoid."""
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
    full_size = jsonl.stat().st_size
    assert handler._state[rel]["end_offset"] == full_size

    # Shrink the file and drive tick 1 through the real live path: installs the marker
    # without touching end_offset, which now sits ABOVE the shrunk file's EOF.
    _make_jsonl(jsonl, user_turns=2)
    _mark_idle(jsonl)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
    assert handler._state[rel]["shrink_pending"]
    assert handler._state[rel]["end_offset"] == full_size   # still above the shrunk EOF

    # The naive predicate (`end_offset >= size` alone) would now call this file fully
    # consumed and skip it forever. It must still be selected as a candidate.
    assert handler.reconcile() == 1


def test_shrink_tick_one_requeues_without_reconcile(engine, tmp_path):
    """Task 4 review follow-up (Change 1): an acceptance-only root has discover=False and
    is NEVER swept by reconcile (session_watcher.py: discover on SessionWatch, and
    run_session_reconcile's `if w.discover`). If tick 1 `complete`d its job, a transcript
    whose last-ever nudge happened to land on the shrink would strand its marker (and its
    cursor above EOF) forever. Tick 1 must instead requeue via the spool's own backoff, so
    a second observation is reachable through the spool ALONE -- no reconcile call
    anywhere in this test."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-test-space"
    proj.mkdir(parents=True)
    jsonl = proj / "shrunk.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
    assert handler._state[rel]["end_offset"] == jsonl.stat().st_size

    _make_jsonl(jsonl, user_turns=2)   # shrink below the stored cursor
    _mark_idle(jsonl)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)  # tick 1 only: a backed-off job is left pending, not reclaimed
    assert handler._state[rel]["shrink_pending"]
    # The job must be requeued (pending, backed off) -- NOT completed, NOT dead-lettered.
    assert handler.spool.pending_count() == 1
    failed_dir = handler.spool.root / "failed"
    assert not any(p.name.endswith(".json") for p in failed_dir.iterdir())


def test_confirmed_shrink_clears_the_frozen_fact_through_the_producer(engine, tmp_path):
    """A rotated file reuses its path at a smaller size. The frozen fact left over from the
    PREVIOUS file must not survive the confirmed reset, and the whole route must run through
    a real producer: council round 1 rejected a version of this test that called
    spool.enqueue directly, because that is exactly the gate the defect lived in."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # 1. a normal ingest: the entry gets a real cursor
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        cursor = handler._state[rel]["end_offset"]
        assert cursor > 0

        # 2. an unterminated turn is appended and the session dies -> the file freezes
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user", "message": {"content": "a prompt that never got its answer"},
            }) + "\n")
        _mark_idle(jsonl)
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] > cursor

        # 3. the path is rotated to a NEW, smaller file
        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=2)
        assert jsonl.stat().st_size < cursor
        _mark_idle(jsonl)

        # 4. tick 1 through the producer: the rotated file is not the file the freeze
        #    examined, so _frozen_unchanged is false and the Observer must still enqueue.
        #    (Its cursor-above-EOF escape returns false here too, but the ceiling conjunct
        #    already differs -- the escape is defence-in-depth, not the operative reason.)
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, "the shrink escape must reach the spool"
        _drain_all(handler)
        assert handler._state[rel]["shrink_pending"], "tick 1 must arm the marker"
        assert "frozen_until" in handler._state[rel], "tick 1 does not reset anything yet"

        # 5. tick 2 is the SAME job, returned to pending/ with a persisted backoff. Advancing
        #    the spool's clock is what makes it due; enqueueing again would be a no-op on the
        #    same (path, boundary) key and _drain_all would find nothing due.
        #
        #    This tick's extraction is made to fail (provider outage) ON PURPOSE. Measured: a
        #    successful re-ingest immediately following the reset, in the SAME tick, always
        #    rebuilds the entry from an empty dict regardless of the fix -- the reset zeroes
        #    end_offset, so `carry = existing and prev_offset > 0` is false right after ANY
        #    reset, which erases a stale frozen_until whether or not the reset commit itself
        #    ever carried it forward. A version of this test that let tick 2 succeed passed
        #    with BOTH fix sites reverted, proving nothing about the reset commit. Failing
        #    the extraction keeps the reset's own commit as the LAST write this tick, so what
        #    follows is actually checking the reset site, not the happy-path site.
        with patch("ormah.background.ingest_spool.time.time",
                   return_value=time.time() + 3600), \
             patch(_LLM_PATCH, return_value=None):
            _drain_all(handler)

    reset_entry = handler._state[rel]
    assert "shrink_pending" not in reset_entry, "tick 2 must have actually run and confirmed"
    assert "frozen_until" not in reset_entry, \
        "a confirmed shrink must drop the stale ceiling with the stale cursor"
    assert "frozen_ino" not in reset_entry and "frozen_mtime_ns" not in reset_entry
    assert "frozen_ctime_ns" not in reset_entry

    # 6. the provider recovers on a later tick, past tick 2's own backoff: the rotated file's
    #    real content still reaches the store -- the reset dropped the stale FACT, not the
    #    file. A response distinct from step 1's avoids _is_duplicate_memory silently
    #    skipping an identical memory already stored by step 1 in this same engine.
    with patch("ormah.background.ingest_spool.time.time",
               return_value=time.time() + 7200), \
         patch(_LLM_PATCH, return_value=_ROTATED_LLM_RESPONSE):
        _drain_all(handler)

    entry = handler._state[rel]
    assert entry.get("node_ids"), "the rotated file's content must reach the store"
    assert "frozen_until" not in entry
    assert "frozen_ino" not in entry and "frozen_mtime_ns" not in entry
    assert "frozen_ctime_ns" not in entry


def test_successful_ingest_clears_the_frozen_fact(engine, tmp_path):
    """Council round 1, cursor, medium: the happy-path commit carries the whole existing
    entry forward, so a frozen fact would outlive the freeze it described and could only
    mislead a later comparison.

    The freeze must land on an entry that ALREADY has a real cursor (`end_offset > 0`):
    freezing a file's very first-ever examination leaves nothing to carry, so
    `carry = existing and prev_offset > 0` stays false and the happy-path commit rebuilds
    the entry from an empty dict regardless of the fix -- proving nothing. Measured: a
    version of this test that froze on a brand-new unterminated file (never ingested
    before) passed even with the fix reverted."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "thaws.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        # 1. a normal ingest: the entry gets a real cursor to carry forward
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        cursor = handler._state[rel]["end_offset"]
        assert cursor > 0

        # 2. an unterminated turn is appended and the session dies -> the file freezes
        #    WITHOUT moving the cursor (ADR-0004): end_offset stays at `cursor`.
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user", "message": {"content": "a prompt that never got its answer"},
            }) + "\n")
        _mark_idle(jsonl)
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] > cursor
        assert handler._state[rel]["end_offset"] == cursor

        # 3. the session comes back and closes the turn: the next parse ingests it
        #    INCREMENTALLY from `cursor` (prev_offset > 0), so carry is true this time and
        #    the happy-path commit under test actually runs. A response distinct from step
        #    1's avoids _is_duplicate_memory silently skipping an identical memory already
        #    stored by step 1 in this same engine.
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": "and a closing answer"}]},
            }) + "\n")
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_ROTATED_LLM_RESPONSE):
            handler._enqueue_path(jsonl, "observer")
            _drain_all(handler)

    entry = handler._state[rel]
    assert entry.get("node_ids"), "the content must have been ingested"
    assert "frozen_until" not in entry, "a successful ingest un-freezes the file"
    assert "frozen_ino" not in entry and "frozen_mtime_ns" not in entry
    assert "frozen_ctime_ns" not in entry


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


def test_reconcile_skips_a_frozen_file_until_it_changes(engine, tmp_path):
    """The cursor no longer drops a frozen file from the sweep — the frozen identity does.
    Growth past the recorded ceiling re-opens it, with the parse resuming from the
    UNTOUCHED cursor rather than wherever a ratchet would have left it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "frozen.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert handler.reconcile() == 1        # first sweep: never seen -> enqueued
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] == size
        assert handler.reconcile() == 0, "an unchanged frozen file must be skipped"

        # the session resumes and closes its turn: the file grows past the ceiling
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        _mark_idle(jsonl)
        assert handler.reconcile() == 1, "growth must re-open the file"


def test_reconcile_reopens_a_frozen_file_that_was_rotated_smaller(engine, tmp_path):
    """Council round 1, critical (cursor + codex, verified): a ceiling-only gate
    (frozen_until >= size) also skips a file that SHRANK, so a rotated transcript is
    suppressed forever and no producer can ever arm the shrink reset. Any change to the
    file's identity must re-select it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    # A single unterminated turn, padded well past what a 6-turn complete conversation
    # takes -- `_partial_unterminated`'s own ~220 bytes is smaller than ANY _make_jsonl
    # output, which would make "rotated smaller" unreachable with these helpers combined.
    padding = "x" * 4000
    jsonl.write_text(
        json.dumps({"type": "user", "message": {"content": f"a long prompt {padding}"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": f"an answer that never closed {padding}"}]}})
        + "\n"
    )
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)
        frozen = handler._state[rel]["frozen_until"]
        assert handler.reconcile() == 0

        # rotated: same path, a NEW smaller file with a complete conversation
        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=6)
        assert jsonl.stat().st_size < frozen
        _mark_idle(jsonl)

        assert handler.reconcile() == 1, \
            "a rotated file must be re-selected, not hidden behind the old ceiling"
        _drain_all(handler)

    assert handler._state[rel].get("node_ids"), "the rotated file's content must be ingested"


def test_reconcile_reopens_a_frozen_file_replaced_at_the_same_size(engine, tmp_path):
    """A replacement of exactly the same byte count is invisible to a size comparison. The
    Observer lane catches it today because it consults no state at all, so a size-only gate
    would be a regression. Identity (inode/mtime) is what makes it visible."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)
        original = jsonl.read_bytes()
        assert handler.reconcile() == 0

        # a NEW file at the same path with the SAME byte count
        replacement = proj / "tmp.jsonl"
        replacement.write_bytes(original)
        replacement.replace(jsonl)
        assert jsonl.stat().st_size == len(original)
        _mark_idle(jsonl)

        stale_ino = handler._state[rel]["frozen_ino"]
        assert stale_ino != jsonl.stat().st_ino, \
            "the replacement must carry a different inode — otherwise this fixture proves nothing"
        assert handler.reconcile() == 1, \
            "a same-size replacement is a different file and must be re-selected"

        # Council round 2, cursor, medium: stopping at the first re-open would ship a park
        # that never refreshes identity. Suppression must RE-ARM on the new file, or every
        # sweep re-selects and re-dead-letters it forever.
        _drain_all(handler)
        assert handler._state[rel]["frozen_ino"] == jsonl.stat().st_ino, \
            "the re-park must converge identity onto the replacement"
        assert handler.reconcile() == 0, "suppression must re-arm on the new identity"


def test_reconcile_still_selects_a_never_seen_file_with_only_a_frozen_fact(engine, tmp_path):
    """A file whose FIRST examination froze has an entry with no end_offset at all. The
    cheap-skip arm evaluates (entry.get('end_offset') or 0) >= size -> 0 >= size is false,
    so it must fall through to the frozen gate and be judged there."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "firstfreeze.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler.reconcile()
        _drain_all(handler)

    assert "end_offset" not in handler._state[rel], \
        "the freeze must not create a cursor for a file that was never ingested"
    assert handler._state[rel]["frozen_until"] == jsonl.stat().st_size
    assert handler.reconcile() == 0


def test_idle_file_with_no_safe_boundary_completes_without_dead_letter(engine, tmp_path):
    """ADR-0004 Fix A: an idle transcript whose bytes never reach a safe boundary (a single
    unterminated turn) parks the suppression fact and completes the job — it must NOT
    dead-letter. Fix B's frozen_until fact already prevents the hot re-enqueue loop and
    already ensures reprocessing on growth, so recording this as a spool-level failure was
    pure noise (superseded T-N3)."""
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

    assert not list((spool.root / "failed").glob("*.json")), \
        "a parked idle file must complete, not dead-letter (ADR-0004 Fix A)"
    assert spool.pending_count() == 0
    assert not any(p.name.endswith(".json") for p in (spool.root / "running").iterdir())
    rel = str(jsonl.relative_to(watch_dir))
    assert handler._state[rel]["frozen_until"] == jsonl.stat().st_size


def test_mark_frozen_prefix_parked_returns_parked_on_fresh_write(engine, tmp_path):
    """ADR-0004 Fix A (council R1/R2): the call site now dispatches on this return value, so
    its contract is pinned directly. A fresh, successful write returns PARKED."""
    from ormah.background.session_watcher import ParkOutcome

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "fresh.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    st = jsonl.stat()
    outcome = handler._mark_frozen_prefix_parked(jsonl, rel, st.st_size, examined=st)
    assert outcome is ParkOutcome.PARKED
    assert handler._state[rel]["frozen_until"] == st.st_size


def test_mark_frozen_prefix_parked_returns_parked_when_already_identically_recorded(engine, tmp_path):
    from ormah.background.session_watcher import ParkOutcome

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "twice.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    st = jsonl.stat()
    assert handler._mark_frozen_prefix_parked(
        jsonl, rel, st.st_size, examined=st
    ) is ParkOutcome.PARKED
    # Second call, same unchanged file, same examined stat: the no-op short-circuit
    # (session_watcher.py:1694-1700) still means a durable fact exists — still PARKED.
    assert handler._mark_frozen_prefix_parked(
        jsonl, rel, st.st_size, examined=st
    ) is ParkOutcome.PARKED


def test_mark_frozen_prefix_parked_rewrites_the_fact_after_external_state_loss(engine, tmp_path):
    """council-pr R1 (codex): the no-write "already recorded" short-circuit returned PARKED
    from self._state alone, which is loaded once at construction and never re-read. If the
    state file is destroyed or rolled back externally while the handler lives, that PARKED
    let the caller complete() the job with NO durable fact anywhere.

    On the evidence, precisely: what ADR-0004 measured being externally destroyed twice
    (2026-08-11, 2026-08-13) was ingest_queue/ -- the SPOOL -- not .session_watcher_state.
    So external destruction of ormah's own on-disk state is observed behaviour of this
    deployment, but destruction of THIS file specifically is inferred, not measured. The
    defect does not rest on that inference either way: self._state outliving its file is
    reachable from any cause (rollback, restore from backup, a stale concurrent writer),
    and the fix costs one write.

    PARKED must now mean the fact is on disk, so a park after external state loss must
    RE-WRITE it, not trust memory."""
    from ormah.background.session_watcher import ParkOutcome, _STATE_FILENAME

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "stateloss.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    st = jsonl.stat()

    assert handler._mark_frozen_prefix_parked(
        jsonl, rel, st.st_size, examined=st
    ) is ParkOutcome.PARKED
    state_file = watch_dir / _STATE_FILENAME
    assert state_file.exists()

    # External destruction of the state file, handler (and its in-memory _state) still alive.
    state_file.unlink()
    assert handler._state[rel]["frozen_until"] == st.st_size   # memory still claims the fact

    # A second, identical park must not trust memory: it must re-persist the fact.
    assert handler._mark_frozen_prefix_parked(
        jsonl, rel, st.st_size, examined=st
    ) is ParkOutcome.PARKED
    assert state_file.exists(), \
        "PARKED must mean the fact is on disk — memory alone is not durability"
    on_disk = json.loads(state_file.read_text())
    assert on_disk[rel]["frozen_until"] == st.st_size


def test_mark_frozen_prefix_parked_returns_gone_when_file_deleted(engine, tmp_path):
    """The race R1 found: deleted between _idle_with_unsafe_tail's examination and this
    re-stat. FileNotFoundError specifically -> GONE, distinct from a transient OSError, and
    no fact written."""
    from ormah.background.session_watcher import ParkOutcome

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "deleted.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    st = jsonl.stat()
    jsonl.unlink()
    outcome = handler._mark_frozen_prefix_parked(jsonl, rel, st.st_size, examined=st)
    assert outcome is ParkOutcome.GONE
    assert "frozen_until" not in handler._state.get(rel, {})


def test_mark_frozen_prefix_parked_returns_retry_when_changed_under_examination(engine, tmp_path):
    """The other race R1 found: the file grows (or is replaced) between the examination and
    this re-stat. examined no longer matches reality -- RETRY (still exists, just not the
    file that was parsed), not GONE, and no fact written."""
    from ormah.background.session_watcher import ParkOutcome

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "changed.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    stale_st = jsonl.stat()
    with jsonl.open("a") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": "more"}}) + "\n")
    outcome = handler._mark_frozen_prefix_parked(
        jsonl, rel, stale_st.st_size, examined=stale_st
    )
    assert outcome is ParkOutcome.RETRY
    assert "frozen_until" not in handler._state.get(rel, {})


def test_mark_frozen_prefix_parked_returns_retry_on_transient_stat_error(engine, tmp_path, monkeypatch):
    """Council R2 (codex): a transient stat() failure (e.g. EACCES from a permissions race,
    not deletion) must be distinguishable from GONE -- it is RETRY, so the job gets a
    persisted-backoff retry rather than a deterministic transcript_deleted dead-letter for a
    file that never actually vanished."""
    from pathlib import Path
    from ormah.background.session_watcher import ParkOutcome

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "transient.jsonl"
    _partial_unterminated(jsonl)
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999)
    rel = str(jsonl.relative_to(watch_dir))
    st = jsonl.stat()

    real_stat = Path.stat

    def _flaky_stat(self, *a, **kw):
        if self == jsonl:
            raise PermissionError("simulated transient EACCES")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", _flaky_stat)
    outcome = handler._mark_frozen_prefix_parked(jsonl, rel, st.st_size, examined=st)
    assert outcome is ParkOutcome.RETRY
    assert "frozen_until" not in handler._state.get(rel, {})


def test_frozen_prefix_advance_never_passes_the_accepted_boundary(engine, tmp_path):
    """council-pr F1, carried onto the suppression fact: a nudge accepted boundary B; the
    live file then grew to S>B, still an unterminated single turn, and went idle. The
    freeze must record B, NEVER raw EOF S -- bytes [B,S] were never accepted, so a later
    nudge at S must still be able to re-examine them."""
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

    entry = _load_state(watch_dir).get(rel, {})
    assert (entry.get("end_offset") or 0) == 0, "the freeze must not move the cursor at all"
    assert entry.get("frozen_until") == boundary, (
        f"the freeze recorded {entry.get('frozen_until')} (S={size}); it must never pass "
        f"the accepted boundary B={boundary}, or bytes [B,S] are suppressed forever"
    )
    # [B,S] was not permanently consumed: a second nudge at S can still claim it for work.
    spool.enqueue(jsonl, boundary=size, reason="nudge")
    assert spool.claim_next() is not None, "the second nudge at S must be claimable"


def test_frozen_prefix_does_not_consume_bytes_the_next_job_can_ingest(engine, tmp_path):
    """ADR-0004 2026-08-12 — the ratchet. A job whose accepted boundary cuts the first
    assistant record in half closes nothing, so the frozen-prefix path fires. It must NOT
    advance the cursor: a second job at the file's real EOF has to ingest the WHOLE
    transcript. With the cursor advanced (the pre-fix behaviour) the second job resumes
    mid-record and the content is unreachable — that happened 24 times in a row on one
    production transcript, boundary climbing 98,985 -> 1,435,339, nothing ever ingested."""
    from ormah.background.ingest_spool import IngestSpool

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "ratchet.jsonl"
    _make_jsonl(jsonl, user_turns=6)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    # A boundary strictly INSIDE the first assistant record: the parser reads that line
    # (its start is below the ceiling) and _exceeds_ceiling refuses it at commit, so
    # safe_end_offset == start_offset == 0 and _idle_with_unsafe_tail is True.
    first_line = jsonl.read_bytes().split(b"\n")[0]
    boundary = len(first_line) + 1 + 10
    assert boundary < size

    spool = IngestSpool(tmp_path / "spool")
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 30.0, 9999, spool=spool)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        spool.enqueue(jsonl, boundary=boundary, reason="observer", force_flush=False)
        _drain_all(handler)

        entry = handler._state.get(rel, {})
        assert entry.get("frozen_until") == boundary, \
            "the freeze must be recorded as a suppression fact"
        assert (entry.get("end_offset") or 0) == 0, \
            "the freeze must NOT move the cursor over bytes nothing ingested"

        spool.enqueue(jsonl, boundary=size, reason="reconcile", force_flush=False)
        _drain_all(handler)

    entry = handler._state[rel]
    assert entry["end_offset"] == size, \
        "the second job, at the real EOF, must ingest the whole transcript"
    assert entry.get("node_ids"), "the content must have reached the store"


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


def test_frozen_prefix_park_is_monotonic(engine, tmp_path):
    """council-pr R2 F2: the park's CEILING must be monotonic. A stale or out-of-order job
    carrying a boundary lower than the current ``frozen_until`` must NEVER lower it -- that
    would re-open the ratchet this method exists to stop. The park never touches the cursor
    (``end_offset``) at all, in either direction, and the refused, stale boundary must never
    be persisted to disk either."""
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

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=3000, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == 3000
    assert handler._state[rel]["end_offset"] == 4000, "the park must not touch the cursor"

    handler._mark_frozen_prefix_parked(     # stale, LOWER boundary
        jsonl, rel, boundary=1000, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == 3000, (
        "a boundary below the current ceiling must never lower it (re-opens the ratchet)"
    )
    assert _load_state(watch_dir).get(rel, {}).get("frozen_until") == 3000, (
        "the stale boundary must not be persisted to disk either"
    )
    assert _load_state(watch_dir).get(rel, {}).get("end_offset") == 4000


def test_park_refuses_a_file_that_changed_under_the_examination(engine, tmp_path):
    """Council round 2, codex, high. The park stats the file AFTER the examination. A
    rotation landing in between would record the REPLACEMENT's identity, and both producers
    would then treat a file nobody has ever parsed as frozen-and-unchanged. Writing no fact
    is always safe: the file is simply re-selected."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "raced.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    examined = jsonl.stat()

    # the path is replaced between the examination and the park
    jsonl.unlink()
    _make_jsonl(jsonl, user_turns=2)

    handler._mark_frozen_prefix_parked(
        jsonl, rel, boundary=jsonl.stat().st_size, examined=examined)
    assert "frozen_until" not in handler._state.get(rel, {}), \
        "a file that changed under the examination must never be parked"


def test_park_converges_identity_when_the_ceiling_does_not_rise(engine, tmp_path):
    """Council round 2, cursor, high. After a same-size replacement the producers correctly
    re-open (identity differs). The re-park lands on the SAME ceiling; if it returned early
    the stale identity would stay forever and every sweep would re-select and re-dead-letter
    the file — an unbounded failed/, the failure mode ADR-0004 exists to avoid."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    size = jsonl.stat().st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=size, examined=jsonl.stat())
    first_ino = handler._state[rel]["frozen_ino"]

    # a NEW file at the same path with the SAME byte count
    original = jsonl.read_bytes()
    replacement = proj / "tmp.jsonl"
    replacement.write_bytes(original)
    replacement.replace(jsonl)
    _mark_idle(jsonl)
    assert jsonl.stat().st_size == size

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=size, examined=jsonl.stat())
    entry = handler._state[rel]
    assert entry["frozen_until"] == size, "the ceiling must not move"
    assert entry["frozen_ino"] != first_ino, \
        "identity must converge even when the ceiling does not rise"
    assert entry["frozen_ino"] == jsonl.stat().st_ino


def test_park_ceiling_is_monotonic_only_within_one_identity(engine, tmp_path):
    """Council round 3, both peers, the only finding of that round. A ceiling belonging to
    a different file is not a ratchet guard, it is a lie: file A frozen at a large size,
    replaced by a SMALLER file that is also unparseable, would keep A's ceiling, and
    `frozen_until == st_size` could never be true again — every sweep re-selecting and
    re-dead-lettering, an unbounded failed/."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "shrinking.jsonl"
    proj_big = "x" * 4000
    jsonl.write_text(
        json.dumps({"type": "user", "message": {"content": f"a long prompt {proj_big}"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": f"an answer that never closed {proj_big}"}]}})
        + "\n"
    )
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    big = jsonl.stat().st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=big, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == big
    first_ino = handler._state[rel]["frozen_ino"]

    # replaced by a SMALLER file that is also unparseable
    jsonl.unlink()
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    small = jsonl.stat().st_size
    assert small < big
    assert jsonl.stat().st_ino != first_ino, \
        "the replacement must carry a different inode — otherwise this fixture proves nothing"

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=small, examined=jsonl.stat())
    assert handler._state[rel]["frozen_until"] == small, (
        "a ceiling from a different file must be replaced, not maxed — otherwise the "
        "predicate can never re-arm and the file re-selects forever"
    )
    assert _frozen_unchanged(handler._state[rel], jsonl.stat()), \
        "suppression must re-arm on the new file"


def test_park_ceiling_does_not_survive_an_mtime_preserving_shrink(engine, tmp_path):
    """council-pr round 1, codex. The identity above is (inode, mtime_ns) and omits the SIZE,
    so the round-3 repair has a hole its own test cannot reach: that test replaces the file
    (`unlink` + recreate), which changes the inode. An in-place `truncate` does NOT — it
    keeps the inode — and a writer that restores the timestamp (utime, rsync --times, an
    editor preserving mtime) keeps `st_mtime_ns` too. The park then calls a 500-byte file the
    same file as the 4000-byte one it froze and keeps the LARGER ceiling, so
    `frozen_until == st_size` can never hold again and every sweep re-selects and
    re-dead-letters it — the unbounded failed/ this fact exists to prevent.

    The guard is on the ceiling itself: a ceiling above the current size cannot belong to
    this file, whatever the inode and mtime say."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "truncated-in-place.jsonl"
    filler = "x" * 4000
    jsonl.write_text(
        json.dumps({"type": "user", "message": {"content": f"a long prompt {filler}"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": f"an answer that never closed {filler}"}]}})
        + "\n"
    )
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    before = jsonl.stat()
    big = before.st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=big, examined=before)
    assert handler._state[rel]["frozen_until"] == big

    # truncated IN PLACE -- same inode -- with the mtime restored to the nanosecond
    with open(jsonl, "r+b") as fh:
        fh.truncate(500)
    os.utime(jsonl, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = jsonl.stat()
    small = after.st_size
    assert small < big
    assert after.st_ino == before.st_ino, \
        "fixture invalid: the inode changed, so this is a replacement and not an in-place edit"
    assert after.st_mtime_ns == before.st_mtime_ns, \
        "fixture invalid: the mtime was not restored, so the identity already differs"

    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=small, examined=after)
    assert handler._state[rel]["frozen_until"] == small, (
        "a ceiling above the file's own size is not a ratchet guard, it is a lie -- the "
        "park must replace it, not max against it"
    )
    assert _frozen_unchanged(handler._state[rel], jsonl.stat()), \
        "suppression must re-arm after an in-place shrink, or the file re-selects forever"


def test_frozen_identity_sees_an_in_place_rewrite_that_restored_its_mtime(engine, tmp_path):
    """council-pr round 2, codex, high. (size, inode, mtime_ns) is not byte identity: an
    in-place rewrite of the SAME length keeps the inode and size, and utime (or rsync
    --times, or an editor preserving timestamps) puts mtime_ns back. Both producers share
    this predicate, so newly closed turns would be suppressed forever.

    st_ctime_ns closes it: the kernel bumps it on any inode change and userspace has no way
    to set it, so it survives exactly the tampering mtime does not. Measured on this
    filesystem for both shapes codex named — a same-size rewrite, and a shrink followed by a
    regrow back to the original size — ctime differs in both while ino/size/mtime match.

    Upstream documents the same hole and accepts it, on the grounds that closing it means
    hashing every consumed file each tick. That is a false choice: this costs one more
    stat field."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rewritten-in-place.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    before = jsonl.stat()
    size = before.st_size
    handler._mark_frozen_prefix_parked(jsonl, rel, boundary=size, examined=before)
    assert _frozen_unchanged(handler._state[rel], jsonl.stat()), \
        "the freeze must suppress the file it actually examined"

    # rewritten IN PLACE at the SAME length, with the mtime put back to the nanosecond
    original = jsonl.read_bytes()
    with open(jsonl, "r+b") as fh:
        fh.seek(0)
        fh.write(bytes(b ^ 0x20 if b not in b'\r\n' else b for b in original))
    os.utime(jsonl, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = jsonl.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns
    ), "fixture invalid: this must be invisible to (inode, size, mtime) or it proves nothing"
    assert jsonl.read_bytes() != original, "fixture invalid: the bytes did not actually change"

    assert not _frozen_unchanged(handler._state[rel], after), (
        "the bytes changed under a restored mtime — suppressing this file strands every "
        "turn the rewrite closed"
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
    handler.flush_chars = 300      # small -> the first closed batch caps (content past it)
    spool = handler.spool

    obs_file = proj / "obs.jsonl"
    _make_jsonl(obs_file, user_turns=12)       # large -> flush_chars=300 caps the first batch
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

def test_normal_shutdown_drain_does_not_cancel_llm_calls_itself(monkeypatch):
    """Locks the ordering contract: on the normal-shutdown path (`rearm=False`, the default),
    `_stop_and_drain` must NOT call `cancel_active_llm_calls` itself -- the lifespan's shutdown
    `finally` already issued the ONE final cancel before `stop_session_watcher` ->
    `_stop_and_drain` is even entered (see the ordering note in `_stop_and_drain`'s docstring).
    ADR-0004 slice 2 redesign: HIGH-C (council R2, Codex) used to be solved by a re-cancel loop
    inside `_stop_and_drain` (cancel; join; cancel; join; ... until drain_alive() reports dead);
    that loop is now REMOVED in favour of a single globally-read epoch (`llm_cancel`), so this
    test's only mutation-sensitive assertion is `cancel_calls["n"] == 0`.

    The companion property -- that a "late" adapter (one whose call is already in flight,
    polling the epoch, when the ONE upstream cancel lands) still reads the cancelled epoch at
    `generate()` entry and is cancelled without anyone re-cancelling -- is NOT this test's job;
    it is owned and locked by
    `tests/test_background/test_llm_client.py::test_an_adapter_built_during_a_shutdown_is_born_cancelled`.
    This test still drives a fake "late" thread through the same epoch-read shape purely so the
    join fence has something real to wait on and so the bound (`elapsed < 5.0`) is exercised, but
    that thread's own correctness is a secondary, deadlined check here -- not the property under
    test.

    This test reproduces the ordering directly against the real `llm_cancel` module (reset by
    the autouse `_clean_llm_cancel_epoch` fixture) and proves the bound holds via a `Barrier`,
    never `sleep`, to synchronise the "late" thread's start with the join fence. The thread's
    internal poll loop is DEADLINED (not `while True: sleep`) and records its own failure via a
    `finally`, so a mutation that breaks the epoch-cancel wiring (e.g. deleting the
    `begin_cancel(final=True)` call below) makes this test FAIL FAST with a readable message
    instead of hanging forever -- `dead` must always be set so the production
    `while any(drain_alive())` loop in `_stop_and_drain` always has an exit."""
    from ormah.background.session_watcher import SessionWatch, _stop_and_drain

    cancel_calls = {"n": 0}

    def _counting_cancel(*, final=True):
        cancel_calls["n"] += 1
        return 0

    monkeypatch.setattr(
        "ormah.background.session_watcher.cancel_active_llm_calls", _counting_cancel
    )
    monkeypatch.setattr("ormah.background.session_watcher.resume_llm_adapters", lambda: None)
    monkeypatch.setattr("ormah.background.session_watcher._drain_handlers", lambda handlers: None)

    gen, _ = llm_cancel.snapshot()
    building = threading.Barrier(2)
    dead = threading.Event()
    # Bounded poll deadline for the "late" thread below -- NOT the production bound under test
    # (that's `elapsed < 5.0`), just a ceiling so a broken epoch never hangs this test.
    poll_deadline_seconds = 2.0
    thread_failure: dict[str, BaseException] = {}

    class _FakeHandler:
        def __init__(self):
            self._stop_event = threading.Event()

        def cancel_pending_timers(self):
            pass

        def wake(self):
            pass

        def drain_alive(self):
            return not dead.is_set()

        def join_drain(self, timeout=None):
            time.sleep(min(timeout or 0, 0.05))

    def _late_built_adapter():
        # Mirrors the facade's real generate()-entry check (llm_client._guarded_generate):
        # reads the CURRENT global epoch, not one captured when the adapter/thread was built.
        try:
            building.wait(timeout=5)
            deadline = time.monotonic() + poll_deadline_seconds
            while not llm_cancel.epoch_changed(gen):
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        "the late-built adapter never observed the cancelled epoch within "
                        f"{poll_deadline_seconds}s -- the epoch-cancel wiring is broken"
                    )
                time.sleep(0.005)
        except BaseException as e:  # noqa: BLE001 -- includes BrokenBarrierError
            thread_failure["error"] = e
        finally:
            # ALWAYS set, success or failure, so the production `while any(drain_alive())`
            # loop in `_stop_and_drain` can never spin forever on this fake.
            dead.set()

    handler = _FakeHandler()
    watch = SessionWatch(watch_dir=Path("/tmp/late-adapter"), handler=handler, observer=None,
                          spool=None, discover=False)

    t = threading.Thread(target=_late_built_adapter)
    t.start()
    building.wait(timeout=5)  # the "late" adapter is alive and polling the epoch now

    # The lifespan-style cancel: ONE call, made BEFORE _stop_and_drain is entered -- exactly the
    # ordering main.lifespan's shutdown finally guarantees ahead of stop_session_watcher().
    llm_cancel.begin_cancel(final=True)

    start = time.monotonic()
    _stop_and_drain([watch])
    elapsed = time.monotonic() - start
    t.join(5)

    if "error" in thread_failure:
        raise AssertionError(
            "the late-built adapter thread failed: "
            f"{thread_failure['error']!r}"
        ) from thread_failure["error"]

    assert elapsed < 5.0, "the join fence must be bounded by the epoch read, not by re-cancelling"
    assert not handler.drain_alive(), "the late-built adapter must have observed the cancel"
    assert cancel_calls["n"] == 0, (
        "the normal-shutdown path (rearm=False) must not call cancel_active_llm_calls itself -- "
        "the lifespan's finally already did, and re-cancelling here would just be the removed "
        "HIGH-C loop in disguise"
    )


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
    the failure), so leaving the world cancelled would poison every later maintenance/ingest LLM
    call until restart. A normal shutdown must NEVER do this (rearm=False by default).

    ADR-0004 slice 2: cancellation is the module-level llm_cancel epoch now, not a per-adapter
    flag the facade toggles — the fake adapter below is deliberately dumb (it always succeeds);
    the FACADE's _guarded_generate is what rejects a call made while the epoch is cancelled."""
    from ormah.background import llm_client

    class _FakeAdapter:
        def generate(self, *a, **k):
            return "ok"

    monkeypatch.setattr(llm_client, "_cached_adapter", _FakeAdapter())
    monkeypatch.setattr(llm_client, "_adapter_initialised", True)
    llm_cancel.begin_cancel(final=False)  # seed: a call already cancelled before the rollback runs
    assert llm_cancel.snapshot()[1] is True

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

    try:
        with patch("ormah.background.session_watcher.Observer", _FailingObserver):
            with pytest.raises(RuntimeError):
                start_session_watcher(engine)

        assert llm_cancel.snapshot()[1] is False, \
            "the world must be RE-ARMED after a rollback (HIGH-A)"
        assert llm_client.llm_generate(engine.settings, "prompt") == "ok"
    finally:
        llm_cancel.begin_lifespan()


def test_startup_rollback_rearms_even_when_observer_join_raises(engine, tmp_path, monkeypatch):
    """HIGH-3 (council-pr, Codex): the HIGH-B fix assigns watch.observer BEFORE observer.start(),
    so a provisional Observer whose start() raised is a NEVER-STARTED thread; its join() raises
    RuntimeError('cannot join thread before it is started'). That exception must NOT escape
    _stop_and_drain and skip resume_llm_adapters() on the rollback path — otherwise main.lifespan
    keeps serving with the world permanently cancelled (ingest AND maintenance dead until restart).

    ADR-0004 slice 2: cancellation is the module-level llm_cancel epoch now, not a per-adapter
    flag the facade toggles — the fake adapter below is deliberately dumb (it always succeeds);
    the FACADE's _guarded_generate is what rejects a call made while the epoch is cancelled."""
    from ormah.background import llm_client

    class _FakeAdapter:
        def generate(self, *a, **k):
            return "ok"

    monkeypatch.setattr(llm_client, "_cached_adapter", _FakeAdapter())
    monkeypatch.setattr(llm_client, "_adapter_initialised", True)
    llm_cancel.begin_cancel(final=False)  # seed: cancelled before the rollback runs
    assert llm_cancel.snapshot()[1] is True

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

    try:
        with patch("ormah.background.session_watcher.Observer", _JoinRaisingObserver):
            with pytest.raises(RuntimeError):
                start_session_watcher(engine)

        assert llm_cancel.snapshot()[1] is False, \
            "the world must be RE-ARMED after a rollback even when observer.join() raised (HIGH-3)"
        assert llm_client.llm_generate(engine.settings, "prompt") == "ok"
    finally:
        llm_cancel.begin_lifespan()


def test_stop_and_drain_rearms_even_when_cancel_raises(monkeypatch):
    """HIGH-2 refine (council-pr R2) + HIGH-3 (R3): the ENTIRE drain body — not just observer
    cleanup — sits inside the try/finally, so ANY raise in it still rearms on the rollback path.

    R3 narrowed this further: a raising ``cancel_active_llm_calls()`` is now SUPPRESSED (it is
    best-effort; the join fence after it is load-bearing), so it no longer propagates at all.
    The rearm-in-finally guarantee is therefore proven here with a raise from a LOAD-BEARING
    step (``handler.wake()``), which must still propagate — after the rearm has run."""
    import ormah.background.session_watcher as sw
    from ormah.background.session_watcher import SessionWatch

    def _raising_cancel(*, final=True):
        raise RuntimeError("cancel_active blew up after setting the cancel flag")

    monkeypatch.setattr(sw, "cancel_active_llm_calls", _raising_cancel)

    # R3: a best-effort cancel failure is suppressed — it must NOT propagate, and the rollback
    # path still rearms.
    resumed_rollback = []
    monkeypatch.setattr(sw, "resume_llm_adapters", lambda: resumed_rollback.append(True))
    sw._stop_and_drain([], rearm=True)  # empty watches -> reaches the first cancel call
    assert resumed_rollback == [True], \
        "rearm must run in finally even when cancel_active_llm_calls raised (HIGH-2)"

    # A LOAD-BEARING step raising still propagates — but only AFTER the finally rearmed.
    class _WakeRaisingHandler:
        def __init__(self):
            self._stop_event = threading.Event()

        def cancel_pending_timers(self):
            pass

        def wake(self):
            raise RuntimeError("wake blew up")

        def drain_alive(self):
            return False

        def join_drain(self, timeout=None):
            pass

        def in_flight_count(self):
            return 0

    watch = SessionWatch(watch_dir=Path("/tmp/high2"), handler=_WakeRaisingHandler(),
                         observer=None, spool=None, discover=False)
    resumed_loadbearing = []
    monkeypatch.setattr(sw, "resume_llm_adapters", lambda: resumed_loadbearing.append(True))
    with pytest.raises(RuntimeError):
        sw._stop_and_drain([watch], rearm=True)
    assert resumed_loadbearing == [True], \
        "rearm must run in finally even when a load-bearing step raised (HIGH-2)"

    # Normal shutdown: same load-bearing raise, but rearm=False must NEVER resume.
    watch_normal = SessionWatch(watch_dir=Path("/tmp/high2b"), handler=_WakeRaisingHandler(),
                                observer=None, spool=None, discover=False)
    resumed_normal = []
    monkeypatch.setattr(sw, "resume_llm_adapters", lambda: resumed_normal.append(True))
    with pytest.raises(RuntimeError):
        sw._stop_and_drain([watch_normal], rearm=False)
    assert resumed_normal == [], "a normal shutdown must never rearm, even if a step raised"


def test_stop_and_drain_join_fence_survives_a_raising_cancel(monkeypatch):
    """HIGH-3 (council-pr R3, Codex) USE-AFTER-CLOSE. The R2 test used an EMPTY watch list, so
    the `while any(drain_alive())` fence was trivially skipped and this bug hid behind it.

    cancel_active_llm_calls() sits in the try body; if it raises, control jumps to the finally —
    the rearm runs, but the ENTIRE join fence (join_drain, _drain_handlers, observer.join) is
    SKIPPED. An un-joined orphan drain thread then outlives the rollback and can touch the DB
    after engine.shutdown() closes it (#52) — exactly what the fence exists to prevent.

    The cancel calls are BEST-EFFORT; the join fence is LOAD-BEARING and must always run."""
    import ormah.background.session_watcher as sw
    from ormah.background.session_watcher import SessionWatch

    class _FakeHandler:
        def __init__(self):
            self._stop_event = threading.Event()
            self.join_drain_calls = 0
            self.wake_calls = 0
            self._alive = True

        def cancel_pending_timers(self):
            pass

        def wake(self):
            self.wake_calls += 1

        def drain_alive(self):
            return self._alive

        def join_drain(self, timeout=None):
            self.join_drain_calls += 1
            self._alive = False  # the drain thread exits once actually joined

        def in_flight_count(self):
            return 0

    class _RecordingObserver:
        def __init__(self):
            self.stopped = False
            self.joined = False

        def stop(self):
            self.stopped = True

        def join(self, timeout=None):
            self.joined = True

    handler = _FakeHandler()
    observer = _RecordingObserver()
    watch = SessionWatch(watch_dir=Path("/tmp/high3"), handler=handler, observer=observer,
                         spool=None, discover=False)

    def _raising_cancel(*, final=True):
        raise RuntimeError("cancel_active blew up after setting the cancel flag")

    monkeypatch.setattr(sw, "cancel_active_llm_calls", _raising_cancel)
    resumed = []
    monkeypatch.setattr(sw, "resume_llm_adapters", lambda: resumed.append(True))

    # (c) a best-effort cancel failing must NOT escape over the fence
    sw._stop_and_drain([watch], rearm=True)

    # (a) the LOAD-BEARING join fence really ran despite the raising cancel
    assert handler.join_drain_calls >= 1, \
        "join_drain never ran — a raising cancel skipped the load-bearing join fence (#52)"
    assert observer.joined, "observer.join never ran — the join fence was skipped"
    # (b) the rollback path still re-armed the adapters
    assert resumed == [True], "the rollback path must still rearm"


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


class TestAboveCapOrphanRecovery:
    """#154 above-cap class: recovery must never move the cursor backward, and an
    un-drainable tail is abandoned EXPLICITLY (skipped_slices), not looped over.

    The caps below are measured against `_write_orphan_tail_jsonl`'s cleaned content, not
    its raw bytes: one closed turn is ~1235 chars and the trailing orphan ~620, so a slice
    budget at or above ~1855 swallows both in one drain and no leading orphan ever forms —
    the class stops being exercised while the tests still pass. 1500 admits a full turn and
    stays below that cliff. The tests that park the cursor immediately before the orphan
    reach the class from any budget and keep their own values."""

    def test_cursor_never_retreats_and_abandons_explicitly(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154.jsonl"
        _write_orphan_tail_jsonl(jsonl)          # ~10 KB total
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        offsets = []
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE) as llm:
            for _ in range(12):
                _ingest_session(engine, jsonl, state, watch_dir,
                                min_turns=5, flush_chars=1500)
                offsets.append(state[rel]["end_offset"])
                _mark_idle(jsonl)                # ingest re-stats; keep it idle
        for prev, cur in zip(offsets, offsets[1:]):
            assert cur >= prev, f"cursor retreated: {offsets}"
        # The un-drainable tail is abandoned explicitly: cursor lands at EOF with a
        # durable loss record, and the LLM is never called again afterwards.
        assert offsets[-1] == size
        skipped = state[rel]["skipped_slices"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "orphan_above_cap"
        assert skipped[0]["end"] == size
        assert skipped[0]["start"] < size
        assert llm.call_count <= 8, f"re-extraction loop: {llm.call_count} LLM calls"

    def test_small_file_recovery_is_still_one_shot(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "oneshot.jsonl"
        _write_orphan_tail_jsonl(jsonl, pairs=1, pad=10)   # well below flush_bytes
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        # A legacy mid-response cursor parked right before the trailing orphan record.
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            result = _ingest_session(engine, jsonl, state, watch_dir,
                                     min_turns=1, flush_chars=60000)
        assert result == IngestResult.OK
        assert state[rel]["end_offset"] == size   # recovered to EOF in one slice, no retreat
        assert not state[rel].get("skipped_slices")   # nothing was abandoned

    def test_run_job_completes_abandoned_orphan_without_dead_letter(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154.jsonl"
        _write_orphan_tail_jsonl(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.flush_chars = 1500
        handler.spool.enqueue(jsonl, boundary=size, reason="drain")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
            _mark_idle(jsonl)
            _drain_all(handler)          # second pass drains any capped continuations
        assert _spool_idle(handler.spool), "job neither completed nor drained"
        entry = handler._state[rel]
        assert entry["end_offset"] == size
        # The EXPLICIT path leaves the durable record; the frozen-prefix side effect
        # (_mark_frozen_prefix_consumed) would have advanced the cursor WITHOUT it.
        assert entry["skipped_slices"][0]["reason"] == "orphan_above_cap"

    def test_two_idle_ticks_on_unchanged_frozen_file_never_dead_letter(self, engine, tmp_path):
        """ADR-0004 Fix A direct regression: parking the SAME unchanged file across two
        consecutive idle ticks (no growth between them, no producer-level _frozen_unchanged
        gate involved — this drives _ingest_session directly through the spool) must not
        write anything to failed/ at all. Before Fix A, the second job's disposition was
        identical to the first's: two dead-letters for a file examined twice with no growth.
        After Fix A, both ticks complete."""
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "twotick.jsonl"
        _partial_unterminated(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)

        # Tick 1: first examination parks and completes.
        handler.spool.enqueue(jsonl, boundary=size, reason="nudge")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
        assert not list((handler.spool.root / "failed").glob("*.json"))
        assert handler._state[rel]["frozen_until"] == size

        # Tick 2: the file is byte-for-byte unchanged (no growth); a second job for the SAME
        # (path, boundary) re-examines it (enqueue is a no-op while the tick-1 job file still
        # exists, so tick 1 must have fully completed -- i.e. unlinked its job -- for this
        # enqueue to create a fresh one). Re-parking must be idempotent and must not dead-letter.
        handler.spool.enqueue(jsonl, boundary=size, reason="nudge")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
        assert not list((handler.spool.root / "failed").glob("*.json")), \
            "re-examining an unchanged parked file must not dead-letter, ever"
        assert handler._state[rel]["frozen_until"] == size
        assert handler.spool.pending_count() == 0

    def test_park_refused_by_race_falls_back_to_external_retry_not_silent_complete(
        self, engine, tmp_path
    ):
        """Council R1/R2 (codex): a RETRY disposition (changed-under-examination race) must
        get the SAME persisted-backoff external retry the neighboring shrink_pending race
        already gets -- an acceptance-only root has no Observer/reconcile to ever re-select
        the file on its own, so silently completing would strand it forever."""
        from ormah.background.session_watcher import ParkOutcome

        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "race.jsonl"
        _partial_unterminated(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.spool.enqueue(jsonl, boundary=size, reason="nudge")
        with patch.object(handler, "_mark_frozen_prefix_parked",
                          return_value=ParkOutcome.RETRY), \
             patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
        assert not list((handler.spool.root / "failed").glob("*.json")), \
            "a RETRY disposition must retry, never dead-letter"
        assert handler.spool.pending_count() == 1, \
            "the job must stay queued with persisted backoff, not vanish"
        assert "frozen_until" not in handler._state.get(rel, {})

    def test_park_refused_by_deletion_dead_letters_even_if_the_path_is_later_recreated(
        self, engine, tmp_path
    ):
        """Council R2 (codex + cursor, the defect that survived the R1 fix): the disposition
        is decided ONCE, atomically, inside _mark_frozen_prefix_parked -- the call site must
        NOT re-derive it from a fresh path.exists() afterward. Proven directly: recreate the
        path in the mock's side effect, after the GONE disposition has already been returned,
        and assert the dead-letter still happens -- a fresh existence check would flip this."""
        from ormah.background.session_watcher import ParkOutcome

        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "vanish.jsonl"
        _partial_unterminated(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.spool.enqueue(jsonl, boundary=size, reason="nudge")

        def _gone_then_recreate(path, rel, boundary, *, examined):
            jsonl.unlink()
            jsonl.write_text('{"type": "user", "message": {"content": "recreated"}}\n')
            return ParkOutcome.GONE

        with patch.object(handler, "_mark_frozen_prefix_parked",
                          side_effect=_gone_then_recreate), \
             patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
        assert handler.spool.pending_count() == 0
        assert not any(
            p.name.endswith(".json") for p in (handler.spool.root / "running").iterdir()
        )
        errs = list((handler.spool.root / "failed").glob("*.error"))
        assert errs and "transcript_deleted" in errs[0].read_text(), \
            "GONE must dead-letter regardless of what the path does afterward"

    def test_abandonment_with_unclosed_tail_composes_with_frozen_prefix(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "loop154tail.jsonl"
        _write_orphan_tail_jsonl(jsonl)
        # An UNCLOSED in-flight record after the closing orphan: probe_safe_end < size.
        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "stop_reason": None,
                            "content": [{"type": "text", "text": "still streaming"}]},
            }) + "\n")
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        rel = str(jsonl.relative_to(watch_dir))
        handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool",
                                      min_turns=5, idle_threshold=30.0)
        handler.flush_chars = 1500
        handler.spool.enqueue(jsonl, boundary=size, reason="drain")
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _drain_all(handler)
            _mark_idle(jsonl)
            _drain_all(handler)
        entry = handler._state[rel]
        # The abandonment recorded ITS range durably...
        skipped = entry["skipped_slices"]
        assert skipped[0]["reason"] == "orphan_above_cap"
        assert skipped[0]["end"] < size            # == probe_safe_end, before the unclosed tail
        # ...and the residual tail followed the standard frozen-prefix path: PARKED, not
        # consumed (ADR-0004 Fix B) — and completed without a dead-letter (ADR-0004 Fix A).
        # The cursor stays at the abandoned range's end and the suppression fact carries the
        # ceiling.
        assert entry["end_offset"] == skipped[0]["end"]
        assert entry["frozen_until"] == size
        assert not list((handler.spool.root / "failed").glob("*.json")), \
            "a parked residual tail must complete, not dead-letter (ADR-0004 Fix A)"

    def test_abandoned_range_magnitude_is_pinned(self, engine, tmp_path):
        """Review follow-up: every OTHER fixture in this class places the trailing orphan
        one small record from EOF, so the abandoned range those tests exercise is tiny and
        its size is never actually checked. Here the trailing orphan record itself is made
        deliberately huge (pad=20000) so the abandoned range [orphan_start, size) is large
        AND exactly computable from the fixture -- a future change that silently enlarges or
        shrinks what gets discarded must fail this test, not just "still returns OK"."""
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "bigorphan.jsonl"
        _write_orphan_tail_jsonl(jsonl, pairs=2, pad=20000)   # trailing record alone ~20 KB
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        # A legacy mid-response cursor parked right before the (huge) trailing orphan record,
        # far below the probe's safe boundary (EOF) once recovery runs.
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            result = _ingest_session(engine, jsonl, state, watch_dir,
                                     min_turns=1, flush_chars=2000)
        assert result == IngestResult.OK
        # Cursor-monotonicity: the abandonment never retreats below the parked cursor, and
        # lands exactly at EOF (the probe's safe boundary), never short of it.
        assert state[rel]["end_offset"] >= orphan_start
        assert state[rel]["end_offset"] == size
        skipped = state[rel]["skipped_slices"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "orphan_above_cap"
        # Exact, fixture-derived numbers -- not a loose bound. The abandoned range is
        # precisely the huge trailing record, nothing more, nothing less.
        assert skipped[0]["start"] == orphan_start
        assert skipped[0]["end"] == size
        assert skipped[0]["end"] - skipped[0]["start"] == last_line_bytes

    def test_abandonment_commit_oserror_propagates(self, engine, tmp_path, monkeypatch):
        """council R3: the abandonment COMMIT lives OUTSIDE the broad parse `try`, so a
        storage failure must surface as itself -- never be swallowed by the `except
        Exception` there and returned as NO_PROGRESS, which would route a valid transcript
        into frozen-prefix/dead-letter handling. Patches `_commit_state`, not `_save_state`:
        `_commit_state` is the exact call the abandonment block makes, so this pins the call
        site itself; `_save_state` sits one level deeper, inside `_commit_state`'s own
        lock-branching, which is an implementation detail this test should not depend on.

        The stub records what it was HANDED and asserts on it (not just that SOME OSError
        propagated): every `_commit_state` call in `_ingest_session` sits outside the parse
        `try` (abandonment, quarantine, happy path alike), so a bare `pytest.raises(OSError)`
        would stay green even if this fixture stopped reaching the abandonment branch at all
        -- e.g. once Task 2 adds its `allow_rewind` preamble. The positional prefix matches
        `_commit_state(state, rel, entry, ...)`; the `*args, **kwargs` tail absorbs whatever
        Task 2 appends (e.g. a keyword-only `allow_rewind`) without breaking this pin."""
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "commitfails.jsonl"
        _write_orphan_tail_jsonl(jsonl)
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}

        calls = []

        def _raise_oserror(state_, rel_, entry, *args, **kwargs):
            calls.append(entry)
            raise OSError("disk full")

        monkeypatch.setattr("ormah.background.session_watcher._commit_state", _raise_oserror)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE), pytest.raises(OSError):
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=1, flush_chars=2000)
        assert calls, "abandonment commit was never reached"
        assert calls[-1]["skipped_slices"][-1]["reason"] == "orphan_above_cap"

    def test_extract_failure_during_rewind_keeps_cursor(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "failrewind.jsonl"
        _write_orphan_tail_jsonl(jsonl, pairs=1, pad=10)   # small file: rewind proceeds
        _mark_idle(jsonl)
        size = jsonl.stat().st_size
        last_line_bytes = len((jsonl.read_text().splitlines()[-1] + "\n").encode())
        orphan_start = size - last_line_bytes
        rel = str(jsonl.relative_to(watch_dir))
        state = {rel: {"hash": "stale", "end_offset": orphan_start}}
        # Slice-specific failure: the LLM answers, but with unparseable content — the
        # deterministic class that goes through _record_extract_failure (not TRANSIENT-early).
        with patch(_LLM_PATCH, return_value="not-json"):
            result = _ingest_session(engine, jsonl, state, watch_dir,
                                     min_turns=1, flush_chars=60000)
        assert result == IngestResult.TRANSIENT
        # Pre-fix this is 0: the rewind zeroed prev_offset and the fail path committed it.
        assert state[rel]["end_offset"] == orphan_start
        # Council R1 (Cursor): the counter is keyed on the durable pre-rewind cursor, so
        # the persisted pair is consistent — not extract_fail_offset=0 with a real cursor.
        assert state[rel]["extract_fail_offset"] == orphan_start
        assert state[rel]["extract_fail_count"] == 1
        # Council R3 (Codex): one failure cannot distinguish correct keying from a
        # counter that resets to 1 forever. A SECOND failed rewind must accumulate...
        with patch(_LLM_PATCH, return_value="not-json"):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1, flush_chars=60000) == IngestResult.TRANSIENT
        assert state[rel]["extract_fail_count"] == 2
        # ...and the THIRD reaches MAX_EXTRACT_FAILURES: the toxic slice is quarantined
        # (skipped_slices) and the cursor finally advances — the counter converges
        # instead of pinning the cursor forever.
        with patch(_LLM_PATCH, return_value="not-json"):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1, flush_chars=60000) == IngestResult.OK
        assert state[rel]["end_offset"] > orphan_start
        # council C2: the quarantine's loss record starts at the durable pre-rewind
        # cursor — NOT at 0, which would make the backfill replay ingested history.
        assert state[rel]["skipped_slices"][0]["start"] == orphan_start
        assert "extract_fail_count" not in state[rel]

    def test_file_shrink_still_rewinds_cursor(self, engine, tmp_path):
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "shrunk.jsonl"
        _make_jsonl(jsonl, user_turns=6)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        old_size = jsonl.stat().st_size
        assert state[rel]["end_offset"] == old_size
        # The transcript is rewritten smaller (compaction/rewrite) — a legitimate retreat,
        # but task 4 requires it confirmed on a SECOND tick before it is published durably.
        _make_jsonl(jsonl, user_turns=2)
        _mark_idle(jsonl)
        new_size = jsonl.stat().st_size
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1) == IngestResult.NO_PROGRESS
        assert state[rel]["end_offset"] == old_size          # tick 1: unchanged, pending
        assert state[rel]["shrink_pending"]
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1) == IngestResult.OK
        # A naive monotonic clamp would freeze the cursor above EOF and reconcile
        # would skip this file forever.
        assert state[rel]["end_offset"] == new_size
        assert "shrink_pending" not in state[rel]

    def test_shrunk_file_with_no_safe_boundary_is_not_stranded(self, engine, tmp_path):
        # council C2 (codex): a shrunk rewrite with NO closed boundary used to return
        # NO_PROGRESS without any commit, leaving the durable cursor above EOF —
        # reconcile would skip the file forever. Task 4: the reset now waits for a
        # confirming second tick, but once confirmed it must still persist even on a
        # no-progress tick — the stranding window becomes ONE reconcile interval, not
        # forever.
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "shrunkbad.jsonl"
        _make_jsonl(jsonl, user_turns=6)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        # Rewritten smaller with NO closed boundary: a single open user turn.
        jsonl.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "only an open turn"},
        }) + "\n")
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.NO_PROGRESS
        assert state[rel]["shrink_pending"]                # tick 1: pending, not stranded yet
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
        assert state[rel]["end_offset"] <= jsonl.stat().st_size
        assert "shrink_pending" not in state[rel]

    def test_transient_truncation_is_not_durably_honoured(self, engine, tmp_path):
        """Task 4 regression: a single stat() observing size < cursor must NOT publish a
        durable end_offset=0. An in-place editor's truncate-then-rewrite window is
        milliseconds; treating one stat() as proof would re-ingest the whole file from
        zero the moment the writer finishes restoring it."""
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "transient.jsonl"
        _make_jsonl(jsonl, user_turns=6)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        original_bytes = jsonl.read_bytes()
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        cursor = state[rel]["end_offset"]
        assert cursor == len(original_bytes)

        # Transient truncation (e.g. an editor mid-rewrite): below the stored cursor.
        jsonl.write_bytes(original_bytes[: cursor // 2])
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            result = _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
        assert result == IngestResult.NO_PROGRESS
        assert state[rel]["end_offset"] == cursor           # NOT reset to 0
        assert state[rel]["shrink_pending"]                 # tick 1 marker persisted

        # The writer finishes: the file is restored to its original full content.
        jsonl.write_bytes(original_bytes)
        _mark_idle(jsonl)
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            _ingest_session(engine, jsonl, state, watch_dir, min_turns=5)
        assert "shrink_pending" not in state[rel]            # marker cleared
        assert state[rel]["end_offset"] == cursor             # no whole-file re-ingest

    def test_shrink_marker_size_mismatch_does_not_confirm(self, engine, tmp_path):
        """Review follow-up (Change 3): the marker records the observed size so two
        INDEPENDENT transient truncations of different sizes cannot confirm each other.
        A different-size second observation re-arms the marker instead of confirming."""
        watch_dir = tmp_path / "projects"
        proj = watch_dir / "-test-space"
        proj.mkdir(parents=True)
        jsonl = proj / "shrunk.jsonl"
        _make_jsonl(jsonl, user_turns=10)
        _mark_idle(jsonl)
        rel = str(jsonl.relative_to(watch_dir))
        state: dict = {}
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.OK
        cursor = state[rel]["end_offset"]

        _make_jsonl(jsonl, user_turns=4)   # first transient truncation
        _mark_idle(jsonl)
        size_a = jsonl.stat().st_size
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.NO_PROGRESS
        assert state[rel]["shrink_pending"]["size"] == size_a
        assert state[rel]["end_offset"] == cursor

        _make_jsonl(jsonl, user_turns=2)   # a DIFFERENT, unrelated truncation size
        _mark_idle(jsonl)
        size_b = jsonl.stat().st_size
        assert size_b != size_a
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            # Size mismatch: re-armed, NOT confirmed.
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=5) == IngestResult.NO_PROGRESS
        assert state[rel]["shrink_pending"]["size"] == size_b   # re-armed with the NEW size
        assert state[rel]["end_offset"] == cursor                # still not reset

        # NOW confirm: same size as the re-armed marker, observed again.
        with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
            assert _ingest_session(engine, jsonl, state, watch_dir,
                                   min_turns=1) == IngestResult.OK
        assert "shrink_pending" not in state[rel]


class TestCommitStateMonotonic:
    def test_stale_lower_commit_is_clamped(self, tmp_path):
        state: dict = {}
        lock = threading.Lock()
        _commit_state(state, "a.jsonl", {"end_offset": 200}, lock, tmp_path)
        # A writer that decided on stale data commits a LOWER offset afterwards —
        # the ordering Codex flagged. The clamp re-reads under the lock, so the
        # retreat is refused no matter when the stale decision was made.
        _commit_state(state, "a.jsonl", {"end_offset": 150, "extra": "kept"}, lock, tmp_path)
        assert state["a.jsonl"]["end_offset"] == 200
        assert state["a.jsonl"]["extra"] == "kept"      # only the offset is clamped
        assert _load_state(tmp_path)["a.jsonl"]["end_offset"] == 200

    def test_allow_rewind_accepts_lower_commit(self, tmp_path):
        state: dict = {}
        _commit_state(state, "a.jsonl", {"end_offset": 200}, None, tmp_path)
        _commit_state(state, "a.jsonl", {"end_offset": 50}, None, tmp_path,
                      allow_rewind=True)
        assert state["a.jsonl"]["end_offset"] == 50

    def test_save_failure_does_not_publish_in_memory(self, tmp_path, monkeypatch):
        # council R2 (codex): a failed persist must not leave the shared in-memory dict
        # claiming the new cursor — the retry would look already-consumed while disk
        # kept the old offset.
        state: dict = {}
        _commit_state(state, "a.jsonl", {"end_offset": 100}, None, tmp_path)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("ormah.background.session_watcher._save_state", _boom)
        with pytest.raises(OSError):
            _commit_state(state, "a.jsonl", {"end_offset": 200}, None, tmp_path)
        assert state["a.jsonl"]["end_offset"] == 100   # not published on failed persist
        monkeypatch.undo()
        assert _load_state(tmp_path)["a.jsonl"]["end_offset"] == 100


# --- ADR-0004: a deleted transcript is deterministic, never an external failure ---

def test_deleted_transcript_is_dead_lettered_not_retried_forever(engine, tmp_path):
    """requeue's contract names this case: "transcript deleted ... a retry cannot change
    the outcome, so the job is dead-lettered immediately". FileNotFoundError is an OSError,
    so it fell into the generic handler, was classed "external", and retried forever --
    which is what fed 8 jobs to the backoff overflow on 2026-08-11."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "gone.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    jsonl.unlink()                       # the transcript is gone before the drain claims it

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, "a deleted transcript must be dead-lettered, not retried"
    assert handler.spool.pending_count() == 0, (
        "it must not go back to pending as an external failure"
    )
    assert list((handler.spool.root / "running").iterdir()) == []
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()


def test_transcript_deleted_mid_drain_is_dead_lettered_not_completed(engine, tmp_path, monkeypatch):
    """TOCTOU: _file_hash and stat both succeed, then the parser re-reads the file and finds
    it gone. That FileNotFoundError lands in the generic `except Exception` -> NO_PROGRESS ->
    complete(job): the job is erased with NO dead-letter record. Silent loss is the one thing
    H1 forbids outright."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "vanishes.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    import ormah.background.session_watcher as sw
    real_parse = sw.parse_transcript

    def _delete_then_parse(path, *args, **kwargs):
        # Gone before the parser touches it at all, so the ENOENT surfaces from the parser's
        # own path.stat() rather than its open(). Either raises FileNotFoundError into the
        # same handler, which is what this test pins.
        Path(path).unlink(missing_ok=True)
        return real_parse(path, *args, **kwargs)

    monkeypatch.setattr(sw, "parse_transcript", _delete_then_parse)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, (
        "a transcript deleted mid-drain must leave a dead-letter record, never be completed"
    )
    assert handler.spool.pending_count() == 0
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()


def test_transcript_deleted_after_ingest_returns_is_dead_lettered(engine, tmp_path, monkeypatch):
    """The transcript survives _ingest_session (which returns NO_PROGRESS on its own merits)
    and is deleted before the drain decides. _idle_with_unsafe_tail swallows the ENOENT in both
    its stat and its parse, returning False, so the drain would complete(job) -- erasing it with
    no dead-letter record."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "late.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    import ormah.background.session_watcher as sw

    def _no_progress_then_delete(*args, **kwargs):
        jsonl.unlink(missing_ok=True)          # gone AFTER the ingest decision, before the drain's
        return sw.IngestResult.NO_PROGRESS

    monkeypatch.setattr(sw, "_ingest_session", _no_progress_then_delete)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, "a transcript gone by decision time must leave a dead-letter record"
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()


def test_enqueue_path_skips_a_frozen_file_until_it_changes(engine, tmp_path):
    """The Observer lane must honour the same suppression fact as reconcile. Gating only
    the sweep trades a growing failed/ for a hot enqueue loop on every FSEvent."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "frozen.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))
    size = jsonl.stat().st_size

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        assert handler._state[rel]["frozen_until"] == size

        handler._enqueue_path(jsonl, "observer")     # a second FSEvent, file unchanged
        assert handler.spool.pending_count() == 0, \
            "an unchanged frozen file must not be re-enqueued by the Observer"

        with jsonl.open("a") as fh:
            fh.write(json.dumps({
                "type": "user",
                "message": {"content": "a second prompt long enough to parse here"},
            }) + "\n")
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, \
            "growth must re-open the Observer lane too"


def test_enqueue_path_reopens_a_frozen_file_that_was_rotated_smaller(engine, tmp_path):
    """Council round 1, critical: this is the lane that catches rotation today, because it
    consults no state at all. A ceiling-only gate here would suppress a rotated transcript
    permanently — and with reconcile also gated, nothing else would ever find it."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "rotated.jsonl"
    # A single unterminated turn, padded well past what a 6-turn complete conversation
    # takes -- `_partial_unterminated`'s own ~220 bytes is smaller than ANY _make_jsonl
    # output, which would make "rotated smaller" unreachable with these helpers combined.
    padding = "x" * 4000
    jsonl.write_text(
        json.dumps({"type": "user", "message": {"content": f"a long prompt {padding}"}})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": f"an answer that never closed {padding}"}]}})
        + "\n"
    )
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        frozen = handler._state[rel]["frozen_until"]

        jsonl.unlink()
        _make_jsonl(jsonl, user_turns=6)
        assert jsonl.stat().st_size < frozen
        _mark_idle(jsonl)

        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, \
            "a rotated file must be re-enqueued, not hidden behind the old ceiling"
        _drain_all(handler)

    assert handler._state[rel].get("node_ids"), "the rotated file's content must be ingested"


def test_enqueue_path_re_arms_suppression_after_a_same_size_replacement(engine, tmp_path):
    """Council round 2, cursor, medium: proving the re-open is half the story. If the re-park
    does not converge identity, every FSEvent re-enqueues the same unparseable file forever
    and failed/ grows without bound — the failure mode the frozen fact exists to prevent."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "samesize.jsonl"
    _partial_unterminated(jsonl)
    _mark_idle(jsonl)
    rel = str(jsonl.relative_to(watch_dir))

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        handler._enqueue_path(jsonl, "observer")
        _drain_all(handler)
        original = jsonl.read_bytes()

        replacement = proj / "tmp.jsonl"
        replacement.write_bytes(original)
        replacement.replace(jsonl)
        _mark_idle(jsonl)

        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 1, "the replacement must re-open the lane"
        _drain_all(handler)

        assert handler._state[rel]["frozen_ino"] == jsonl.stat().st_ino
        handler._enqueue_path(jsonl, "observer")
        assert handler.spool.pending_count() == 0, \
            "suppression must re-arm on the new identity, not loop forever"


# --- Issue #220: confirmed use from the auto_llm_judge path -----------------

_LIFECYCLE_FIELDS = ("access_count", "last_accessed", "stability", "last_review")


def _lifecycle(engine, node_id):
    """The four lifecycle fields, from the markdown file and the SQLite row."""
    node = engine.file_store.load(node_id)
    row = engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    return {
        "file": tuple(getattr(node, f) for f in _LIFECYCLE_FIELDS),
        "db": tuple(row[f] for f in _LIFECYCLE_FIELDS),
    }


def test_llm_judge_used_verdict_records_confirmed_use(engine, tmp_path):
    """Issue #220: a positive auto_llm_judge verdict confirms use for its node."""
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-confirms-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-confirms-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_JUDGE_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    after = _lifecycle(engine, node_id)
    assert after != before, "the judged-used node was not confirmed"
    assert after["file"][0] == before["file"][0] + 1, "access_count did not advance by one"
    assert after["db"][0] == after["file"][0], "file and DB disagree on access_count"

    # The signal and affinity rows must still be written — confirmed use is
    # additional behaviour, not a replacement for observability.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["source"] == "auto_llm_judge"


def test_llm_judge_unused_verdict_does_not_record_confirmed_use(engine, tmp_path):
    """A negative verdict is affinity evidence only — it never reinforces."""
    prompt = "What deployment marker should we use?"
    response = "Ignore that; we are switching to a completely different scheme."
    transcript_path = tmp_path / "judge-unused-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-unused-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "unused",
            "confidence": 0.9,
            "reason": "The answer rejects the injected guidance.",
        }]
    })
    with patch(_JUDGE_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    assert _lifecycle(engine, node_id) == before, "an unused verdict changed lifecycle fields"


def test_heuristic_positive_does_not_record_confirmed_use(engine, tmp_path):
    """Issue #220: auto_heuristic yields polarity 1 but never confirms use.

    The heuristic path is excluded pending #218 signal calibration. This is the
    case that matters: it is positive, so only the source keeps it out.
    """
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "heuristic-no-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="heuristic-no-confirm-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)

    recorded = _record_whisper_usage_signals(engine, transcript)

    # The heuristic signal is still recorded — this is about lifecycle, not observability.
    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1

    assert _lifecycle(engine, node_id) == before, "auto_heuristic confirmed use — it must not"

    # And it claimed nothing, so a later qualified positive can still confirm.
    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is None, "the heuristic path took a confirmed-use claim"


def test_replaying_the_judge_does_not_reconfirm(engine, tmp_path):
    """Issue #220: a second pass over the same transcript reinforces nothing.

    has_llm_judge already excludes an event that was judged before, so the
    replay should not even reach the confirm loop — and the claim latch stops it
    a second time if it does. Two independent guards, deliberately.
    """
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-replay-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-replay-session", prompt=prompt,
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
    with patch(_JUDGE_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)
    after_first = _lifecycle(engine, node_id)

    with patch(_JUDGE_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    assert _lifecycle(engine, node_id) == after_first, (
        "replaying the judge reinforced the same event twice"
    )


def test_feedback_claim_makes_the_judge_a_noop(engine, tmp_path):
    """Issue #220 cross-caller contract: one event, one reinforcement, two callers.

    This is the case has_llm_judge cannot cover: it only looks at signals whose
    source is transcript_watcher_llm_judge, so it is blind to feedback submitted
    through MCP. Before the claim latch, an implicit +1 followed by a positive
    judge verdict on the same whisper event reinforced it twice.
    """
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-cross-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-cross-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    engine.submit_feedback(node_id, signal=1, source="implicit", whisper_log_id=whisper_log_id)
    after_feedback = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_JUDGE_PATCH, return_value=llm_response):
        recorded = _record_whisper_usage_signals(engine, transcript)

    # The judge's own signal and affinity rows are still written — observability
    # is not what the claim gates.
    assert recorded >= 1, "the judge signal was not recorded"
    assert _lifecycle(engine, node_id) == after_feedback, (
        "the judge reinforced an event already confirmed through submit_feedback"
    )


def test_one_failing_node_does_not_skip_the_rest_of_the_batch(engine, tmp_path):
    """Issue #220: reinforcement is isolated per node, for any exception.

    The judge signals and the claims are already committed when this loop runs,
    so an escaping exception would abort the slice and — because has_llm_judge is
    now set and the claims are taken — the retry would never reinforce these
    events. The later nodes would lose their only chance at confirmation.

    ZeroDivisionError is the realistic case, not a contrived one: stability is
    Field(default=1.0, ge=0.0), so zero is legal, and the mutator divides by it.
    """
    prompt = "What deployment marker should we use?"
    response = "Both of those notes are exactly right."
    transcript_path = tmp_path / "judge-batch-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    first_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact", title="Blue deployment rollback marker",
    ))
    second_id, _ = engine.remember(CreateNodeRequest(
        content="Roll back within one minute when the marker check fails.",
        type="fact", title="Rollback timing",
    ))
    log_ids = [
        _insert_injected_whisper_log(
            engine, node_id=node_id, session_id="judge-batch-session", prompt=prompt,
        )
        for node_id in (first_id, second_id)
    ]
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before_second = _lifecycle(engine, second_id)

    real_mutator = engine._record_confirmed_use

    def failing_for_first(node_id):
        if node_id == first_id:
            raise ZeroDivisionError("float division by zero")
        return real_mutator(node_id)

    llm_response = json.dumps({
        "verdicts": [
            {"whisper_log_id": log_id, "verdict": "used", "confidence": 0.9,
             "reason": "endorsed"}
            for log_id in log_ids
        ]
    })
    with patch(_JUDGE_PATCH, return_value=llm_response), \
         patch.object(engine, "_record_confirmed_use", side_effect=failing_for_first):
        recorded = _record_whisper_usage_signals(engine, transcript)

    # Both nodes go through the heuristic pass unreferenced (the response text
    # matches neither node's id/title/content), then both go to the judge pass:
    # 2 heuristic signals + 2 judge signals.
    assert recorded == 4, "the signals themselves must still be recorded"
    assert _lifecycle(engine, second_id) != before_second, (
        "the first node's failure skipped the second node's reinforcement"
    )

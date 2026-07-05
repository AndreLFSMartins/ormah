"""Extraction error classification: timeout/call-failure must not read as 'no provider'."""
from __future__ import annotations

import json
from unittest.mock import patch

from ormah.engine.memory_engine import (
    EXTRACT_ERR_CALL_FAILED,
    EXTRACT_ERR_NO_PROVIDER,
)

_CONTENT = "User asked about X. " * 20  # > 50 chars so extraction runs


def test_extraction_call_failure_is_distinct_from_no_provider(engine):
    # ingest_llm_generate is imported locally inside _extract_memories_llm (per call),
    # so it must be patched at its defining module (ormah.background.llm_client) —
    # matching the convention used by every other ingest test (see test_ingest.py's
    # _LLM_PATCH). ingest_provider_configured is imported at module scope in
    # memory_engine, so it is patched there instead.
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(_CONTENT)
    assert result == EXTRACT_ERR_CALL_FAILED

    # No provider configured -> the honest "unavailable" message.
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=False):
        result = engine._extract_memories_llm(_CONTENT)
    assert result == EXTRACT_ERR_NO_PROVIDER


def test_oversized_payload_is_chunked_not_truncated(engine):
    """Content larger than ingest_chunk_chars is split at line boundaries and every chunk is
    extracted — the tail is never dropped."""
    engine.settings.ingest_chunk_chars = 100  # tiny, to force multiple chunks
    # 5 lines * ~60 chars = ~300 chars -> at least 3 chunks of <=100.
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        # Each chunk yields one memory tagged with the call index so we can count.
        return json.dumps({"memories": [
            {"content": f"mem for call {len(calls)}", "type": "fact", "title": "t"},
        ]})

    with patch("ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert isinstance(result, list)
    assert len(calls) >= 3            # split into >=3 chunks
    assert len(result) == len(calls)  # every chunk's memory survived (no tail drop)


def test_middle_chunk_failure_keeps_good_chunks(engine):
    """A single failing chunk (e.g. the middle one) does not discard the memories
    already extracted from the chunks that succeeded — the result stays a list."""
    engine.settings.ingest_chunk_chars = 100
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 2:  # fail the middle chunk only
            return None
        return json.dumps({"memories": [
            {"content": f"mem for call {len(calls)}", "type": "fact", "title": "t"},
        ]})

    with patch("ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert isinstance(result, list)          # not an error string — partial success
    assert len(calls) >= 3
    assert len(result) == len(calls) - 1     # every chunk except the failed one survived


def test_all_chunks_failing_returns_retryable_error(engine):
    """If every chunk's call fails while a provider is configured, the whole extraction is a
    retryable error (so Task 04's per-slice cap governs it)."""
    engine.settings.ingest_chunk_chars = 100
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert result == EXTRACT_ERR_CALL_FAILED


def test_confidence_floor_drops_low_value_memories(engine):
    """Extracted memories below ingest_min_confidence are dropped before node creation."""
    engine.settings.ingest_min_confidence = 0.5
    resp = json.dumps({"memories": [
        {"content": "keep me", "type": "fact", "title": "hi", "confidence": 0.9},
        {"content": "drop me", "type": "fact", "title": "lo", "confidence": 0.2},
    ]})
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=resp), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        created = engine.ingest_conversation(content="x" * 100, space="test")

    titles = [c["title"] for c in created]
    assert "hi" in titles
    assert "lo" not in titles

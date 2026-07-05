"""Extraction error classification: timeout/call-failure must not read as 'no provider'."""
from __future__ import annotations

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

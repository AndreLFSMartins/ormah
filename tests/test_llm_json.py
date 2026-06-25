"""Tests for fence-tolerant LLM JSON parsing shared across background jobs.

Thinking-capable local models (e.g. qwen3.5) wrap their output in markdown
``` fences even when asked for JSON mode, which makes a naive json.loads(raw)
fail. extract_json() recovers the embedded JSON so maintenance jobs stop
discarding (auto_linker poisoning, conflict/duplicate misses) valid output.
"""

from __future__ import annotations

import json
from unittest import mock

from ormah.background.llm_client import extract_json

# The exact shape qwen3.5 produced in the wild (see investigation).
FENCED_JSON = (
    '```json\n{\n  "relationship": "none",\n'
    '  "reason": "no link between A and B"\n}\n```'
)


def test_extract_json_strips_json_fence():
    parsed = json.loads(extract_json(FENCED_JSON))
    assert parsed["relationship"] == "none"


def test_extract_json_strips_bare_fence():
    raw = '```\n{"a": 1}\n```'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_passthrough_for_clean_json():
    raw = '{"a": 1}'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_extracts_from_surrounding_prose():
    raw = 'Here is the result:\n{"a": 1}\nHope that helps.'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_auto_linker_recovers_fenced_response_instead_of_poisoning():
    """A fenced-but-valid classification must yield the real relationship,
    not an 'error' result that advances the watermark and strands the node."""
    from ormah.background import auto_linker

    node = {"title": "A", "type": "fact", "space": "x", "content": "content a"}
    other = {"title": "B", "type": "fact", "space": "x", "content": "content b"}
    fenced = '```json\n{"relationship": "supports", "reason": "A backs B"}\n```'

    with mock.patch(
        "ormah.background.llm_client.llm_generate", return_value=fenced
    ):
        result = auto_linker._llm_classify_link(mock.Mock(), node, other)

    assert result is not None
    assert result["relationship"] == "supports"
    assert result["relationship"] != "error"


def test_auto_linker_treats_unparseable_output_as_poison():
    """Genuinely unparseable output (no JSON anywhere) yields an "error" result, never a
    spurious real relationship. The caller treats "error" like "none" (no edge) but counts
    the node as resolved so the watermark advances — poison content must not stall the queue.
    This is distinct from a transient None (LLM unavailable), which leaves the node unresolved."""
    from ormah.background import auto_linker

    node = {"title": "A", "type": "fact", "space": "x", "content": "ca"}
    other = {"title": "B", "type": "fact", "space": "x", "content": "cb"}

    with mock.patch(
        "ormah.background.llm_client.llm_generate", return_value="totally not json"
    ):
        result = auto_linker._llm_classify_link(mock.Mock(), node, other)

    assert result is not None
    assert result["relationship"] == "error"

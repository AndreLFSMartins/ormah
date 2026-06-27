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
    assert extract_json(raw) == raw
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_passthrough_for_clean_array():
    raw = '[{"a": 1}, {"a": 2}]'
    assert extract_json(raw) == raw
    assert json.loads(extract_json(raw)) == [{"a": 1}, {"a": 2}]


def test_extract_json_extracts_from_surrounding_prose():
    raw = 'Here is the result:\n{"a": 1}\nHope that helps.'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_extracts_before_trailing_prose():
    raw = '{"a": 1}\nHope that helps.'
    assert extract_json(raw) == '{"a": 1}'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_preserves_prose_wrapped_array():
    raw = 'Here is the result:\n[{"a": 1}]\nHope that helps.'
    parsed = json.loads(extract_json(raw))
    assert isinstance(parsed, list)
    assert parsed == [{"a": 1}]


def test_extract_json_accepts_uppercase_fence_language():
    raw = '```JSON\n{"a": 1}\n```'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_skips_invalid_fence_before_valid_json():
    raw = '```json\nnot json\n```\nActual result: {"a": 1}'
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_extract_json_returns_stripped_invalid_output():
    raw = "  totally not json  "
    assert extract_json(raw) == "totally not json"


def test_auto_linker_recovers_fenced_response_instead_of_dropping_it():
    """A valid fenced classification must not be treated as invalid JSON."""
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


def test_auto_linker_returns_none_on_unparseable_output():
    """Genuinely unparseable output (no JSON anywhere) still yields no link —
    fence tolerance must not turn garbage into a spurious relationship."""
    from ormah.background import auto_linker

    node = {"title": "A", "type": "fact", "space": "x", "content": "ca"}
    other = {"title": "B", "type": "fact", "space": "x", "content": "cb"}

    with mock.patch(
        "ormah.background.llm_client.llm_generate", return_value="totally not json"
    ):
        result = auto_linker._llm_classify_link(mock.Mock(), node, other)

    assert result is None

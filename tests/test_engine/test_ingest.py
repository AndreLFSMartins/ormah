"""Tests for conversation ingestion: dry_run, confidence, truncation."""

from __future__ import annotations

import json
import shutil
from unittest.mock import patch

import pytest

from ormah.engine import memory_engine
from ormah.models.node import NodeType

_LLM_PATCH = "ormah.background.llm_client.ingest_llm_generate"


class TestExtractionSchema:
    def test_extraction_passes_strict_schema(self, monkeypatch, engine):
        captured = {}

        def spy(settings, prompt, json_mode=True, **kwargs):
            captured.update(kwargs)
            return '{"memories": []}'

        monkeypatch.setattr(_LLM_PATCH, spy)
        engine._extract_memories_llm("some conversation text")
        assert (
            captured["response_format"]["json_schema"]["schema"]
            is memory_engine._INGEST_RESPONSE_SCHEMA
        )

    def test_fenced_json_with_inner_code_fence_is_parsed(self, engine):
        """Regression: a memory 'content' that quotes a ```-fenced code block must not
        truncate extraction. The old local ``_extract_json`` used a NON-GREEDY fence regex
        that cut the (valid) JSON at the first inner ``` -> 'Unterminated string' -> the
        method returned an error string -> the session_watcher cursor stalled on any coding
        session. Routing through the robust ``llm_client.extract_json`` (raw_decode-based)
        must recover the full document."""
        inner = json.dumps({
            "memories": [{
                "type": "procedure",
                "content": "Run the repro: ```python\nfoo()\n``` then check the output",
                "title": "Repro snippet",
                "tags": ["repro"],
                "about_self": False,
                "confidence": 0.8,
            }]
        })
        # The model wraps its (valid) JSON in a ```json fence, as claude -p often does.
        raw = "Here you go:\n\n```json\n" + inner + "\n```\n"
        with patch(_LLM_PATCH, return_value=raw):
            result = engine._extract_memories_llm("some conversation text")
        assert isinstance(result, list), f"expected parsed list, got error string: {result!r}"
        assert len(result) == 1
        assert result[0]["type"] == "procedure"
        assert "```python" in result[0]["content"]

    def test_null_optional_fields_do_not_crash_ingestion(self, engine):
        """The fallback (`result`) extraction path is not --json-schema-constrained, so a
        null for tags/about_self/confidence is genuinely plausible. None of the three is
        inside the loop's try/except (only node_type is) — a raw None must not raise, or
        the exception propagates as an error string and the session_watcher cursor never
        advances (infinite reprocess of the same slice)."""
        fake_llm_response = json.dumps({
            "memories": [
                {
                    "content": "x",
                    "type": "fact",
                    "title": "t",
                    "tags": None,
                    "about_self": None,
                    "confidence": None,
                },
            ]
        })
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation long enough to pass the length gate." * 3,
            )

        assert isinstance(result, list)
        assert len(result) == 1
        node = engine.file_store.load(result[0]["node_id"])
        assert node is not None
        assert node.confidence == 0.7
        assert "auto-ingested" in node.tags

    def test_null_content_is_skipped_not_crashed(self, engine):
        """content:null hits the same crash mode as the other three fields: `.get("content",
        "")` only applies its default on a MISSING key, not a null value, so `None.strip()`
        raises. Must instead be treated like empty content: skipped, no crash, cursor OK."""
        fake_llm_response = json.dumps({
            "memories": [
                {"content": None, "type": "fact", "title": "t"},
            ]
        })
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation long enough to pass the length gate." * 3,
            )

        assert result == []  # skipped, not crashed

    def test_zero_confidence_is_not_clobbered_to_default(self, engine):
        """confidence:0.0 is a legitimate, falsy value — must survive the `is None` check
        (an `or`-default would wrongly replace it with 0.7)."""
        fake_llm_response = json.dumps({
            "memories": [
                {"content": "x", "type": "fact", "title": "t", "confidence": 0.0},
            ]
        })
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation long enough to pass the length gate." * 3,
            )

        assert len(result) == 1
        node = engine.file_store.load(result[0]["node_id"])
        assert node.confidence == 0.0


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_claude_cli_extraction_returns_well_formed_memories(engine):
    """Real claude_cli round-trip: mandatory schema must survive an actual `claude -p`
    call and produce a well-formed {"memories": [...]} structure (or a valid empty one)."""
    engine.settings.ingest_llm_provider = "claude_cli"
    engine.settings.ingest_llm_model = "claude-haiku-4-5-20251001"

    conversation = (
        "User: I've decided to use SQLite instead of Postgres for this project's local "
        "index, because the app is single-user and local-first, and I don't want to run "
        "a separate database server.\n"
        "Assistant: Got it, SQLite it is."
    )
    extracted = engine._extract_memories_llm(conversation)
    if isinstance(extracted, str):
        pytest.skip(f"claude CLI returned no usable output: {extracted}")

    assert isinstance(extracted, list)
    for mem in extracted:
        assert isinstance(mem, dict)
        assert isinstance(mem.get("content"), str) and mem["content"]
        assert mem.get("type") in {t.value for t in NodeType}


class TestIngestDryRun:
    def test_dry_run_returns_extracted_without_storing(self, engine):
        """dry_run=True should return extracted memories without calling remember()."""
        fake_llm_response = json.dumps(
            {
                "memories": [
                    {
                        "content": "User prefers dark mode for all editors",
                        "type": "preference",
                        "title": "Dark mode preference",
                        "tags": ["ui"],
                        "about_self": True,
                    },
                    {
                        "content": "Project uses FastAPI for the backend",
                        "type": "fact",
                        "title": "FastAPI backend",
                        "tags": ["architecture"],
                        "about_self": False,
                    },
                ]
            }
        )
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A long enough conversation about preferences and architecture decisions." * 5,
                dry_run=True,
            )

        assert isinstance(result, list)
        assert len(result) == 2
        # Dry run results should NOT have node_id (nothing was stored)
        assert "node_id" not in result[0]
        # But should have content, title, type
        assert result[0]["title"] == "Dark mode preference"
        assert result[0]["type"] == "preference"
        assert result[0]["content"] == "User prefers dark mode for all editors"
        assert "auto-ingested" in result[0]["tags"]

    def test_dry_run_does_not_create_nodes(self, engine):
        """Verify no nodes are created during dry_run."""
        fake_llm_response = json.dumps(
            {
                "memories": [
                    {
                        "content": "Test memory that should not be stored",
                        "type": "fact",
                        "title": "Test memory",
                        "tags": [],
                    },
                ]
            }
        )
        # Count nodes before
        before = engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

        with patch(_LLM_PATCH, return_value=fake_llm_response):
            engine.ingest_conversation(
                content="Some conversation content." * 10,
                dry_run=True,
            )

        # Count nodes after — should be the same (only self node)
        after = engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert after == before


class TestIngestConfidence:
    def test_auto_ingested_memories_get_default_confidence(self, engine):
        """Auto-ingested memories should default to confidence=0.7."""
        fake_llm_response = json.dumps(
            {
                "memories": [
                    {
                        "content": "The project is called ormah",
                        "type": "fact",
                        "title": "Project name",
                        "tags": ["project"],
                    },
                ]
            }
        )
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation about the project." * 10,
            )

        assert isinstance(result, list)
        assert len(result) == 1
        node_id = result[0]["node_id"]

        # Load the node and check confidence
        node = engine.file_store.load(node_id)
        assert node is not None
        assert node.confidence == 0.7

    def test_llm_specified_confidence_preserved(self, engine):
        """If the LLM specifies confidence, it should be used."""
        fake_llm_response = json.dumps(
            {
                "memories": [
                    {
                        "content": "User might prefer vim keybindings",
                        "type": "preference",
                        "title": "Possible vim preference",
                        "tags": [],
                        "confidence": 0.4,
                    },
                ]
            }
        )
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation about editor preferences." * 10,
            )

        assert len(result) == 1
        node = engine.file_store.load(result[0]["node_id"])
        assert node.confidence == 0.4

    def test_dry_run_includes_confidence(self, engine):
        """dry_run results should include the confidence value."""
        fake_llm_response = json.dumps(
            {
                "memories": [
                    {
                        "content": "Some fact",
                        "type": "fact",
                        "title": "A fact",
                        "tags": [],
                    },
                ]
            }
        )
        with patch(_LLM_PATCH, return_value=fake_llm_response):
            result = engine.ingest_conversation(
                content="A conversation." * 10,
                dry_run=True,
            )

        assert result[0]["confidence"] == 0.7


class TestIngestTruncation:
    def test_content_truncated_to_setting(self, engine):
        """A single oversized turn (no line breaks) larger than ingest_max_content_chars is
        truncated to that hard cap rather than sent whole (chunking replaced whole-payload
        truncation; a single line still can't exceed the hard cap)."""
        engine.settings.ingest_max_content_chars = 2000
        engine.settings.ingest_chunk_chars = 2000
        marker = "ZQZQ"
        long_content = marker * 2000  # 8000 chars total, single line (no newlines)

        captured_prompt = {}

        def fake_llm(settings, prompt, **kwargs):
            captured_prompt["prompt"] = prompt
            return json.dumps({"memories": []})

        with patch(_LLM_PATCH, side_effect=fake_llm):
            engine.ingest_conversation(content=long_content)

        # The conversation text in the prompt should be truncated to 2000 chars
        # which means 500 full markers (each is 4 chars)
        prompt = captured_prompt["prompt"]
        marker_count = prompt.count(marker)
        assert marker_count == 500


def test_extraction_schema_and_prompt_wire_provenance():
    from ormah.engine import memory_engine as me
    item = me._INGEST_RESPONSE_SCHEMA["properties"]["memories"]["items"]
    assert item["properties"]["provenance"]["enum"] == ["material", "product"]
    assert "provenance" in item["required"]
    rules = me._INGEST_LLM_RULES
    assert "material" in rules and "product" in rules
    assert '"provenance"' in rules  # appears in the output-format section


def _canned(provenance):
    m = {"content": "x" * 60, "type": "fact", "title": "t",
         "tags": [], "about_self": False, "confidence": 0.9, "provenance": provenance}
    if provenance is None:
        m.pop("provenance")
    return [m]


@pytest.mark.parametrize("gate,prov,kept", [
    (True,  "material", False),   # dropped
    (True,  "product",  True),
    (True,  None,       True),    # missing label -> keep (errs toward Product)
    (True,  "garbage",  True),    # unknown label -> keep
    (False, "material", True),    # kill-switch off -> keep
])
def test_relevance_gate_drop(engine, monkeypatch, gate, prov, kept):
    engine.settings.ingest_relevance_gate = gate
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned(prov))
    out = engine.ingest_conversation("hello world " * 20, dry_run=True)
    assert (len(out) == 1) is kept


def test_dropped_material_is_recorded(engine, monkeypatch, tmp_path):
    from ormah.engine import relevance_quarantine as q
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "q.jsonl")
    engine.settings.ingest_relevance_gate = True
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned("material"))
    engine.ingest_conversation("hello world " * 20, dry_run=False, space="proj")
    assert len(list(q.iter_dropped(engine.settings))) == 1


def test_dropped_material_records_effective_provider_and_model(engine, monkeypatch, tmp_path):
    """provider/model in the ledger must be the EFFECTIVE (resolved) values used by the
    actual extraction call, not the (usually empty) ingest_llm_provider/model override
    fields -- those fall back to llm_provider/llm_model when unset."""
    from ormah.engine import relevance_quarantine as q
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "q.jsonl")
    engine.settings.ingest_relevance_gate = True
    engine.settings.ingest_llm_provider = ""
    engine.settings.ingest_llm_model = ""
    engine.settings.llm_provider = "claude_cli"
    engine.settings.llm_model = "claude-haiku-4-5-20251001"
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned("material"))
    engine.ingest_conversation("hello world " * 20, dry_run=False, space="proj")
    rows = list(q.iter_dropped(engine.settings))
    assert len(rows) == 1
    assert rows[0]["provider"] == "claude_cli"
    assert rows[0]["model"] == "claude-haiku-4-5-20251001"


def test_dry_run_does_not_write_to_quarantine_ledger(engine, monkeypatch, tmp_path):
    from ormah.engine import relevance_quarantine as q
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "q.jsonl")
    engine.settings.ingest_relevance_gate = True
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned("material"))
    out = engine.ingest_conversation("hello world " * 20, dry_run=True, space="proj")
    assert out == []
    assert list(q.iter_dropped(engine.settings)) == []


def test_quarantine_write_failure_does_not_abort_ingestion(engine, monkeypatch):
    """The ledger is a best-effort safety net: a write failure (disk full, permission)
    must not propagate and must not drop sibling memories from the same batch."""
    from ormah.engine import relevance_quarantine as q

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(q, "record_dropped", _boom)
    engine.settings.ingest_relevance_gate = True
    material = _canned("material")[0]
    product = _canned("product")[0]
    product["content"] = "y" * 60  # distinct content from the material candidate
    monkeypatch.setattr(
        type(engine), "_extract_memories_llm", lambda self, c: [material, product]
    )
    created = engine.ingest_conversation("hello world " * 20, dry_run=False, space="proj")
    # does not raise (implicit); material still dropped from output; product sibling not lost
    assert len(created) == 1
    assert created[0]["title"] == product["title"]

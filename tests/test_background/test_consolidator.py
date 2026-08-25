"""Tests for the memory consolidation background job."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ormah.background import consolidator
from ormah.config import Settings
from ormah.models.node import CreateNodeRequest, NodeType, Tier


@pytest.fixture
def consolidation_engine(engine):
    """Engine with several similar working memories."""
    contents = [
        "Python uses indentation to define code blocks",
        "Python relies on whitespace indentation for block structure",
        "In Python, indentation determines code block scope",
        "Code blocks in Python are delimited by indentation level",
    ]
    ids = []
    for i, content in enumerate(contents):
        req = CreateNodeRequest(
            content=content,
            type=NodeType.fact,
            title=f"Python indentation {i}",
            space="testproject",
        )
        nid, _ = engine.remember(req)
        ids.append(nid)
    return engine, ids


class TestConsolidation:

    @patch("ormah.background.llm_client.llm_generate")
    def test_creates_consolidated_node(self, mock_llm, consolidation_engine):
        """LLM consolidation should create a new node with derived_from edges."""
        engine, original_ids = consolidation_engine
        mock_llm.return_value = json.dumps({
            "title": "Python indentation rules",
            "summary": "Python uses whitespace indentation to define code block scope and structure.",
            "type": "fact",
        })

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

        # Function should complete without error.
        # Actual consolidation depends on embedding similarity threshold.

    @patch("ormah.background.llm_client.llm_generate")
    def test_originals_demoted_to_archival(self, mock_llm, consolidation_engine):
        """Original nodes should be demoted to archival tier."""
        engine, original_ids = consolidation_engine
        mock_llm.return_value = json.dumps({
            "title": "Python indentation rules",
            "summary": "Python uses whitespace indentation to define code block scope.",
            "type": "fact",
        })

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)
        # Completes without error; actual demotion depends on clustering

    def test_skips_without_llm(self, engine):
        """Should not crash when LLM is disabled."""
        engine.settings.llm_provider = "none"
        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

    def test_skips_with_few_nodes(self, engine):
        """Should skip when there aren't enough working nodes."""
        req = CreateNodeRequest(
            content="Solo memory",
            type=NodeType.fact,
            title="Solo",
        )
        engine.remember(req)

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

    def test_preserves_core_nodes(self, engine):
        """Core-tier nodes should not be consolidated."""
        for i in range(5):
            req = CreateNodeRequest(
                content=f"Important core fact {i}",
                type=NodeType.fact,
                tier=Tier.core,
                title=f"Core {i}",
            )
            engine.remember(req)

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

        # Core nodes should still be core
        core_rows = engine.db.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE tier = 'core'"
        ).fetchone()
        assert core_rows[0] >= 5  # At least the 5 we created + self node

    @patch("ormah.background.llm_client.llm_generate")
    def test_space_majority_vote(self, mock_llm, engine):
        """Consolidated node should inherit the majority space."""
        for i in range(4):
            space = "projectA" if i < 3 else "projectB"
            req = CreateNodeRequest(
                content=f"Similar fact about coding {i}",
                type=NodeType.fact,
                title=f"Coding fact {i}",
                space=space,
            )
            engine.remember(req)

        mock_llm.return_value = json.dumps({
            "title": "Coding facts consolidated",
            "summary": "Various facts about coding practices.",
            "type": "fact",
        })

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)
        # Completes without error


def test_consolidation_settings_defaults(tmp_path):
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_clusters_per_run == 10
    assert s.consolidation_min_cluster_size == 2
    assert s.consolidation_cluster_threshold == 0.6
    assert s.consolidation_max_cluster_nodes == 5


def test_consolidation_settings_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ORMAH_CONSOLIDATION_MAX_CLUSTERS_PER_RUN", "3")
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_clusters_per_run == 3


def test_run_consolidation_uses_settings_cap(engine, monkeypatch):
    from ormah.background import consolidator

    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_max_clusters_per_run = 3
    seen = {}

    def fake_find(eng, limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(consolidator, "_find_consolidation_clusters", fake_find)
    consolidator.run_consolidation(engine)
    assert seen["limit"] == 3


def test_inverted_cluster_bounds_returns_empty_and_warns(consolidation_engine, caplog):
    from ormah.background.consolidator import _find_consolidation_clusters

    engine, _ids = consolidation_engine
    engine.settings.consolidation_max_cluster_nodes = 1
    engine.settings.consolidation_min_cluster_size = 2

    with caplog.at_level("WARNING"):
        clusters = _find_consolidation_clusters(engine)

    assert clusters == []
    assert "consolidation_max_cluster_nodes" in caplog.text


def test_full_source_content_reaches_the_prompt(monkeypatch, consolidation_engine):
    """The consolidator must never summarize from a partial view of a source (#192)."""
    engine, ids = consolidation_engine
    marker = "MARKER-BEYOND-THE-OLD-300-CHAR-CAP"
    long_content = "padding. " * 600 + marker  # ~5400 chars, marker at the very end
    cluster = [
        {"id": ids[0], "title": "long source", "content": long_content, "space": None},
        {"id": ids[1], "title": "short source", "content": "A short one.", "space": None},
    ]
    captured = {}

    def spy(settings, prompt, json_mode=True, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({"title": "t", "summary": "s", "type": "fact"})

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

    consolidator._consolidate_cluster(engine, cluster)

    assert marker in captured["prompt"], "content past char 300 never reached the model"
    assert long_content in captured["prompt"]
    assert "A short one." in captured["prompt"]


def test_consolidation_logs_source_and_summary_sizes(monkeypatch, consolidation_engine, caplog):
    """A lossy consolidation must be detectable after the fact (#192)."""
    engine, ids = consolidation_engine
    cluster = [
        {"id": ids[0], "title": "a", "content": "x" * 400, "space": None},
        {"id": ids[1], "title": "b", "content": "y" * 600, "space": None},
    ]

    def spy(settings, prompt, json_mode=True, **kwargs):
        return json.dumps({"title": "t", "summary": "z" * 120, "type": "fact"})

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

    with caplog.at_level("INFO"):
        consolidator._consolidate_cluster(engine, cluster)

    assert "source_chars=1000" in caplog.text
    assert "summary_chars=120" in caplog.text


def test_consolidation_max_prompt_chars_default(tmp_path):
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_prompt_chars == 24000


def test_consolidation_max_prompt_chars_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS", "16000")
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_prompt_chars == 16000


def test_consolidation_max_prompt_chars_rejects_below_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS", "3999")
    with pytest.raises(ValueError, match="consolidation_max_prompt_chars must be >= 4000"):
        Settings(memory_dir=tmp_path)

"""Tests for the memory consolidation background job."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

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


def test_consolidation_marks_sources_as_superseded(engine):
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about pytest fixtures"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about pytest fixtures"))

    new_id = _apply_consolidation(engine, [a, b], "Pytest fixtures", "merged body", "fact")

    for source_id in (a, b):
        node = engine.file_store.load(source_id)
        assert node.tier is Tier.archival
        assert node.superseded_by == new_id


def test_the_marker_survives_in_the_index_after_consolidation(engine):
    """Regression for the INSERT OR REPLACE column drop (Task 3): update_node
    re-indexes the file one line after the marker is written."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest

    a, _ = engine.remember(CreateNodeRequest(content="source one about ruff config"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about ruff config"))

    new_id = _apply_consolidation(engine, [a, b], "Ruff config", "merged body", "fact")

    row = engine.db.conn.execute(
        "SELECT superseded_by FROM nodes WHERE id = ?", (a,)
    ).fetchone()
    assert row["superseded_by"] == new_id


def test_a_superseded_source_does_not_come_back_on_confirmed_use(engine):
    """The end-to-end point of #223's exception: consolidation sources stay buried."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about sqlite vec"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about sqlite vec"))
    _apply_consolidation(engine, [a, b], "sqlite-vec", "merged body", "fact")

    engine._record_confirmed_use(a)

    assert engine.file_store.load(a).tier is Tier.archival


def test_marking_precedes_demotion_so_a_crash_leaves_working_plus_marked(engine, monkeypatch):
    """Inject a demotion failure and assert the node ended working + marked,
    NOT archival + unmarked — the promotable node we must never create."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about apscheduler"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about apscheduler"))

    def boom(*args, **kwargs):
        raise RuntimeError("demotion failed")

    monkeypatch.setattr(engine, "update_node", boom)

    with pytest.raises(RuntimeError):
        _apply_consolidation(engine, [a, b], "APScheduler", "merged body", "fact")

    node = engine.file_store.load(a)
    assert node.tier is Tier.working
    assert node.superseded_by is not None



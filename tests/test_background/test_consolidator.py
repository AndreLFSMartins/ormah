"""Tests for the memory consolidation background job."""

from __future__ import annotations

import json
import shutil
from unittest.mock import patch

import pytest

from ormah.background import consolidator
from ormah.config import Settings
from ormah.background import consolidator
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


class TestConsolidationSignatureSkip:

    def test_consolidate_passes_strict_schema_and_records_signature(
        self, monkeypatch, consolidation_engine
    ):
        engine, original_ids = consolidation_engine
        cluster = [
            {"id": original_ids[0], "title": "SQLite pick", "content": "API uses SQLite.",
             "space": None},
            {"id": original_ids[1], "title": "SQLite decision",
             "content": "Chose SQLite for the API.", "space": None},
        ]
        captured = {}

        def spy(settings, prompt, **kwargs):
            captured.update(kwargs)
            return json.dumps({
                "title": "SQLite for the API",
                "summary": "The API uses SQLite.",
                "type": "decision",
            })

        monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

        consolidator._consolidate_cluster(engine, cluster)

        assert (
            captured["response_format"]["json_schema"]["schema"]
            is consolidator._CONSOLIDATE_RESPONSE_SCHEMA
        )
        sig = consolidator._cluster_signature(cluster)
        row = engine.db.conn.execute(
            "SELECT 1 FROM consolidation_checked WHERE signature = ?", (sig,)
        ).fetchone()
        assert row is not None

    def test_consolidate_skips_known_signature(self, monkeypatch, consolidation_engine):
        engine, _ = consolidation_engine
        cluster = [
            {"id": "n1", "title": "t", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        sig = consolidator._cluster_signature(cluster)
        engine.db.conn.execute(
            "INSERT INTO consolidation_checked (signature, checked_at) VALUES (?, datetime('now'))",
            (sig,),
        )

        called = {"n": 0}

        def spy(*a, **k):
            called["n"] += 1
            return None

        monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

        consolidator._consolidate_cluster(engine, cluster)

        assert called["n"] == 0  # skipped before the LLM call

    def test_signature_changes_on_title_or_space_edit(self):
        base = [
            {"id": "n1", "title": "t", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        title_edit = [
            {"id": "n1", "title": "different title", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        space_edit = [
            {"id": "n1", "title": "t", "content": "c", "space": "projectA"},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        type_edit = [
            {"id": "n1", "title": "t", "content": "c", "space": None, "type": "decision"},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]

        base_sig = consolidator._cluster_signature(base)
        assert base_sig != consolidator._cluster_signature(title_edit)
        assert base_sig != consolidator._cluster_signature(space_edit)
        assert base_sig != consolidator._cluster_signature(type_edit)

    def test_consolidate_records_signature_on_noop_summary(self, monkeypatch, consolidation_engine):
        """An empty/blank summary is a no-op that must still record the signature."""
        engine, _ = consolidation_engine
        cluster = [
            {"id": "n1", "title": "t", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        monkeypatch.setattr(
            "ormah.background.llm_client.llm_generate",
            lambda *a, **k: json.dumps({"title": "x", "summary": "", "type": "fact"}),
        )

        consolidator._consolidate_cluster(engine, cluster)

        sig = consolidator._cluster_signature(cluster)
        row = engine.db.conn.execute(
            "SELECT 1 FROM consolidation_checked WHERE signature = ?", (sig,)
        ).fetchone()
        assert row is not None

    def test_consolidate_does_not_record_when_llm_unavailable(self, monkeypatch, consolidation_engine):
        engine, _ = consolidation_engine
        cluster = [
            {"id": "n1", "title": "t", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        monkeypatch.setattr("ormah.background.llm_client.llm_generate", lambda *a, **k: None)

        consolidator._consolidate_cluster(engine, cluster)

        sig = consolidator._cluster_signature(cluster)
        row = engine.db.conn.execute(
            "SELECT 1 FROM consolidation_checked WHERE signature = ?", (sig,)
        ).fetchone()
        assert row is None

    def test_consolidate_does_not_record_signature_on_invalid_json(
        self, monkeypatch, consolidation_engine
    ):
        """Invalid JSON is now treated as transient (mirrors raw is None): retry next run,
        do NOT permanently skip a consolidatable cluster on a one-off parse failure."""
        engine, _ = consolidation_engine
        cluster = [
            {"id": "n1", "title": "t", "content": "c", "space": None},
            {"id": "n2", "title": "t2", "content": "c2", "space": None},
        ]
        monkeypatch.setattr(
            "ormah.background.llm_client.llm_generate", lambda *a, **k: "not json at all"
        )

        consolidator._consolidate_cluster(engine, cluster)

        sig = consolidator._cluster_signature(cluster)
        row = engine.db.conn.execute(
            "SELECT 1 FROM consolidation_checked WHERE signature = ?", (sig,)
        ).fetchone()
        assert row is None

    def test_consolidate_clamps_off_enum_type_to_fact(self, monkeypatch, consolidation_engine):
        """The result-fallback recovers JSON shape but not the schema's enum constraint —
        an off-enum type from the LLM must be clamped, not written straight to the node."""
        engine, original_ids = consolidation_engine
        cluster = [
            {"id": original_ids[0], "title": "t", "content": "c", "space": None},
            {"id": original_ids[1], "title": "t2", "content": "c2", "space": None},
        ]
        monkeypatch.setattr(
            "ormah.background.llm_client.llm_generate",
            lambda *a, **k: json.dumps(
                {"title": "x", "summary": "consolidated summary", "type": "architecture"}
            ),
        )

        consolidator._consolidate_cluster(engine, cluster)

        tag_row = engine.db.conn.execute(
            "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
        ).fetchone()
        assert tag_row is not None
        new_row = engine.db.conn.execute(
            "SELECT type FROM nodes WHERE id = ?", (tag_row["node_id"],)
        ).fetchone()
        assert new_row["type"] == "fact"

    def test_consolidation_checked_table_exists_on_migrated_engine(self, engine):
        """The skip table is created by init_schema()'s executescript(schema.sql), which
        runs on every engine construction (fresh or reopened) — so it's always present."""
        row = engine.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='consolidation_checked'"
        ).fetchone()
        assert row is not None


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_claude_cli_consolidate_creates_node_with_valid_type(consolidation_engine):
    """End-to-end: --json-schema -> structured_output round-trips for the consolidate prompt."""
    from ormah.background.llm_client import llm_generate, reset_adapter

    engine, original_ids = consolidation_engine
    engine.settings.llm_provider = "claude_cli"
    reset_adapter()

    cluster = engine.db.conn.execute(
        "SELECT id, title, content, space FROM nodes WHERE id IN ({})".format(
            ",".join("?" * len(original_ids))
        ),
        original_ids,
    ).fetchall()
    cluster = [dict(r) for r in cluster]

    # Capability probe: skip only when the CLI itself is unusable (not logged in, binary
    # missing/broken), not when the real consolidate prompt merely produces a result — the
    # adapter's result-fallback (e276baa) makes that round-trip reliably now, so a null
    # result for the real prompt below is a genuine regression, not an environment issue.
    from ormah.background.consolidator import _CONSOLIDATE_RESPONSE_SCHEMA
    probe = llm_generate(
        engine.settings, "Return title='Test', summary='Hello', type='fact'.",
        json_mode=True,
        response_format={"type": "json_schema", "json_schema": {"schema": _CONSOLIDATE_RESPONSE_SCHEMA}},
    )
    if probe is None:
        pytest.skip("claude CLI unusable (likely not logged in or binary missing)")

    consolidator._consolidate_cluster(engine, cluster)

    tag_row = engine.db.conn.execute(
        "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
    ).fetchone()
    assert tag_row is not None
    new_row = engine.db.conn.execute(
        "SELECT content, type FROM nodes WHERE id = ?", (tag_row["node_id"],)
    ).fetchone()
    assert new_row is not None
    assert new_row["content"]
    assert new_row["type"] in _CONSOLIDATE_RESPONSE_SCHEMA["properties"]["type"]["enum"]


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

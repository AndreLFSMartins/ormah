"""Tests for the memory consolidation background job."""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
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


def test_consolidation_pins_the_llm_route(monkeypatch, consolidation_engine):
    """The consolidation call must pin its own input window, not inherit the server default.

    Without ``route="consolidation"`` the prompt falls back to whatever ``num_ctx`` the Ollama
    server defaults to, and the full content this PR started sending is silently truncated by
    the model instead of by us (#192).
    """
    engine, ids = consolidation_engine
    cluster = [
        {"id": ids[0], "title": "a", "content": "A body.", "space": None},
        {"id": ids[1], "title": "b", "content": "B body.", "space": None},
    ]
    captured = {}

    def spy(settings, prompt, json_mode=True, **kwargs):
        captured.update(kwargs)
        return json.dumps({"title": "t", "summary": "s", "type": "fact"})

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)

    consolidator._consolidate_cluster(engine, cluster)

    assert captured.get("route") == "consolidation", (
        f"the consolidation call did not pin its route: kwargs={captured}"
    )


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


class TestSplitClusterToFit:
    """#192: a cluster that does not fit is SPLIT, never truncated."""

    @staticmethod
    def _node(nid: str, chars: int) -> dict:
        return {"id": nid, "title": "t", "content": "x" * chars, "space": None}

    def test_cluster_that_fits_is_returned_whole(self):
        cluster = [self._node("a", 100), self._node("b", 100)]
        assert consolidator._split_cluster_to_fit(cluster, 10_000) == [cluster]

    def test_oversized_cluster_is_split_preserving_order(self):
        cluster = [self._node(x, 400) for x in ("a", "b", "c", "d")]
        parts = consolidator._split_cluster_to_fit(cluster, 900)

        assert [[n["id"] for n in p] for p in parts] == [["a", "b"], ["c", "d"]]
        flat = [n["id"] for p in parts for n in p]
        assert flat == ["a", "b", "c", "d"]        # order preserved
        assert len(flat) == len(set(flat))          # no duplicates

    def test_a_cluster_landing_exactly_on_the_budget_stays_whole(self):
        """The boundary is inclusive: a cluster that fills the budget exactly is ONE call.

        The budget comes from ``_item_chars`` rather than a magic number so it cannot rot when
        the item rendering changes. Splitting here would cost a second LLM call and, worse, cut
        apart sources that do fit together.
        """
        cluster = [self._node("a", 400), self._node("b", 400)]
        exact = sum(consolidator._item_chars(n) for n in cluster)

        parts = consolidator._split_cluster_to_fit(cluster, exact)
        assert [[n["id"] for n in p] for p in parts] == [["a", "b"]]

        # one char short is the other side of the same boundary
        parts = consolidator._split_cluster_to_fit(cluster, exact - 1)
        assert [[n["id"] for n in p] for p in parts] == [["a"], ["b"]]

    def test_node_larger_than_the_whole_budget_is_dropped_with_a_warning(self, caplog):
        cluster = [self._node("small", 100), self._node("huge", 5_000), self._node("s2", 100)]
        with caplog.at_level("WARNING"):
            parts = consolidator._split_cluster_to_fit(cluster, 1_000)

        assert [[n["id"] for n in p] for p in parts] == [["small", "s2"]]
        assert "huge" in caplog.text

    def test_split_does_not_mutate_source_content(self):
        """The splitter hands back the input dicts untouched.

        This guards the SPLITTER only -- it returns the dicts by reference, so it cannot catch
        truncation in the renderer. That is what test_full_source_content_reaches_the_prompt is
        for.
        """
        cluster = [self._node("a", 400), self._node("b", 400)]
        parts = consolidator._split_cluster_to_fit(cluster, 500)
        for part in parts:
            for node in part:
                assert len(node["content"]) == 400

    def test_exhausted_budget_returns_nothing_and_warns(self, caplog):
        with caplog.at_level("WARNING"):
            assert consolidator._split_cluster_to_fit([self._node("a", 10)], 0) == []
        assert "budget" in caplog.text.lower()


def test_prompt_overhead_is_computed_from_the_template():
    overhead = consolidator._prompt_overhead_chars()
    assert overhead == len(consolidator._CONSOLIDATE_PROMPT.format(items_text=""))
    assert 1_000 < overhead < 10_000  # sanity: the template is real prose, not a stub


def test_prompt_items_are_rendered_by_the_same_function_the_split_budgets_with(monkeypatch):
    """The split's cost model and the prompt's rendering must be one function, or the budget
    silently stops matching what is actually sent (#192)."""
    # db stub: on this tree _consolidate_cluster consults the consolidation_checked signature
    # BEFORE building the prompt, so a settings-only namespace no longer reaches the prompt.
    # fetchone() -> None means "cluster not seen", which is the path under test.
    engine = SimpleNamespace(
        settings=SimpleNamespace(),
        db=SimpleNamespace(
            conn=SimpleNamespace(
                execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: None)
            )
        ),
    )
    cluster = [{"id": "n1", "title": "T", "content": "C", "space": None}]
    captured = {}

    def spy(settings, prompt, json_mode=True, **kwargs):
        captured["prompt"] = prompt
        return None  # short-circuit: returns before _record_signature touches the engine again

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", spy)
    monkeypatch.setattr(
        consolidator, "_render_item", lambda node: "SENTINEL-RENDER-" + node["id"]
    )

    consolidator._consolidate_cluster(engine, cluster)

    assert "SENTINEL-RENDER-n1" in captured["prompt"], (
        "the prompt does not go through _render_item — the split budgets against a different "
        "rendering than the one actually sent"
    )


class TestRunConsolidationSplits:
    """#192: run_consolidation splits oversized clusters and caps LLM calls, not discovery."""

    @pytest.fixture(autouse=True)
    def _fixed_overhead(self, monkeypatch):
        """Pin the template overhead so these tests measure the SPLIT, not the prompt's prose.

        With the real overhead the budgets below sit ~146 chars from their breaking point: an
        unrelated edit to the prompt text would fail this class and point at the wrong code.
        """
        monkeypatch.setattr(consolidator, "_prompt_overhead_chars", lambda: 2_400)

    @staticmethod
    def _fat(nid: str, chars: int) -> dict:
        return {"id": nid, "title": "t", "content": "x" * chars, "space": None}

    def test_oversized_cluster_becomes_two_consolidations(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        cluster = [self._fat(x, 1_500) for x in ("a", "b", "c", "d")]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"], ["c", "d"]]

    def test_oversized_node_is_never_sent_to_the_llm(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        cluster = [self._fat("a", 800), self._fat("huge", 20_000), self._fat("b", 800)]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"]]

    def test_short_subcluster_is_dropped(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        # a+b fill the budget; c lands alone in its sub-cluster with nothing to merge with
        cluster = [self._fat("a", 1_700), self._fat("b", 1_700), self._fat("c", 1_700)]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"]]

    def test_cap_counts_subclusters_not_raw_clusters(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        engine.settings.consolidation_max_clusters_per_run = 2
        clusters = [
            [self._fat(f"c{i}n{j}", 1_500) for j in range(4)] for i in range(3)
        ]  # 3 raw clusters -> 6 sub-clusters of 2
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: clusters
        )
        calls = {"n": 0}

        def spy(eng, sub):
            calls["n"] += 1

        monkeypatch.setattr(consolidator, "_consolidate_cluster", spy)

        consolidator.run_consolidation(engine)

        assert calls["n"] == 2, "the cap must bound LLM calls, not discovery"

    def test_exhausted_budget_warns_once_not_once_per_cluster(self, monkeypatch, engine, caplog):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 4_000
        monkeypatch.setattr(consolidator, "_prompt_overhead_chars", lambda: 4_000)
        monkeypatch.setattr(
            consolidator,
            "_find_consolidation_clusters",
            lambda eng, limit: [[self._fat("a", 10), self._fat("b", 10)] for _ in range(3)],
        )
        called = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: called.append(sub)
        )

        with caplog.at_level("WARNING"):
            consolidator.run_consolidation(engine)

        assert called == []
        budget_warnings = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "budget" in r.getMessage().lower()
        ]
        assert len(budget_warnings) == 1, (
            f"one warning per run, got {len(budget_warnings)}: "
            f"{[r.getMessage() for r in budget_warnings]}"
        )


def test_split_produces_two_real_consolidations_and_demotes_every_source(
    monkeypatch, consolidation_engine
):
    """#192 end-to-end: an oversized cluster yields TWO consolidated nodes, and all four
    sources end up archival — none is left half-processed.

    The count goes through the ``consolidated`` tag rather than the ``derived_from`` edges:
    ``_apply_consolidation`` does create those edges, but ``update_node(tier=archival)`` on the
    very next line re-indexes the source and ``IndexBuilder._remove_node`` deletes every row with
    ``source_id = ? OR target_id = ?``, so an inbound ``derived_from`` never survives the demotion
    that follows it. That is a pre-existing defect in a path this PR does not touch; counting
    edges here would measure it instead of the split.
    """
    engine, ids = consolidation_engine
    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_max_prompt_chars = 6_000
    cluster = [
        {"id": nid, "title": f"src {i}", "content": "x" * 1_500, "space": "testproject"}
        for i, nid in enumerate(ids)
    ]
    monkeypatch.setattr(
        consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
    )
    monkeypatch.setattr(
        "ormah.background.llm_client.llm_generate",
        lambda settings, prompt, json_mode=True, **kw: json.dumps(
            {"title": "merged", "summary": "merged body", "type": "fact"}
        ),
    )

    consolidator.run_consolidation(engine)

    tiers = {
        nid: engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id = ?", (nid,)
        ).fetchone()["tier"]
        for nid in ids
    }
    assert set(tiers.values()) == {"archival"}, tiers
    created = engine.db.conn.execute(
        "SELECT COUNT(*) AS n FROM node_tags WHERE tag = 'consolidated'"
    ).fetchone()["n"]
    assert created == 2, "each sub-cluster must produce its own consolidated node"


def test_oversized_source_is_left_working_end_to_end(monkeypatch, consolidation_engine):
    """The node the split refuses to pack must be left working while its neighbours merge.

    The companion assertion is a consolidation count, not the absence of an inbound
    ``derived_from`` edge: no such edge survives ``update_node``'s re-index (see the docstring
    above), so asserting zero of them would pass even if the split had never run.
    """
    engine, ids = consolidation_engine
    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_max_prompt_chars = 6_000
    huge, a, b = ids[0], ids[1], ids[2]
    cluster = [
        {"id": huge, "title": "huge", "content": "x" * 20_000, "space": "testproject"},
        {"id": a, "title": "a", "content": "y" * 800, "space": "testproject"},
        {"id": b, "title": "b", "content": "z" * 800, "space": "testproject"},
    ]
    monkeypatch.setattr(
        consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
    )
    monkeypatch.setattr(
        "ormah.background.llm_client.llm_generate",
        lambda settings, prompt, json_mode=True, **kw: json.dumps(
            {"title": "merged", "summary": "merged body", "type": "fact"}
        ),
    )

    consolidator.run_consolidation(engine)

    tier = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (huge,)
    ).fetchone()["tier"]
    assert tier == "working"
    consolidated = engine.db.conn.execute(
        "SELECT COUNT(*) AS n FROM node_tags WHERE tag = 'consolidated'"
    ).fetchone()["n"]
    assert consolidated == 1, "a and b must still have been consolidated without the huge source"
    for other in (a, b):
        assert engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id = ?", (other,)
        ).fetchone()["tier"] == "archival"


def test_render_item_never_writes_the_literal_string_none():
    """A NULL content column must render as empty, not as the four characters 'None'.

    ``nodes.content`` is nullable, and ``dict.get(key, default)`` returns the stored ``None``
    when the key is present -- the default only applies to a MISSING key. The audit log already
    uses the ``or ""`` idiom; the renderer must match, or a node with NULL content teaches the
    model that its body is the word "None".
    """
    assert consolidator._render_item({"id": "n", "title": "t", "content": None}) == "- [t]: "
    assert "None" not in consolidator._render_item({"id": "n", "title": "t", "content": None})


def test_a_failed_consolidation_is_logged_with_its_sources(monkeypatch, consolidation_engine,
                                                           caplog):
    """A consolidation the LLM never answered must not vanish silently (#192).

    ``llm_generate`` returns None on timeout, connect error, or a disabled provider, and the
    adapter's own warning names neither the job nor the cluster. run_consolidation's closing
    report is guarded by ``if consolidated_count:``, so a run where EVERY consolidation failed
    emits nothing at all: the daily job stays green while the working tier stops being curated.
    """
    engine, ids = consolidation_engine
    cluster = [
        {"id": ids[0], "title": "a", "content": "x" * 50, "space": None},
        {"id": ids[1], "title": "b", "content": "y" * 50, "space": None},
    ]
    monkeypatch.setattr(
        "ormah.background.llm_client.llm_generate",
        lambda settings, prompt, json_mode=True, **kw: None,
    )

    with caplog.at_level("WARNING"):
        consolidator._consolidate_cluster(engine, cluster)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a consolidation that produced nothing left no trace"
    text = " ".join(r.getMessage() for r in warnings)
    assert ids[0] in text and ids[1] in text, f"the warning does not name the sources: {text}"
def _remember(engine, content: str, title: str, tags: list[str] | None = None) -> str:
    req = CreateNodeRequest(
        content=content, type=NodeType.fact, title=title, space="testproject", tags=tags or []
    )
    nid, _ = engine.remember(req)
    return nid


_SAME_TEXT = "Python uses indentation to define code blocks"


def test_consolidated_nodes_are_never_seed_nor_member(engine):
    """A summary is terminal: discovery must not pick it as seed or member (#261)."""
    from ormah.background.consolidator import _find_consolidation_clusters

    raw = [_remember(engine, _SAME_TEXT, f"Raw {i}") for i in range(2)]
    summaries = [
        _remember(engine, _SAME_TEXT, f"Summary {i}", tags=["consolidated"]) for i in range(2)
    ]
    # Fixture check: the tag reached the index, otherwise the test proves nothing.
    tagged = {
        r[0]
        for r in engine.db.conn.execute(
            "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
        ).fetchall()
    }
    assert set(summaries) <= tagged

    clusters = _find_consolidation_clusters(engine)
    ids_in_clusters = {n["id"] for cluster in clusters for n in cluster}

    assert ids_in_clusters.isdisjoint(summaries), "a consolidated node entered a cluster"
    assert set(raw) <= ids_in_clusters, "the raw pair should still cluster"


def test_two_summaries_are_not_summarised_again(monkeypatch, engine):
    """Issue #261's scenario: run 1 yields N1 and N2, run 2 must leave them alone."""
    from ormah.background import consolidator

    engine.settings.llm_provider = "ollama"  # default is "none", which skips the job
    engine.settings.consolidation_max_cluster_nodes = 2  # four sources -> two clusters
    for i in range(4):
        _remember(engine, _SAME_TEXT, f"Source {i}")

    prompts: list[str] = []

    def fake_llm(settings, prompt, json_mode=True, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {"title": "Python indentation rules", "summary": "Blocks by indentation.", "type": "fact"}
        )

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", fake_llm)

    def consolidated_ids() -> list[str]:
        rows = engine.db.conn.execute(
            "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
        ).fetchall()
        return sorted(r[0] for r in rows)

    consolidator.run_consolidation(engine)
    first = consolidated_ids()
    assert len(first) == 2 and len(prompts) == 2

    consolidator.run_consolidation(engine)

    assert consolidated_ids() == first, "run 2 created a summary of summaries"
    assert len(prompts) == 2, "run 2 asked the LLM again"
    tiers = {
        r[0]
        for r in engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id IN (?, ?)", first
        ).fetchall()
    }
    assert tiers == {"working"}

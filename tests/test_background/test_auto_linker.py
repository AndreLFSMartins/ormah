"""Tests for LLM-based edge type classification in auto_linker."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

from ormah.models.node import CreateNodeRequest, NodeType

_LLM_PATCH = "ormah.background.llm_client.llm_generate"


def _create_pair(engine, title_a="Python language", content_a="Python is a programming language.",
                 title_b="Python lang", content_b="Python is a popular programming language.",
                 node_type=NodeType.fact):
    """Helper: create two similar nodes without auto-linking, return their IDs."""
    # Suppress auto-link during creation so run_auto_linker controls edge creation
    original_threshold = engine.settings.auto_link_similarity_threshold
    engine.settings.auto_link_similarity_threshold = 999.0
    try:
        id_a, _ = engine.remember(
            CreateNodeRequest(content=content_a, type=node_type, title=title_a, tags=["test"]),
            agent_id="test",
        )
        id_b, _ = engine.remember(
            CreateNodeRequest(content=content_b, type=node_type, title=title_b, tags=["test"]),
            agent_id="test",
        )
    finally:
        engine.settings.auto_link_similarity_threshold = original_threshold
    return id_a, id_b


def _edges_between(engine, id_a, id_b):
    """Return all edges between two nodes."""
    return engine.db.conn.execute(
        "SELECT edge_type FROM edges WHERE "
        "(source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)",
        (id_a, id_b, id_b, id_a),
    ).fetchall()


def _reset_adapter():
    from ormah.background.llm_client import reset_adapter
    reset_adapter()


def test_llm_classifies_supports(engine):
    """LLM classifies as supports -> edge created with type supports."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "relationship": "supports",
        "reason": "Both describe Python as a programming language.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    edges = _edges_between(engine, id_a, id_b)
    assert len(edges) >= 1
    assert edges[0]["edge_type"] == "supports"


def test_llm_classifies_contradicts(engine):
    """LLM classifies as contradicts -> edge created with type contradicts."""
    id_a, id_b = _create_pair(
        engine,
        title_a="Python is fast",
        content_a="Python is the fastest programming language.",
        title_b="Python is slow",
        content_b="Python is one of the slowest programming languages.",
    )

    llm_response = json.dumps({
        "relationship": "contradicts",
        "reason": "They make opposing claims about Python speed.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    edges = _edges_between(engine, id_a, id_b)
    assert len(edges) >= 1
    assert edges[0]["edge_type"] == "contradicts"


def test_llm_classifies_none_no_edge(engine):
    """LLM classifies as none -> no edge created."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "relationship": "none",
        "reason": "Not meaningfully related.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    edges = _edges_between(engine, id_a, id_b)
    assert len(edges) == 0


def test_llm_unavailable_skips_edge(engine):
    """LLM returns None -> no edge created (no heuristic fallback)."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=None):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    edges = _edges_between(engine, id_a, id_b)
    assert len(edges) == 0


def test_llm_disabled_skips_entirely(engine):
    """With llm_provider='none', LLM is never called and no edges are created."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "none"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    mock_llm = MagicMock()
    with patch(_LLM_PATCH, mock_llm):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    mock_llm.assert_not_called()

    edges = _edges_between(engine, id_a, id_b)
    assert len(edges) == 0


def test_checked_pairs_not_rechecked(engine):
    """Pairs already checked should not trigger a second LLM call on re-run."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "relationship": "none",
        "reason": "Not meaningfully related.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    mock_llm = MagicMock(return_value=llm_response)
    with patch(_LLM_PATCH, mock_llm):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    first_call_count = mock_llm.call_count
    assert first_call_count >= 1

    # Run again — the pair should be skipped
    mock_llm.reset_mock()
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)

    # LLM should not be called again for the same pair
    assert mock_llm.call_count == 0


def test_checked_pairs_recorded_for_none(engine):
    """Pairs classified as 'none' should be recorded in auto_link_checked."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "relationship": "none",
        "reason": "Not meaningfully related.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    pair = tuple(sorted([id_a, id_b]))
    row = engine.db.conn.execute(
        "SELECT result FROM auto_link_checked WHERE node_a = ? AND node_b = ?",
        pair,
    ).fetchone()
    assert row is not None
    assert row["result"] == "none"


def test_max_nodes_per_run_default(engine):
    assert engine.settings.auto_link_max_nodes_per_run == 500


def test_seq_bumped_on_rewrite(engine):
    """Re-writing a node's content bumps its seq to the head (crit#2 mechanism)."""
    from ormah.models.node import UpdateNodeRequest
    id_a, id_b = _create_pair(engine)
    seq_before = engine.db.conn.execute("SELECT seq FROM nodes WHERE id=?", (id_a,)).fetchone()["seq"]
    max_before = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    engine.update_node(id_a, UpdateNodeRequest(content="rewritten content"))
    seq_after = engine.db.conn.execute("SELECT seq FROM nodes WHERE id=?", (id_a,)).fetchone()["seq"]
    assert seq_after > seq_before
    assert seq_after > max_before  # landed at the head


def test_metadata_update_does_not_bump_seq(engine):
    """A direct metadata UPDATE (not via the builder) must not change seq."""
    id_a, _ = _create_pair(engine)
    before = engine.db.conn.execute("SELECT seq FROM nodes WHERE id=?", (id_a,)).fetchone()["seq"]
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET access_count = access_count + 1 WHERE id=?", (id_a,))
    after = engine.db.conn.execute("SELECT seq FROM nodes WHERE id=?", (id_a,)).fetchone()["seq"]
    assert after == before


def test_watermark_roundtrip(engine):
    from ormah.background.auto_linker import _get_watermark, _set_watermark
    assert _get_watermark(engine.db.conn) == 0
    _set_watermark(engine, 42)
    assert _get_watermark(engine.db.conn) == 42


def test_select_nodes_after_seq(engine):
    from ormah.background.auto_linker import _select_nodes_after
    id_a, id_b = _create_pair(engine)
    rows = _select_nodes_after(engine.db.conn, 0, limit=10)
    assert {id_a, id_b} <= {r["id"] for r in rows}
    last = rows[-1]
    rows2 = _select_nodes_after(engine.db.conn, last["seq"], limit=10)
    assert all(r["id"] != last["id"] for r in rows2)
    assert len(_select_nodes_after(engine.db.conn, 0, limit=1)) == 1


def test_run_advances_watermark(engine):
    from ormah.background.auto_linker import run_auto_linker, _get_watermark, _select_nodes_after
    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=json.dumps({"relationship": "none", "reason": "x"})):
        run_auto_linker(engine)
    last = _select_nodes_after(engine.db.conn, 0, limit=100)[-1]
    assert _get_watermark(engine.db.conn) == last["seq"]


def test_llm_none_does_not_advance_past_node(engine):
    """crit#1: a transient None must not let the watermark pass the node."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark
    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=None):
        run_auto_linker(engine)
    # No node fully resolved → watermark stays at 0
    assert _get_watermark(engine.db.conn) == 0
    # Next run with the LLM healthy re-evaluates the pair
    mock_llm = MagicMock(return_value=json.dumps({"relationship": "supports", "reason": "x"}))
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)
    assert mock_llm.call_count >= 1


def test_empty_vector_index_does_not_advance_watermark(engine):
    """Regression (#30): when node_vectors is empty/underfilled (e.g. mid full_rebuild,
    after vectors are deleted but before _reindex_all_embeddings restores them),
    vec_store.search returns no candidates. The watermark must NOT advance past those
    unchecked nodes, and once vectors are restored the pair must still be evaluated."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark

    id_a, id_b = _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    # Simulate the rebuild window: vectors gone, not yet restored.
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    mock_llm = MagicMock(return_value=json.dumps({"relationship": "supports", "reason": "x"}))
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)

    # Nothing could be checked → no LLM call, watermark stays at 0, no edge.
    assert mock_llm.call_count == 0
    assert _get_watermark(engine.db.conn) == 0
    assert len(_edges_between(engine, id_a, id_b)) == 0

    # Vectors restored → the pair is finally evaluated and the watermark advances.
    engine._reindex_all_embeddings()
    mock_llm2 = MagicMock(return_value=json.dumps({"relationship": "supports", "reason": "x"}))
    with patch(_LLM_PATCH, mock_llm2):
        run_auto_linker(engine)
    assert mock_llm2.call_count >= 1
    assert _get_watermark(engine.db.conn) > 0


def test_max_edges_does_not_skip_interrupted_node(engine):
    """imp#4: max_edges mid-run must not advance the watermark past unprocessed nodes."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark, _select_nodes_after
    # three mutually-similar nodes
    _create_pair(engine, title_a="A", content_a="shared topic alpha", title_b="B", content_b="shared topic alpha beta")
    _create_pair(engine, title_a="C", content_a="shared topic alpha gamma", title_b="D", content_b="shared topic alpha delta")
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.auto_link_max_edges_per_run = 1
    _reset_adapter()
    rows = _select_nodes_after(engine.db.conn, 0, limit=100)
    with patch(_LLM_PATCH, return_value=json.dumps({"relationship": "supports", "reason": "x"})):
        run_auto_linker(engine)
    wm = _get_watermark(engine.db.conn)
    assert wm < rows[-1]["seq"]  # did not reach the last node


def test_max_pairs_per_run_caps_llm_calls_and_does_not_skip_interrupted_node(engine):
    """#126: pairs_judged must cap LLM calls even when every verdict is 'none' (created stays 0),
    and the interrupted node must not be marked resolved (fail-closed, like max_edges)."""
    from ormah.background.auto_linker import run_auto_linker, _get_watermark, _select_nodes_after
    # four mutually-similar nodes -> node A alone has several candidate pairs
    _create_pair(engine, title_a="A", content_a="shared topic alpha", title_b="B", content_b="shared topic alpha beta")
    _create_pair(engine, title_a="C", content_a="shared topic alpha gamma", title_b="D", content_b="shared topic alpha delta")
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.auto_link_max_pairs_per_run = 1
    _reset_adapter()
    rows = _select_nodes_after(engine.db.conn, 0, limit=100)

    mock_llm = MagicMock(return_value=json.dumps({"relationship": "none", "reason": "x"}))
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)

    assert mock_llm.call_count == 1, "the run must stop after the first LLM judgement"
    wm = _get_watermark(engine.db.conn)
    assert wm < rows[-1]["seq"], "watermark must not advance past the interrupted node"


def test_full_rebuild_resets_watermark(engine):
    """A mass reindex must not leave a stale watermark hiding the whole store."""
    from ormah.background.auto_linker import _set_watermark, _get_watermark
    _create_pair(engine)
    _set_watermark(engine, 99999)
    engine.builder.full_rebuild()
    assert _get_watermark(engine.db.conn) == 0


def test_find_candidates_uses_window_without_advancing(engine):
    from ormah.background.auto_linker import _find_link_candidates, _get_watermark
    _create_pair(engine)
    engine.settings.auto_link_similarity_threshold = 0.0
    before = _get_watermark(engine.db.conn)
    cands = _find_link_candidates(engine, limit=8)
    assert all("node_a" in c and "node_b" in c and "similarity" in c for c in cands)
    assert _get_watermark(engine.db.conn) == before  # preview never advances the cursor


def test_invalid_llm_output_records_error_not_none(engine):
    """Malformed LLM JSON → recorded as result='error' (no edge), so the node resolves."""
    id_a, id_b = _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()
    with patch(_LLM_PATCH, return_value="not valid json"):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)
    assert len(_edges_between(engine, id_a, id_b)) == 0  # no edge
    pair = tuple(sorted([id_a, id_b]))
    row = engine.db.conn.execute(
        "SELECT result FROM auto_link_checked WHERE node_a=? AND node_b=?", pair
    ).fetchone()
    assert row is not None and row["result"] == "error"


def test_checked_pairs_invalidated_on_update(engine):
    """Updating a node's content should clear its checked pairs so it gets re-evaluated."""
    from ormah.models.node import UpdateNodeRequest

    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "relationship": "none",
        "reason": "Not meaningfully related.",
    })

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    pair = tuple(sorted([id_a, id_b]))
    row = engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone()
    assert row is not None  # pair was recorded

    # Update node A's content
    engine.update_node(id_a, UpdateNodeRequest(content="Completely different content now"))

    # Checked pair should be cleared
    row = engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone()
    assert row is None  # pair invalidated

    # Next run should re-evaluate the pair
    mock_llm = MagicMock(return_value=json.dumps({
        "relationship": "supports",
        "reason": "Now they are related.",
    }))
    with patch(_LLM_PATCH, mock_llm):
        run_auto_linker(engine)

    assert mock_llm.call_count >= 1  # LLM was called again for this pair


def test_pairs_evaluated_counts_one_candidate_pair(engine):
    """Issue #90: pairs_evaluated must reflect exactly one LLM decision call.

    Uses the default similarity threshold (not 0.0): the auto-created "Self"
    node is far enough below threshold that it does not count as a second
    candidate, leaving exactly the id_a/id_b pair.
    """
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(
        "ormah.background.auto_linker._llm_classify_link",
        return_value={"relationship": "none", "reason": "not related"},
    ):
        from ormah.background.auto_linker import run_auto_linker
        stats = run_auto_linker(engine)

    assert stats["pairs_attempted"] == 1
    assert stats["pairs_evaluated"] == 1


def test_pairs_attempted_counts_llm_unavailable_pair_but_not_evaluated(engine):
    """Issue #90 (council finding 2): an LLM-unavailable pair (None decision)
    must count as attempted but NOT as evaluated — otherwise pairs_per_s is
    inflated by calls that never produced a decision."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(
        "ormah.background.auto_linker._llm_classify_link",
        return_value=None,
    ):
        from ormah.background.auto_linker import run_auto_linker
        stats = run_auto_linker(engine)

    assert stats["pairs_attempted"] == 1
    assert stats["pairs_evaluated"] == 0


def test_pairs_attempted_counts_invalid_llm_output_but_not_evaluated(engine):
    """Issue #90 council R2 finding 2: the 'error' sentinel (invalid/malformed
    LLM output) must count as attempted but NOT as a valid evaluation — a
    degraded provider must not report healthy pairs_per_s with zero real
    decisions. duplicate_merger/conflict_detector already exclude their
    equivalent None-decision case; auto_linker's sentinel is a dict, not
    None, so it needs its own check."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(
        "ormah.background.auto_linker._llm_classify_link",
        return_value={"relationship": "error", "reason": "invalid LLM output"},
    ):
        from ormah.background.auto_linker import run_auto_linker
        stats = run_auto_linker(engine)

    assert stats["pairs_attempted"] == 1
    assert stats["pairs_evaluated"] == 0


# --- #87 pair batching ---

def test_link_prompt_is_composed_from_parts():
    from ormah.background import auto_linker as al
    assert al._LLM_LINK_PROMPT == (
        al._LLM_LINK_INTRO + "\n\n" + al._LLM_LINK_PAIR + "\n\n" + al._LLM_LINK_RULES
    )
    assert al._LLM_LINK_INSTRUCTIONS == al._LLM_LINK_INTRO + "\n\n" + al._LLM_LINK_RULES


def _seed_similar_nodes(engine, n=3):
    ids = []
    for _ in range(n):
        nid, _created = engine.remember(CreateNodeRequest(
            content="ormah uses sqlite-vec for vector search in the memory index",
            title="ormah vector search"))
        ids.append(nid)
    return ids


def test_batched_run_creates_edges_and_advances_watermark(engine):
    from ormah.background import auto_linker as al
    _seed_similar_nodes(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.maintenance_pairs_per_call = 2
    _reset_adapter()

    def fake_batch(settings, prompt, json_mode=True, **kw):
        n = prompt.count("### Pair ")
        return json.dumps({"verdicts": [
            {"pair_id": i, "relationship": "related_to", "reason": "same subsystem"}
            for i in range(n)]})

    single = MagicMock(return_value=json.dumps({"relationship": "related_to", "reason": "x"}))
    with patch("ormah.background.llm.pair_batch.llm_generate", fake_batch), \
            patch(_LLM_PATCH, single):
        stats = al.run_auto_linker(engine)

    edges = engine.db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'related_to'").fetchone()[0]
    assert edges >= 1
    assert stats["pairs_evaluated"] >= 1
    assert al._get_watermark(engine.db.conn) > 0


def test_outage_stops_after_first_window_and_blocks_watermark(engine):
    """Council C1 regression: LLM down -> exactly one batch attempt, watermark held."""
    from ormah.background import auto_linker as al
    _seed_similar_nodes(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.maintenance_pairs_per_call = 2
    _reset_adapter()
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        return None

    with patch("ormah.background.llm.pair_batch.llm_generate", down):
        al.run_auto_linker(engine)
    assert calls["n"] == 1
    assert al._get_watermark(engine.db.conn) == 0


def test_k1_stops_llm_calls_at_max_edges(engine):
    """Cursor regression: no pair is judged once the edge budget is spent (K=1 path)."""
    from ormah.background import auto_linker as al
    _seed_similar_nodes(engine, n=4)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    engine.settings.auto_link_max_edges_per_run = 1
    _reset_adapter()
    calls = {"n": 0}

    def single(settings, prompt, json_mode=True, **kw):
        calls["n"] += 1
        return json.dumps({"relationship": "related_to", "reason": "r"})

    with patch(_LLM_PATCH, single):
        al.run_auto_linker(engine)
    assert calls["n"] <= 2   # budget 1 -> at most the winning call + the boundary check


def test_vectorless_node_skipped_then_heals(engine):
    """A vectorless node must not kill the run: later nodes still get edges,
    the watermark parks BEFORE the orphan, and once the orphan's vector lands
    a later run advances past it (skip-then-heal)."""
    import numpy as np

    from ormah.background.auto_linker import _get_watermark, run_auto_linker
    from ormah.embeddings.vector_store import VectorStore
    from ormah.models.node import CreateNodeRequest

    # Orphan: lowest seq above the watermark, vector deleted.
    a_id, _ = engine.remember(
        CreateNodeRequest(title="orphan", content="a node whose vector was lost", tags=["test"])
    )
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (a_id,))

    id_b, id_c = _create_pair(engine)  # both embedded, similar

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    orphan_seq = engine.db.conn.execute(
        "SELECT seq FROM nodes WHERE id = ?", (a_id,)
    ).fetchone()["seq"]
    verdict = json.dumps({"relationship": "supports", "reason": "same topic"})

    with patch(_LLM_PATCH, return_value=verdict):
        stats = run_auto_linker(engine)

    assert len(_edges_between(engine, id_b, id_c)) >= 1  # pair linked despite orphan
    assert stats["pairs_attempted"] >= 1
    assert _get_watermark(engine.db.conn) < orphan_seq  # parked before the orphan

    # Heal: the orphan's vector lands (backfill), next run advances past it.
    dim = engine.settings.embedding_dim
    VectorStore(engine.db).upsert(a_id, np.ones(dim, dtype=np.float32))
    with patch(_LLM_PATCH, return_value=verdict):
        run_auto_linker(engine)

    assert _get_watermark(engine.db.conn) >= orphan_seq
def test_apply_edge_is_idempotent_when_edge_already_exists(engine):
    """A concurrent writer created the same edge between collection and apply.
    _apply_edge must not raise, and must still record the pair as checked."""
    from datetime import datetime, timezone
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'created by someone else')",
            (id_a, id_b, now),
        )

    _apply_edge(engine, id_a, id_b, "supports", "auto-linker reason", 0.8)

    # The pre-existing edge survives untouched; no duplicate was created.
    rows = engine.db.conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = 'supports'",
        (id_a, id_b),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "created by someone else"

    # The pair is marked checked -> it will never be re-judged. This is exactly what
    # the rollback used to erase, which is why the pair poisoned every future run.
    pair = tuple(sorted([id_a, id_b]))
    assert engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone() is not None


def test_apply_edge_does_not_duplicate_the_markdown_connection(engine):
    """The winner of the race already wrote its Connection to the file. We must not
    append a second one for the same (target, edge)."""
    from datetime import datetime, timezone
    from ormah.models.node import Connection, EdgeType
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'x')",
            (id_a, id_b, now),
        )
    node = engine.file_store.load(id_a)          # the winner persisted its markdown
    node.connections.append(Connection(target=id_b, edge=EdgeType.supports, weight=0.9))
    engine.file_store.save(node)

    _apply_edge(engine, id_a, id_b, "supports", "reason", 0.8)

    node = engine.file_store.load(id_a)
    assert len([c for c in node.connections if c.target == id_b]) == 1


def test_apply_edge_repairs_a_markdown_connection_the_winner_failed_to_save(engine):
    """The winner committed the DB row but crashed before saving its markdown. The
    file is the source of truth and a reindex rebuilds edges from it — so if we skip
    the append just because we lost the race, the next reindex deletes the edge while
    auto_link_checked stops the pair from ever being reconsidered. The link would be
    lost forever. We must repair the file instead. (Codex R1, critical #1.)"""
    from datetime import datetime, timezone
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    now = datetime.now(timezone.utc).isoformat()
    with engine.db.transaction() as conn:        # DB row exists, markdown does NOT
        conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
            "VALUES (?, ?, 'supports', 0.9, ?, 'winner crashed before saving md')",
            (id_a, id_b, now),
        )
    assert [c for c in engine.file_store.load(id_a).connections if c.target == id_b] == []

    _apply_edge(engine, id_a, id_b, "supports", "reason", 0.8)

    conns = [c for c in engine.file_store.load(id_a).connections if c.target == id_b]
    assert len(conns) == 1
    assert conns[0].edge.value == "supports"


def test_run_survives_an_edge_apply_failure(engine, monkeypatch):
    """A pair whose edge write blows up must not abort the whole run."""
    import json
    from unittest.mock import patch
    from ormah.background import auto_linker as al

    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0

    def boom(*_args, **_kwargs):
        raise RuntimeError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(al, "_apply_edge", boom)

    llm_response = json.dumps({"relationship": "supports", "reason": "r"})
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=llm_response):
        al.run_auto_linker(engine)   # must return normally, not raise

    # Fail closed: the watermark must NOT have advanced past the unresolved node.
    watermark = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'auto_link_watermark'"
    ).fetchone()
    assert watermark is None or int(watermark["value"]) == 0


def test_a_failing_pair_does_not_block_progress_on_earlier_nodes(engine, monkeypatch):
    """Progress, not just survival (Codex R1, critical #2): the failing pair parks the
    cursor AT that node, but every node before it still advances the watermark. Without
    this, the fix would only be swapping one kind of total stall for another."""
    import json
    from unittest.mock import patch
    from ormah.background import auto_linker as al

    # A first pair that links cleanly, then a second pair whose apply always fails.
    good_a, good_b = _create_pair(engine)
    bad_a, bad_b = _create_pair(
        engine, title_a="Rust language", content_a="Rust is a systems language.",
        title_b="Rust lang", content_b="Rust is a popular systems language.",
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0

    real_apply = al._apply_edge

    def apply_or_boom(eng, a_id, b_id, *args, **kwargs):
        if a_id in (bad_a, bad_b):
            raise RuntimeError("FOREIGN KEY constraint failed")
        return real_apply(eng, a_id, b_id, *args, **kwargs)

    monkeypatch.setattr(al, "_apply_edge", apply_or_boom)

    good_seq = engine.db.conn.execute(
        "SELECT seq FROM nodes WHERE id = ?", (good_b,)
    ).fetchone()["seq"]

    llm_response = json.dumps({"relationship": "supports", "reason": "r"})
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=llm_response):
        al.run_auto_linker(engine)

    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'auto_link_watermark'"
    ).fetchone()
    assert row is not None, "the run made no progress at all — the failing pair stalled everything"
    assert int(row["value"]) >= good_seq, "the clean nodes before the failing pair must advance"


def test_apply_edge_reports_whether_it_actually_created_the_edge(engine):
    """An INSERT OR IGNORE that inserted nothing is not a creation. Counting it as one
    burns the run's edge budget on a link someone else already made, and logs a
    creation that never happened (Codex R2, medium)."""
    from datetime import datetime, timezone
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)

    assert _apply_edge(engine, id_a, id_b, "supports", "r", 0.8) is True   # new edge

    # Same edge again: a concurrent writer already has it -> ignored, not created.
    now = datetime.now(timezone.utc).isoformat()
    assert now  # keep the import honest
    assert _apply_edge(engine, id_a, id_b, "supports", "r", 0.8) is False

    # 'none' records the pair as checked without ever creating an edge.
    id_c, id_d = _create_pair(
        engine, title_a="Go language", content_a="Go is a systems language.",
        title_b="Go lang", content_b="Go is a popular systems language.",
    )
    assert _apply_edge(engine, id_c, id_d, "none", "", 0.0) is False


def test_a_failed_markdown_save_does_not_leave_the_pair_marked_checked(engine, monkeypatch):
    """The markdown is the source of truth: a rebuild recreates the edge table from it.
    If the connection cannot be persisted, the pair must NOT stay marked as checked —
    otherwise the rebuild drops the DB-only edge and the checked row stops the pair from
    ever being judged again. The link would be lost for good (Codex, PR A round 2)."""
    import pytest
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)

    def boom(_node):
        raise OSError("disk full")

    monkeypatch.setattr(engine.file_store, "save", boom)

    with pytest.raises(OSError):
        _apply_edge(engine, id_a, id_b, "supports", "r", 0.8)

    pair = tuple(sorted([id_a, id_b]))
    assert engine.db.conn.execute(
        "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
    ).fetchone() is None, "the pair stayed checked, so it will never be judged again"

    # The edge WE inserted is rolled back too, or the collection guard would skip the
    # pair forever on the strength of a row whose markdown never existed.
    assert engine.db.conn.execute(
        "SELECT 1 FROM edges WHERE source_id = ? AND target_id = ?", (id_a, id_b)
    ).fetchone() is None
def test_run_auto_linker_reports_a_fatal_error_instead_of_returning_none(engine, monkeypatch):
    """A run that dies must say so in its return value — the job tracker and the admin
    route both read it. Returning None made a dead run look like a clean one (#117)."""
    from ormah.background import auto_linker as al

    engine.settings.llm_provider = "ollama"  # llm_enabled is derived from this

    def boom(*_a, **_kw):
        raise RuntimeError("vector store exploded")

    monkeypatch.setattr(al, "_get_watermark", boom)

    result = al.run_auto_linker(engine)

    assert isinstance(result, dict)
    assert "vector store exploded" in result["error"]
def test_apply_edge_writes_the_reason_into_the_markdown(engine):
    """The reason must reach the file, otherwise the next reindex erases it."""
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)
    _apply_edge(engine, id_a, id_b, "supports", "they agree about Python", 0.8)

    node = engine.file_store.load(id_a)
    conn = next(c for c in node.connections if c.target == id_b)
    assert conn.reason == "they agree about Python"


def test_a_non_string_llm_reason_does_not_cost_us_the_markdown_connection(engine):
    """The LLM can return JSON-valid garbage like {"reason": 123}. SQLite accepts the int
    and commits the edge + auto_link_checked, but Connection.reason is typed str|None, so
    building it raises — and the broad except swallows it, leaving the edge in the index
    with NO markdown connection. The next reindex then deletes the edge while the checked
    pair blocks reevaluation: the link is lost for good (Codex, PR C)."""
    from ormah.background.auto_linker import _apply_edge

    id_a, id_b = _create_pair(engine)

    _apply_edge(engine, id_a, id_b, "supports", 123, 0.8)   # non-string reason

    conns = [c for c in engine.file_store.load(id_a).connections if c.target == id_b]
    assert len(conns) == 1, "the edge was committed but the markdown connection was lost"
    assert conns[0].reason == "123"

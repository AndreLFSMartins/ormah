"""Tests for LLM-based duplicate consolidation in duplicate_merger."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

from ormah.models.node import CreateNodeRequest, NodeType

_LLM_PATCH = "ormah.background.llm_client.llm_generate"


def _create_pair(engine, title_a="Python language", content_a="Python is a programming language.",
                 title_b="Python lang", content_b="Python is a popular programming language.",
                 node_type=NodeType.fact):
    """Helper: create two similar nodes and return their IDs."""
    id_a, _ = engine.remember(
        CreateNodeRequest(content=content_a, type=node_type, title=title_a, tags=["test"]),
        agent_id="test",
    )
    id_b, _ = engine.remember(
        CreateNodeRequest(content=content_b, type=node_type, title=title_b, tags=["test"]),
        agent_id="test",
    )
    return id_a, id_b


def _reset_adapter():
    from ormah.background.llm_client import reset_adapter
    reset_adapter()


def test_llm_confirms_duplicate_auto_merge(engine):
    """LLM confirms duplicate -> auto-merge with merged content."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": True,
        "merged_title": "Python Programming Language",
        "merged_content": "Python is a popular programming language used widely.",
        "reason": "Both describe Python as a programming language.",
    })

    # Force auto-merge threshold low so the pair qualifies
    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    # One of the two nodes should have been removed; the kept one should
    # have the LLM-generated content.
    kept = engine.file_store.load(id_a) or engine.file_store.load(id_b)
    assert kept is not None
    assert kept.content == "Python is a popular programming language used widely."
    assert kept.title == "Python Programming Language"


def test_llm_rejects_duplicate_no_merge(engine):
    """LLM rejects duplicate -> no merge or proposal despite high composite score."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": False,
        "merged_title": "",
        "merged_content": "",
        "reason": "These describe different aspects of Python.",
    })

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    # Both nodes should still exist
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None


def test_llm_unavailable_skips_merge(engine):
    """LLM returns None -> pair is skipped, both nodes survive, no proposals."""
    id_a, id_b = _create_pair(engine)

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=None):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    # Both nodes should still exist
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None

    # No proposals
    proposals = engine.db.conn.execute(
        "SELECT * FROM proposals WHERE type = 'merge' AND status = 'pending'"
    ).fetchall()
    assert len(proposals) == 0


def test_llm_disabled_skips_detection(engine):
    """With llm_provider='none', LLM is never called."""
    id_a, id_b = _create_pair(engine)

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "none"
    _reset_adapter()

    mock_llm = MagicMock()
    with patch(_LLM_PATCH, mock_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    mock_llm.assert_not_called()


def test_merged_content_stored_in_proposal(engine):
    """For medium-confidence pairs, proposal contains merged content preview."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": True,
        "merged_title": "Python Programming Language",
        "merged_content": "Python is a popular programming language used widely.",
        "reason": "Both describe Python as a programming language.",
    })

    # Set threshold high so pair goes to proposal instead of auto-merge
    engine.settings.auto_merge_threshold = 0.99
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    # Both nodes should still exist (no auto-merge)
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None

    # A proposal should have been created with merged content preview
    proposals = engine.db.conn.execute(
        "SELECT * FROM proposals WHERE type = 'merge' AND status = 'pending'"
    ).fetchall()
    assert len(proposals) >= 1

    proposal = proposals[0]
    assert "Merged content preview:" in proposal["proposed_action"]
    assert "Python Programming Language" in proposal["proposed_action"]
    assert "Python is a popular programming language used widely." in proposal["proposed_action"]
    assert "Both describe Python" in proposal["reason"]


# --- #81 delta-selection ---

def _make_fact(engine, title, content):
    """Create a node without auto-linking; return (id, seq)."""
    original = engine.settings.auto_link_similarity_threshold
    engine.settings.auto_link_similarity_threshold = 999.0
    try:
        node_id, _ = engine.remember(
            CreateNodeRequest(content=content, type=NodeType.fact, title=title, tags=["test"]),
            agent_id="test",
        )
    finally:
        engine.settings.auto_link_similarity_threshold = original
    seq = engine.db.conn.execute("SELECT seq FROM nodes WHERE id = ?", (node_id,)).fetchone()["seq"]
    return node_id, seq


def test_dedup_finder_skips_seeds_at_or_below_watermark(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, set_watermark

    _make_fact(engine, "Python is dynamic", "Python is a dynamically typed language.")
    _make_fact(engine, "Python typing", "Python is a dynamically typed programming language.")

    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, DUPLICATE_WATERMARK_KEY, max_seq)
    candidates, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    assert candidates == [] and seeds == []
    # legacy mode (agent path) ignores the watermark entirely
    legacy = _find_merge_candidates(engine, limit=100)
    assert isinstance(legacy, list) and len(legacy) >= 1


def test_dedup_new_seed_pairs_with_old_neighbor(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, set_watermark

    old_id, old_seq = _make_fact(engine, "Server port", "The ormah server listens on port 8787.")
    set_watermark(engine, DUPLICATE_WATERMARK_KEY, old_seq)

    new_id, _ = _make_fact(engine, "Ormah port", "The ormah server runs on port 8787.")

    candidates, _ = _find_merge_candidates(engine, limit=100, delta=True)
    pair_ids = {(c["node_a"]["id"], c["node_b"]["id"]) for c in candidates}
    assert any(old_id in p and new_id in p for p in pair_ids)


def test_empty_vector_index_does_not_drain_dedup_seeds(engine):
    """Fail-closed (overview invariant): seed with text but no persisted
    vector must not drain (empty/backfilling node_vectors window)."""
    from ormah.background.duplicate_merger import _find_merge_candidates

    node_id, seq = _make_fact(engine, "Vectorless note", "A note whose vector is missing.")
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    _, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    assert (node_id, seq) not in seeds


def test_dedup_finder_delta_reports_drained_in_seq_order(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates

    made = [_make_fact(engine, f"Note {i}", f"Unrelated singleton note number {i}.")
            for i in range(3)]
    _, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    seed_ids = [s[0] for s in seeds]
    for node_id, _seq in made:
        assert node_id in seed_ids  # zero-candidate seeds still drained
    assert [s[1] for s in seeds] == sorted(s[1] for s in seeds)

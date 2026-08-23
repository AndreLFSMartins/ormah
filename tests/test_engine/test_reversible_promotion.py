"""Reversible promotion: archival nodes return to working on confirmed use (#223)."""

from __future__ import annotations

from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, Tier


def _archive(engine, content: str, superseded_by: str | None = None) -> str:
    node_id, _ = engine.remember(CreateNodeRequest(content=content))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.superseded_by = superseded_by
    engine.builder.index_single(engine.file_store.save(node))
    return node_id


def test_recall_node_promotes_exactly_the_requested_node(engine):
    """The archival NEIGHBOUR is the point: without it, an implementation that
    promotes every id in whisper_log_ids passes — and recall_node DOES create
    whisper_log rows for neighbours, in _log_feedback_candidates."""
    a = _archive(engine, "the node actually recalled")
    b = _archive(engine, "a connected neighbour that must stay archival")
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to))

    engine.recall_node(a)

    assert engine.file_store.load(a).tier is Tier.working
    assert engine.file_store.load(b).tier is Tier.archival


def test_a_generic_derived_from_target_still_promotes(engine):
    """derived_from is a general relationship; only marked sources are blocked.
    Testing only the marked node misses the block-everything bug the issue names."""
    plain = _archive(engine, "a derived_from target that was never superseded")
    marked = _archive(engine, "a genuinely superseded source", superseded_by="some-consolidation-id")

    engine._record_confirmed_use(plain)
    engine._record_confirmed_use(marked)

    assert engine.file_store.load(plain).tier is Tier.working
    assert engine.file_store.load(marked).tier is Tier.archival


def test_a_superseded_node_is_not_promoted_but_still_tracks_access(engine):
    """Blocking promotion must not silently swallow the access bookkeeping."""
    marked = _archive(engine, "superseded but still read", superseded_by="some-consolidation-id")
    before = engine.file_store.load(marked).access_count

    engine._record_confirmed_use(marked)

    after = engine.file_store.load(marked)
    assert after.tier is Tier.archival
    assert after.access_count == before + 1


def test_a_working_node_is_left_alone(engine):
    """promote() guards tier ordering; a working node must not be touched by the branch."""
    node_id, _ = engine.remember(CreateNodeRequest(content="already working"))
    engine.file_store.load(node_id)

    engine._record_confirmed_use(node_id)

    assert engine.file_store.load(node_id).tier is Tier.working


def test_promotion_is_written_to_the_index_too(engine):
    node_id = _archive(engine, "must land in SQL as well")

    engine._record_confirmed_use(node_id)

    row = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["tier"] == "working"

"""Conditional seq allocation driven by a persisted content fingerprint (#126)."""

from __future__ import annotations

from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType


def _row(engine, node_id: str):
    return engine.db.conn.execute(
        "SELECT seq, content_fingerprint FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()


def _seq(engine, node_id: str) -> int:
    return _row(engine, node_id)["seq"]


def _make_node(engine, title="Python language", content="Python is a programming language.",
               node_type=NodeType.fact, tags=None):
    node_id, _ = engine.remember(
        CreateNodeRequest(content=content, type=node_type, title=title,
                          tags=tags if tags is not None else ["test"]),
        agent_id="test",
    )
    return node_id


def test_indexing_persists_a_content_fingerprint(engine):
    """The builder stamps a fingerprint on every node it indexes."""
    node_id = _make_node(engine)
    fp = _row(engine, node_id)["content_fingerprint"]
    assert fp, "builder must persist a content fingerprint"
    assert len(fp) == 64, "expected a sha256 hex digest"


def test_edge_write_does_not_bump_seq(engine):
    """Persisting a connection must not requeue the node (#126).

    _apply_edge appends a Connection, touches `updated`, and saves the markdown. That
    rewrite used to bump `seq`, sending the node back to the end of the auto_linker queue
    with nothing new to learn — the pairs are already in auto_link_checked. That is what
    pinned the backlog at ~the size of the store.
    """
    id_a = _make_node(engine)
    id_b = _make_node(engine, title="Ruby language", content="Ruby is a programming language.")
    seq_before = _seq(engine, id_a)

    node = engine.file_store.load(id_a)
    node.connections.append(
        Connection(target=id_b, edge=EdgeType.related_to, weight=0.9, reason="both languages")
    )
    node.touch_updated()
    engine.builder.index_single(engine.file_store.save(node))

    assert _seq(engine, id_a) == seq_before, "an edge write must not requeue the node"

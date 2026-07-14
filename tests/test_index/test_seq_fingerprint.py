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

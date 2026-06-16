"""Tests for MemoryEngine._embed_node_rows (extracted embedding core, #32)."""
from __future__ import annotations

from ormah.models.node import CreateNodeRequest


def test_embed_node_rows_returns_embedded_ids(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Alpha", content="hello world"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    rows = engine.db.conn.execute(
        "SELECT id, title, content FROM nodes WHERE id = ?", (nid,)
    ).fetchall()

    embedded_ids, failed_ids = engine._embed_node_rows(rows)

    assert embedded_ids == [nid]
    assert failed_ids == []
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_embed_node_rows_reports_failed_ids(engine, monkeypatch):
    nid, _ = engine.remember(CreateNodeRequest(title="Boom", content="payload"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    rows = engine.db.conn.execute(
        "SELECT id, title, content FROM nodes WHERE id = ?", (nid,)
    ).fetchall()

    class _DeadEncoder:
        def encode(self, text):
            raise RuntimeError("encoder down")

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda settings: _DeadEncoder())

    embedded_ids, failed_ids = engine._embed_node_rows(rows)

    assert embedded_ids == []
    assert failed_ids == [nid]


def test_embed_node_rows_empty_list_is_noop(engine):
    embedded_ids, failed_ids = engine._embed_node_rows([])
    assert embedded_ids == []
    assert failed_ids == []

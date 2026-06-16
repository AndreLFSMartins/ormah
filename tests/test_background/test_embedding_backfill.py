"""Tests for the embedding_backfill reconciliation job (#32)."""
import pytest
from ormah.background.embedding_backfill import run_embedding_backfill
from ormah.models.node import CreateNodeRequest


def test_run_embedding_backfill_closes_gap(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Job", content="content"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    run_embedding_backfill(engine)
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_run_embedding_backfill_raises_when_incomplete(engine, monkeypatch):
    monkeypatch.setattr(engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 1, "missing": 1,
                 "vec_count": 0, "node_count": 1})
    with pytest.raises(RuntimeError, match="incomplete"):
        run_embedding_backfill(engine)


def test_run_embedding_backfill_ok_when_complete(engine, monkeypatch):
    monkeypatch.setattr(engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 0, "missing": 0,
                 "vec_count": 1, "node_count": 1})
    run_embedding_backfill(engine)  # must NOT raise

"""Auto-cluster: another no-LLM job that held L_mem for its whole run."""

from __future__ import annotations

from ormah.background.auto_cluster import run_auto_cluster
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType

from tests.test_background.lock_probe import install_probe


def _unassign(engine, node_id: str) -> None:
    engine.db.conn.execute("UPDATE nodes SET space = NULL WHERE id = ?", (node_id,))
    engine.db.conn.commit()


def _space_of(engine, node_id: str) -> str | None:
    row = engine.db.conn.execute(
        "SELECT space FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row["space"] if row else None


def _seeded_pair(engine, i: int) -> str:
    """One spaced anchor plus one unassigned neighbour edged to it."""
    anchor, _ = engine.remember(CreateNodeRequest(
        content=f"anchor {i}", type=NodeType.fact, title=f"anchor {i}", space="proj"))
    orphan, _ = engine.remember(CreateNodeRequest(
        content=f"orphan {i}", type=NodeType.fact, title=f"orphan {i}"))
    _unassign(engine, orphan)
    engine.connect(ConnectRequest(
        source_id=orphan, target_id=anchor, edge=EdgeType.related_to, weight=1.0))
    return orphan


def test_auto_cluster_assigns_from_neighbours(engine):
    orphan = _seeded_pair(engine, 0)
    run_auto_cluster(engine)
    assert _space_of(engine, orphan) == "proj"


def test_auto_cluster_takes_the_lock_per_node_not_once_per_run(engine):
    orphans = [_seeded_pair(engine, i) for i in range(3)]
    probe = install_probe(engine)
    run_auto_cluster(engine)

    assert all(_space_of(engine, o) == "proj" for o in orphans)
    # Before the fix: exactly 1, whatever the node count.
    assert probe.acquisitions >= 3


def test_auto_cluster_aborts_when_a_restore_lands_mid_run(engine):
    orphans = [_seeded_pair(engine, i) for i in range(3)]
    real_save = engine.file_store.save
    saves = {"count": 0}

    def bump_after_first(node):
        path = real_save(node)
        saves["count"] += 1
        if saves["count"] == 1:
            engine._restore_epoch += 1
        return path

    engine.file_store.save = bump_after_first
    run_auto_cluster(engine)  # returns cleanly

    assert saves["count"] == 1
    assert sum(_space_of(engine, o) == "proj" for o in orphans) == 0

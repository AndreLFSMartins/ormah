"""auto_cluster must not propagate the placeholder 'null' space (#22 council follow-up).

auto_cluster assigns unassigned nodes the majority space of their neighbors, writing
both the index (raw SQL UPDATE) and the markdown file (node.space). Both writes must
stay clean if a stale neighbor still carries the literal 'null' string.
"""

from __future__ import annotations

from ormah.background.auto_cluster import run_auto_cluster
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType


def _connect(engine, a, b):
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to))


def test_auto_cluster_assigns_real_neighbor_space(engine):
    """Happy path still works: an unassigned node inherits a real neighbor space."""
    a, _ = engine.remember(CreateNodeRequest(content="unassigned", type=NodeType.fact))
    b, _ = engine.remember(
        CreateNodeRequest(content="neighbor", type=NodeType.fact, space="work")
    )
    _connect(engine, a, b)

    run_auto_cluster(engine)

    assert engine.file_store.load(a).space == "work"


def test_auto_cluster_does_not_propagate_placeholder_space(engine):
    a, _ = engine.remember(CreateNodeRequest(content="unassigned", type=NodeType.fact))
    b, _ = engine.remember(
        CreateNodeRequest(content="neighbor", type=NodeType.fact, space="work")
    )
    _connect(engine, a, b)
    # Simulate a stale, pre-migration neighbor carrying the literal placeholder.
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET space = 'null' WHERE id = ?", (b,))

    run_auto_cluster(engine)

    # The unassigned node stays unassigned — it must not inherit the phantom 'null'.
    assert engine.file_store.load(a).space is None
    index_space = engine.db.conn.execute(
        "SELECT space FROM nodes WHERE id = ?", (a,)
    ).fetchone()[0]
    assert index_space is None
    # auto_cluster added no new 'null' rows (only the one we injected on b remains).
    nulls = engine.db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE space = 'null'"
    ).fetchone()[0]
    assert nulls == 1

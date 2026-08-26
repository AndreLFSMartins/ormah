"""auto_cluster must not propagate the placeholder 'null' space (#22 council follow-up).

auto_cluster assigns unassigned nodes the majority space of their neighbors, writing
both the index (raw SQL UPDATE) and the markdown file (node.space). Both writes must
stay clean if a stale neighbor still carries the literal 'null' string.
"""

from __future__ import annotations

from ormah.background.auto_cluster import run_auto_cluster
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType
from tests.test_background.lock_probe import install_probe


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


def test_auto_cluster_skips_space_locked_node(engine):
    """A user-curated global (space_locked) keeps its None space despite project neighbors."""
    a, _ = engine.remember(
        CreateNodeRequest(content="global pref", type=NodeType.preference, space_locked=True)
    )
    b, _ = engine.remember(
        CreateNodeRequest(content="neighbor", type=NodeType.fact, space="work")
    )
    _connect(engine, a, b)

    run_auto_cluster(engine)

    assert engine.file_store.load(a).space is None


def test_auto_cluster_skips_self_node(engine):
    """The self/identity node is never swept into a project space."""
    uid = engine.user_node_id
    b, _ = engine.remember(
        CreateNodeRequest(content="neighbor", type=NodeType.fact, space="work")
    )
    _connect(engine, uid, b)

    run_auto_cluster(engine)

    assert engine.file_store.load(uid).space is None


def test_auto_cluster_rechecks_stale_index_lock(engine):
    """Markdown is source of truth: a node locked in the file but stale-unlocked in the
    index must not be reassigned (#22 council B)."""
    a, _ = engine.remember(
        CreateNodeRequest(content="global pref", type=NodeType.preference, space_locked=True)
    )
    b, _ = engine.remember(
        CreateNodeRequest(content="neighbor", type=NodeType.fact, space="work")
    )
    _connect(engine, a, b)
    # Simulate a stale index row: file says locked, index says unlocked + no space.
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET space_locked = 0, space = NULL WHERE id = ?", (a,))

    run_auto_cluster(engine)

    node = engine.file_store.load(a)
    assert node.space is None
    assert node.space_locked is True
    # The stale index row is healed so the node stops resurfacing in the unassigned query.
    healed = engine.db.conn.execute(
        "SELECT space_locked FROM nodes WHERE id = ?", (a,)
    ).fetchone()[0]
    assert healed == 1


def test_migrate_lock_identity_spaces_relocks_legacy(engine):
    """Startup migration re-locks legacy identity memories once (#22 council C)."""
    sid, _ = engine.remember(
        CreateNodeRequest(content="André is stoic.", type=NodeType.preference, about_self=True)
    )
    # Simulate a legacy/upgraded node: swept into a project space, unlocked, in file + index.
    n = engine.file_store.load(sid)
    n.space = "ormah"
    n.space_locked = False
    engine.file_store.save(n)
    with engine.db.transaction() as conn:
        conn.execute("UPDATE nodes SET space = 'ormah', space_locked = 0 WHERE id = ?", (sid,))
        conn.execute("DELETE FROM meta WHERE key = 'identity_space_locked_migrated'")

    engine._migrate_lock_identity_spaces()

    node = engine.file_store.load(sid)
    assert node.space is None
    assert node.space_locked is True
    # Idempotent: the guard meta key is set, a second run is a no-op.
    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'identity_space_locked_migrated'"
    ).fetchone()
    assert row["value"] == "1"


def test_repair_global_identity_relocks_swept_cluster(engine):
    """The repair resets a swept identity cluster back to global + locked."""
    from ormah.store.migrations import repair_global_identity

    uid = engine.user_node_id
    sid, _ = engine.remember(
        CreateNodeRequest(content="André runs triathlons.", type=NodeType.fact, about_self=True)
    )
    # Simulate the pre-fix damage: both pulled into a project space, unlocked.
    for nid in (uid, sid):
        n = engine.file_store.load(nid)
        n.space = "ormah"
        n.space_locked = False
        engine.file_store.save(n)

    fixed, _ = repair_global_identity(engine.settings.nodes_dir, engine.settings.db_path)

    assert fixed >= 2
    for nid in (uid, sid):
        n = engine.file_store.load(nid)
        assert n.space is None
        assert n.space_locked is True


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


def test_a_space_assigned_after_the_scan_is_not_overwritten(engine):
    """auto_cluster's candidate query says 'no space'; revalidate before writing one."""
    orphan = _seeded_pair(engine, 0)
    assigned_by_user = {"done": False}

    real_load = engine.file_store.load

    def assign_then_load(node_id):
        """file_store.load is the first thing the apply step does; the user write lands
        just before it, standing in for one that arrived after the candidate query."""
        if not assigned_by_user["done"] and node_id == orphan:
            assigned_by_user["done"] = True
            node = real_load(node_id)
            node.space = "chosen-by-user"
            node.touch_updated()
            real_save(node)
            engine.db.conn.execute(
                "UPDATE nodes SET space = 'chosen-by-user' WHERE id = ?", (orphan,))
            engine.db.conn.commit()
        return real_load(node_id)

    real_save = engine.file_store.save
    engine.file_store.load = assign_then_load

    run_auto_cluster(engine)

    assert assigned_by_user["done"], "the apply step never ran — the fixture stopped exercising the job"
    assert _space_of(engine, orphan) == "chosen-by-user"

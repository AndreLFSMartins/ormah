"""Tests for the decay manager background job."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


from ormah.background.decay_manager import run_decay
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier


def _make_stale(engine, node_id: str, days: int = 30) -> None:
    """Set a node's last_accessed to `days` ago."""
    stale_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ? WHERE id = ?", (stale_date, node_id)
    )
    engine.db.conn.commit()


def _get_tier(engine, node_id: str) -> str:
    row = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return row["tier"] if row else None


def test_high_importance_stale_node_is_decayed(engine):
    """#222: importance is no longer a pre-gate — a stale node decays regardless.

    Before #222 a node with importance >= decay_importance_threshold (0.5) could
    never leave working, however stale it became.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Important stale node",
        type=NodeType.fact,
        tier=Tier.working,
        title="Important",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.9 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_accumulated_access_and_edges_do_not_pin_a_node_to_working(engine):
    """The reported case: 50 accesses + 4 edges produce a permanent non-recency
    importance contribution of ~0.514, above the old 0.5 gate. That node must
    still decay once it goes stale."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Hub node with long access history",
        type=NodeType.concept,
        tier=Tier.working,
        title="Hub",
    ))

    for i in range(4):
        sat_id, _ = engine.remember(CreateNodeRequest(
            content=f"Satellite of the hub number {i}",
            type=NodeType.fact,
            tier=Tier.working,
        ))
        engine.connect(ConnectRequest(
            source_id=node_id,
            target_id=sat_id,
            edge=EdgeType.related_to,
        ))

    engine.db.conn.execute(
        "UPDATE nodes SET access_count = 50, importance = 0.5145 WHERE id = ?",
        (node_id,),
    )
    engine.db.conn.commit()
    _make_stale(engine, node_id)

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_fresh_high_importance_node_stays_working(engine):
    """The negative case (council I2): retrievability still decides.

    Removing the importance gate must not turn decay into "demote everything".
    A fresh node has R ~= 1.0 and stays working whatever its importance. Without
    this test, deleting the retrievability check would leave the suite green.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Fresh node that must not decay",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh",
    ))

    # Deliberately NOT made stale.
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.9 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"


def test_fresh_low_importance_node_stays_working(engine):
    """Same guard from the other side: low importance alone never demotes."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Fresh unimportant node that must not decay",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh unimportant",
    ))

    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.05 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"


def test_self_node_is_never_decayed(engine):
    """Identity protection survives the removal of the importance gate."""
    user_node_id = getattr(engine, "user_node_id", None)
    # Fail closed, not skip (council I2): MemoryEngine.startup() calls
    # _ensure_self_node(), which creates the self node if absent, so a missing
    # one means the fixture broke — silently skipping would hide that.
    assert user_node_id is not None, "engine fixture must provide a self node"

    _make_stale(engine, user_node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET tier = 'working', importance = 0.1 WHERE id = ?",
        (user_node_id,),
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, user_node_id) == "working"


def test_low_importance_stale_node_decayed(engine):
    """A stale node with low importance should be demoted to archival."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Unimportant stale node",
        type=NodeType.fact,
        tier=Tier.working,
        title="Unimportant",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.2 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_decay_still_works_without_importance(engine):
    """Low importance (0.3) + stale should trigger decay (0.3 < 0.5 threshold)."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Default importance stale node",
        type=NodeType.fact,
        tier=Tier.working,
        title="Default",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.3 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_decay_is_idempotent(engine):
    """Running decay twice should not error; node stays archival after both runs."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Node that will go stale",
        type=NodeType.fact,
        tier=Tier.working,
        title="Stale node",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.2 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)
    assert _get_tier(engine, node_id) == "archival"

    # Second run should not error
    run_decay(engine)
    assert _get_tier(engine, node_id) == "archival"


def test_decay_writes_audit_log(engine):
    """Demoted nodes should have an audit log entry recording the tier change."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Node with known importance",
        type=NodeType.fact,
        tier=Tier.working,
        title="Audit test",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.35 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    row = engine.db.conn.execute(
        "SELECT detail FROM audit_log WHERE node_id = ? AND operation = 'update' "
        "ORDER BY performed_at DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    assert row is not None
    detail = json.loads(row["detail"])
    assert "tier" in detail["changed_fields"]


def test_decay_cleans_pending_proposals(engine):
    """Legacy pending decay proposals should be cleaned up on run."""
    # Insert a fake legacy decay proposal
    engine.db.conn.execute(
        "INSERT INTO proposals (id, type, status, source_nodes, proposed_action, reason, created) "
        "VALUES ('legacy-1', 'decay', 'pending', '[\"fake-id\"]', 'Demote to archival: test', 'test', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    engine.db.conn.commit()

    count_before = engine.db.conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE type = 'decay' AND status = 'pending'"
    ).fetchone()[0]
    assert count_before == 1

    run_decay(engine)

    count_after = engine.db.conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE type = 'decay' AND status = 'pending'"
    ).fetchone()[0]
    assert count_after == 0

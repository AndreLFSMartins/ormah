from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ormah.background.forgetting_manager import run_forgetting
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier


def _exists(engine, node_id) -> bool:
    row = engine.db.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row is not None


def _enable(engine):
    engine.settings.deletion_enabled = True


def _make_eligible(engine, content="dead weight", days=200):
    """Create an archival node eligible in BOTH file and index (the guard reads the file)."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content=content, type=NodeType.fact, tier=Tier.archival, title=content))
    old = datetime.now(timezone.utc) - timedelta(days=days)
    node = engine.file_store.load(node_id)
    node.importance = 0.1
    node.stability = 1.0
    node.last_review = old
    node.last_accessed = old
    node.archived_at = old
    path = engine.file_store.save(node)        # source of truth
    engine.builder.index_single(path)          # keep the index in sync
    engine.db.conn.commit()
    return node_id


def test_master_switch_off_is_noop(engine):
    node_id = _make_eligible(engine)
    run_forgetting(engine)  # deletion_enabled defaults to False
    assert _exists(engine, node_id) is True


def test_fully_eligible_node_is_soft_deleted(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    assert _exists(engine, node_id) is False


def test_idempotent_second_run_deletes_nothing(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    run_forgetting(engine)
    assert _exists(engine, node_id) is False


# --- conjunction matrix: passing all gates deletes; breaking exactly one keeps (council M1) ---

def _break(engine, node_id, gate):
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    if gate == "tier":
        engine.db.conn.execute("UPDATE nodes SET tier='working' WHERE id=?", (node_id,))
    elif gate == "archived_recent":
        engine.db.conn.execute("UPDATE nodes SET archived_at=? WHERE id=?", (recent, node_id))
    elif gate == "accessed_recent":
        engine.db.conn.execute("UPDATE nodes SET last_accessed=? WHERE id=?", (recent, node_id))
    elif gate == "retrievable":   # high stability ⇒ R well above floor
        engine.db.conn.execute("UPDATE nodes SET stability=100000.0 WHERE id=?", (node_id,))
    elif gate == "importance":
        engine.db.conn.execute("UPDATE nodes SET importance=0.9 WHERE id=?", (node_id,))
    elif gate == "archived_null":
        engine.db.conn.execute("UPDATE nodes SET archived_at=NULL WHERE id=?", (node_id,))
    elif gate == "feedback":
        engine.db.conn.execute(
            "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
            "VALUES (?, ?, 1, 'explicit', ?, 's1')", (b"\x00", node_id, recent))
    engine.db.conn.commit()


@pytest.mark.parametrize("gate", [
    "tier", "archived_recent", "accessed_recent", "retrievable",
    "importance", "archived_null", "feedback",
])
def test_breaking_one_gate_keeps_node(engine, gate):
    _enable(engine)
    node_id = _make_eligible(engine)
    _break(engine, node_id, gate)
    run_forgetting(engine)
    assert _exists(engine, node_id) is True, f"gate={gate} should have protected the node"


def test_strong_edge_protects_both_nodes(engine):
    _enable(engine)
    a = _make_eligible(engine, content="hub a")
    b = _make_eligible(engine, content="hub b")
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to, weight=0.9))
    run_forgetting(engine)
    assert _exists(engine, a) is True and _exists(engine, b) is True


def test_user_node_never_deleted(engine):
    _enable(engine)
    uid = engine.user_node_id
    assert uid is not None
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET tier='archival', importance=0.1, stability=1.0, "
        "last_review=?, last_accessed=?, archived_at=? WHERE id=?",
        (old, old, old, uid))
    engine.db.conn.commit()
    run_forgetting(engine)
    assert _exists(engine, uid) is True


def test_guard_reads_file_over_stale_index(engine):
    """Cross-path race (council R3 C5): a promotion writes the FILE before the index.

    The pre-filter (index) still sees archival+stale and selects the node, but the hybrid guard
    reads the source file (tier=working) and aborts. Fails with an index-only guard.
    """
    _enable(engine)
    node_id = _make_eligible(engine)
    node = engine.file_store.load(node_id)
    node.tier = Tier.working
    engine.file_store.save(node)  # file promoted; index intentionally NOT updated
    run_forgetting(engine)
    assert _exists(engine, node_id) is True  # guard saw the fresh file → no deletion

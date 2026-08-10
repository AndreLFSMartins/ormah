from __future__ import annotations

import threading
from datetime import datetime, timezone

from ormah.models.node import CreateNodeRequest, NodeType, Tier


def _archival(engine):
    node_id, _ = engine.remember(CreateNodeRequest(
        content="g", type=NodeType.fact, tier=Tier.archival, title="g"))
    return node_id


def _exists(engine, node_id):
    return engine.db.conn.execute(
        "SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone() is not None


def test_guard_false_aborts_deletion(engine):
    node_id = _archival(engine)
    res = engine.delete_node_guarded(node_id, lambda conn: False)
    assert res is None
    assert _exists(engine, node_id) is True


def test_guard_true_deletes(engine):
    node_id = _archival(engine)
    res = engine.delete_node_guarded(node_id, lambda conn: True)
    assert res is not None and res.startswith("Deleted")
    assert _exists(engine, node_id) is False


def test_guard_observes_writes_in_same_transaction(engine):
    """A +feedback row inserted inside the guard's txn is visible to the guard's recheck."""
    node_id = _archival(engine)

    def guard(conn):
        conn.execute(
            "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
            "VALUES (?, ?, 1, 'explicit', ?, 's1')",
            (b"\x00", node_id, datetime.now(timezone.utc).isoformat()))
        row = conn.execute(
            "SELECT 1 FROM affinity WHERE node_id=? AND signal>0 LIMIT 1", (node_id,)
        ).fetchone()
        return row is None  # protected (has feedback) → guard returns False → abort

    res = engine.delete_node_guarded(node_id, guard)
    assert res is None
    assert _exists(engine, node_id) is True


def test_guard_never_deletes_user_node(engine):
    res = engine.delete_node_guarded(engine.user_node_id, lambda conn: True)
    assert res is None


def test_guarded_delete_does_not_deadlock_against_a_concurrent_writer(engine):
    """The guarded delete must take L_mem BEFORE L_db, like every other decorated writer.

    Decorating its only production caller (run_forgetting) closes today's exposure; this pins
    the method itself, so the next direct caller cannot reopen the inversion. The two locks are
    upstream's restore-exclusion RLock (L_mem, shared with FileStore) and Database._lock (L_db,
    held across transaction()'s yield).
    """
    node_id = _archival(engine)
    deleter_holds_db = threading.Event()
    writer_holds_mem = threading.Event()
    real_soft_delete = engine.file_store.soft_delete

    def instrumented_soft_delete(target_id):
        # Inside the write txn: this thread holds L_db and is one call away from taking L_mem.
        deleter_holds_db.set()
        writer_holds_mem.wait(timeout=1.0)  # times out once the deleter holds L_mem itself
        return real_soft_delete(target_id)

    engine.file_store.soft_delete = instrumented_soft_delete

    def writer():
        """What @_serialized_memory_operation + a write txn do on any MCP write: L_mem, L_db."""
        deleter_holds_db.wait(timeout=5.0)
        with engine._memory_operation_lock:
            writer_holds_mem.set()
            with engine.db.transaction():
                pass

    deleter_thread = threading.Thread(
        target=engine.delete_node_guarded, args=(node_id, lambda conn: True), daemon=True)
    writer_thread = threading.Thread(target=writer, daemon=True)
    deleter_thread.start()
    writer_thread.start()
    deleter_thread.join(timeout=10.0)
    writer_thread.join(timeout=10.0)

    assert not deleter_thread.is_alive(), "guarded delete held L_db while waiting for L_mem"
    assert not writer_thread.is_alive(), "writer held L_mem while waiting for L_db"

"""Tests for index builder."""

import threading

from ormah.index.builder import IndexBuilder
from ormah.models.node import CreateNodeRequest, MemoryNode, NodeType


def test_full_rebuild(db, file_store):
    # Create some nodes on disk
    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact {i} for indexing.",
            title=f"Fact {i}",
        )
        file_store.save(node)

    builder = IndexBuilder(db, file_store)
    count = builder.full_rebuild()
    assert count == 3

    # Verify in DB
    rows = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    assert rows[0] == 3


def test_incremental_update(db, file_store):
    builder = IndexBuilder(db, file_store)

    # Initial build
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="Original content.",
        title="Original",
    )
    file_store.save(node)
    builder.full_rebuild()

    # Add another node
    node2 = MemoryNode(
        type=NodeType.decision,
        source="agent:test",
        content="New decision.",
        title="Decision",
    )
    file_store.save(node2)

    added, updated = builder.incremental_update()
    assert added == 1
    assert updated == 0

    rows = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    assert rows[0] == 2


# --- lock order (0.14.8 restore-exclusion lock) ---


def test_incremental_update_does_not_deadlock_against_a_memory_job(engine):
    """incremental_update must take L_mem BEFORE L_db, like every memory job.

    The restore-exclusion lock decorates 8 FileStore methods with the engine's own RLock
    (L_mem) -- MemoryEngine passes it in: FileStore(nodes_dir, self._memory_operation_lock).
    incremental_update opens the write txn (L_db) and only then calls file_store.list_paths /
    file_hash: L_db -> L_mem. Every @serialized_memory_job background job goes L_mem -> L_db.
    Opposite orders on two locks = deadlock, and index_updater runs every 60s.
    """
    engine.remember(CreateNodeRequest(
        content="indexed content", type=NodeType.fact, title="indexed content"))

    builder_reached_file_store = threading.Event()
    job_holds_mem = threading.Event()
    real_list_paths = engine.file_store.list_paths

    def instrumented_list_paths():
        # Before the fix this runs INSIDE the write txn: this thread holds L_db and is one call
        # away from taking L_mem. Let the memory job grab L_mem first, then reach for it.
        # After the fix this runs BEFORE the txn, so no L_db is held and nothing can cycle.
        builder_reached_file_store.set()
        job_holds_mem.wait(timeout=1.0)  # times out once this thread already holds L_mem
        return real_list_paths()

    engine.file_store.list_paths = instrumented_list_paths

    def memory_job():
        """What @serialized_memory_job + a write txn do on every background job: L_mem, L_db."""
        builder_reached_file_store.wait(timeout=5.0)
        with engine._memory_operation_lock:
            job_holds_mem.set()
            with engine.db.transaction():
                pass

    builder_thread = threading.Thread(target=engine.builder.incremental_update, daemon=True)
    job_thread = threading.Thread(target=memory_job, daemon=True)
    builder_thread.start()
    job_thread.start()
    builder_thread.join(timeout=10.0)
    job_thread.join(timeout=10.0)

    assert not builder_thread.is_alive(), "incremental_update held L_db while waiting for L_mem"
    assert not job_thread.is_alive(), "memory job held L_mem while waiting for L_db"

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


# --- lock order (0.14.7+ restore-exclusion lock) ---


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


def test_builder_never_takes_file_lock_inside_write_transaction(engine):
    """All builder entry points must finish FileStore calls before taking L_db."""
    real_lock = engine._memory_operation_lock
    violations: list[int] = []

    class OrderProbe:
        def __enter__(self):
            tx_depth = getattr(engine.db._local, "tx_depth", 0)
            if tx_depth > 0:
                violations.append(tx_depth)
            return real_lock.__enter__()

        def __exit__(self, *args):
            return real_lock.__exit__(*args)

    engine.file_store._operation_lock = OrderProbe()

    # Exercise full rebuild and single-file indexing.
    engine.builder.full_rebuild()
    single = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="single content",
        title="single",
    )
    single_path = engine.file_store.save(single)
    engine.builder.index_single(single_path)

    # Exercise every incremental branch: new, changed, then deleted.
    incremental = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="new content",
        title="incremental",
    )
    engine.file_store.save(incremental)
    assert engine.builder.incremental_update() == (1, 0)

    incremental.content = "changed content"
    engine.file_store.save(incremental)
    assert engine.builder.incremental_update() == (0, 1)

    engine.file_store.delete(incremental.id)
    assert engine.builder.incremental_update() == (0, 0)

    assert not violations, f"FileStore lock acquired inside db.transaction(): {violations}"


def test_reindex_preserves_incoming_edges(engine):
    """Reindexing a node must not destroy the edges that point AT it (#123).

    The connection A -> B lives in A's markdown file. Reindexing B has no access to that
    file and therefore no way to reconstruct the row, so it must not delete it.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, edge_type, weight FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before B is reindexed"

    # Reindex the TARGET — what the index updater does after any change to B's own file.
    node_b = engine.file_store.load(id_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = incoming()
    assert len(rows) == 1, "incoming edge destroyed by reindexing the target (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["edge_type"] == "supports"
    assert rows[0]["weight"] == 0.9, "weight 0.9 (not the 0.5 default) proves this is A's row"


def test_touch_updated_does_not_drop_incoming_edges(engine):
    """The real-world trigger: file_hash changes, content fingerprint does not (#123).

    `_invalidate_checked_pairs` only fires when the CONTENT fingerprint changes, but the
    reindex fires on any file_hash change. `touch_updated()` moves only `updated`, so the
    edge dies while the cached pair verdict survives — and auto_linker, conflict_detector
    and duplicate_merger all skip a pair already recorded in `auto_link_checked`. Nothing
    ever recreates the edge; the loss stands until a full rebuild.

    Self-feeding on the Beta: the auto-linker touches the node before saving, so creating
    any new link on a node destroys that node's own incoming edges. The same shape drives
    the importance scorer, which touched 5,216 nodes in one pass on 2026-08-21 and cost
    ~13,800 edges in 54 minutes.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.7)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming_count():
        return engine.db.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
        ).fetchone()[0]

    assert incoming_count() == 1, "sanity: the edge must exist before the touch"

    # The only delta is `updated`: file_hash changes, content fingerprint does not.
    node_b = engine.file_store.load(id_b)
    node_b.touch_updated()
    engine.file_store.save(node_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    assert incoming_count() == 1, "touch_updated() destroyed the incoming edge (#123)"


def test_incremental_update_preserves_incoming_edges(engine):
    """The path production actually takes: the 60s index updater (#123).

    `index_single` is not the production trigger. `incremental_update` is — it walks the
    store, sees B's file_hash changed, and calls `_remove_node(id, keep_vectors=True)` at
    builder.py:104, a DIFFERENT call site from the one index_single uses (:122). A fix
    applied only to index_single leaves this path destroying incoming edges once a minute.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.6)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, weight FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before the updater runs"

    # Change B's file so the updater sees a new file_hash, then run the REAL trigger.
    node_b = engine.file_store.load(id_b)
    node_b.touch_updated()
    engine.file_store.save(node_b)
    added, updated = engine.builder.incremental_update()

    assert updated == 1, "sanity: the updater must have seen B as changed"
    rows = incoming()
    assert len(rows) == 1, "incremental_update destroyed the incoming edge (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["weight"] == 0.6, "weight 0.6 (not the 0.5 default) proves this is A's row"

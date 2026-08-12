"""Tests for index builder."""

import threading

import pytest

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


def test_full_rebuild_aborts_and_preserves_data_on_total_failure(db, file_store, monkeypatch):
    """A rebuild where every file fails to index must NOT persist a truncated index —
    it must ROLLBACK, preserving whatever was committed before (the nodes-empty incident)."""
    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact {i} for indexing.",
            title=f"Fact {i}",
        )
        file_store.save(node)

    builder = IndexBuilder(db, file_store)
    builder.full_rebuild()  # seed the index from the fixture store
    before = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert before == 3

    def boom(_path, _file_hash, prior=None, prior_fingerprints=None):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(builder, "_index_file_nodes_only", boom)

    with pytest.raises(RuntimeError, match=r"0/3 files"):
        builder.full_rebuild()

    after = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert after == before  # ROLLBACK preserved the prior committed state


def test_full_rebuild_aborts_and_preserves_data_on_partial_failure(db, file_store, monkeypatch):
    """One file succeeding out of many must still abort the rebuild (not just count==0) —
    a partial index committed as "complete" is the exact silent-degradation risk the
    count==0 guard misses."""
    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact {i} for indexing.",
            title=f"Fact {i}",
        )
        file_store.save(node)

    builder = IndexBuilder(db, file_store)
    builder.full_rebuild()  # seed the index from the fixture store
    before = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert before == 3

    original = builder._index_file_nodes_only
    calls = {"n": 0}

    def flaky(path, file_hash, prior=None, prior_fingerprints=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(path, file_hash, prior=prior, prior_fingerprints=prior_fingerprints)
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(builder, "_index_file_nodes_only", flaky)

    with pytest.raises(RuntimeError, match=r"1/3 files"):
        builder.full_rebuild()

    after = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert after == before  # ROLLBACK preserved the prior committed state, not a 1-node index


def test_full_rebuild_allow_partial_accepts_incomplete_pass(db, file_store, monkeypatch):
    """allow_partial=True is the explicit opt-out: a partial pass is committed instead of
    raising, for callers that intentionally tolerate known-corrupt files."""
    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact {i} for indexing.",
            title=f"Fact {i}",
        )
        file_store.save(node)

    builder = IndexBuilder(db, file_store)

    original = builder._index_file_nodes_only
    calls = {"n": 0}

    def flaky(path, file_hash, prior=None, prior_fingerprints=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(path, file_hash, prior=prior, prior_fingerprints=prior_fingerprints)
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(builder, "_index_file_nodes_only", flaky)

    count = builder.full_rebuild(allow_partial=True)
    assert count == 1

    rows = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    assert rows[0] == 1


def test_full_rebuild_edge_failure_does_not_abort_but_is_surfaced(db, file_store, monkeypatch, caplog):
    """A per-file edge-indexing failure must NOT abort the rebuild (edges are derived and
    self-healing; aborting on one bad link would roll back every good node and risk an empty
    store). But the aggregate failure must be surfaced, not swallowed silently (council-pr H1)."""
    import logging

    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact {i} for indexing.",
            title=f"Fact {i}",
        )
        file_store.save(node)

    builder = IndexBuilder(db, file_store)
    original = builder._index_file_edges

    def flaky_edges(path):
        if "Fact 1" in path.read_text(encoding="utf-8"):
            raise RuntimeError("bad link")
        return original(path)

    monkeypatch.setattr(builder, "_index_file_edges", flaky_edges)

    with caplog.at_level(logging.ERROR, logger="ormah.index.builder"):
        count = builder.full_rebuild()

    assert count == 3  # all nodes committed despite the edge failure
    assert db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
    assert any("failed edge indexing" in r.message for r in caplog.records)  # surfaced, not silent


def test_reindex_preserves_the_edge_reason(engine):
    """Reindexing a node must not wipe why its edges exist."""
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node = engine.file_store.load(id_a)
    node.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node)

    # index_single takes a Path, not an id (builder.py:124) - passing the id raises
    # before the assertion is ever reached (Codex R2, critical #4). The only helper that
    # maps a node to its file is FileStore._path_for(node) (file_store.py:192), which
    # takes the MemoryNode, not the id.
    engine.builder.index_single(engine.file_store._path_for(node))

    row = engine.db.conn.execute(
        "SELECT reason FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = 'supports'",
        (id_a, id_b),
    ).fetchone()
    assert row is not None
    assert row["reason"] == "because X"


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


# --- hash-failure regressions (council 2026-08-12) ---


def test_full_rebuild_aborts_when_hashing_fails(db, file_store, monkeypatch):
    """A hash failure must skip the path, miss the count, and trip abort-on-partial."""
    for i in range(3):
        file_store.save(MemoryNode(
            type=NodeType.fact, source="agent:test",
            content=f"Fact {i} for indexing.", title=f"Fact {i}"))

    builder = IndexBuilder(db, file_store)
    builder.full_rebuild()
    before = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert before == 3

    original_hash = file_store.file_hash
    calls = {"n": 0}

    def flaky_hash(path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(24, "Too many open files")
        return original_hash(path)

    monkeypatch.setattr(file_store, "file_hash", flaky_hash)

    with pytest.raises(RuntimeError, match=r"2/3 files"):
        builder.full_rebuild()

    assert db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == before


def test_incremental_update_defers_removal_when_hashing_fails(db, file_store, monkeypatch):
    """A transient hash failure must NOT be read as a deletion.

    _remove_node runs with keep_vectors=False on the removal path, so a spurious removal loses
    the vector permanently, and it does not clear the checked-pair tables, bypassing #126.
    """
    node = MemoryNode(type=NodeType.fact, source="agent:test",
                      content="Durable content.", title="Durable")
    file_store.save(node)
    builder = IndexBuilder(db, file_store)
    builder.full_rebuild()
    assert db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1

    def always_fails(path):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(file_store, "file_hash", always_fails)
    builder.incremental_update()

    # The file is still on disk: the node must survive.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id = ?", (node.id,)).fetchone()[0] == 1

    # A genuine absence must still be removed once hashing works again.
    monkeypatch.undo()
    file_store.delete(node.id)
    builder.incremental_update()
    assert db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id = ?", (node.id,)).fetchone()[0] == 0

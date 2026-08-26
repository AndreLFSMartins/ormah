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
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, weight, reason FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before B is reindexed"

    # Reindex the TARGET — what the index updater does after any change to B's own file.
    node_b = engine.file_store.load(id_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = incoming()
    assert len(rows) == 1, "incoming edge destroyed by reindexing the target (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["reason"] == "because X"
    assert rows[0]["weight"] == 0.9


def test_touch_updated_does_not_drop_incoming_edges(engine):
    """The real-world trigger: file_hash changes, content fingerprint does not (#123).

    `_invalidate_checked_pairs` only fires when the CONTENT fingerprint changes, but the
    reindex fires on any file_hash change. `touch_updated()` moves only `updated`, so the
    edge dies while the cached pair verdict survives — and auto_linker, conflict_detector
    and duplicate_merger all skip a pair already recorded in `auto_link_checked`. Nothing
    ever recreates the edge; the loss stands until a full rebuild.

    Self-feeding: `auto_linker._apply_edge` calls `touch_updated()` before saving
    (auto_linker.py:361), so creating any new link on a node destroys that node's own
    incoming edges.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.7, reason="mechanism")
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


def test_removing_a_node_still_drops_its_incoming_edges(engine):
    """When the file is really gone, incoming edges MUST die (the mirror of #123).

    `edges.target_id` is `REFERENCES nodes(id) ON DELETE CASCADE`: an edge pointing at a
    node that no longer exists is a foreign-key violation. A fix that simply never deleted
    incoming edges would pass every other test in this file and leave orphan rows behind.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
    ).fetchone()[0] == 1, "sanity: the edge must exist before B's file is deleted"

    # B genuinely leaves the store: its markdown file is gone from disk.
    path_b = engine.file_store._path_for(engine.file_store.load(id_b))
    path_b.unlink()
    engine.builder.incremental_update()

    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id = ?", (id_b,)
    ).fetchone()[0] == 0, "the removed node must be gone from the index"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
    ).fetchone()[0] == 0, "orphan edge survived the removal of its target"


def test_reindex_keeps_the_incumbent_canonical_direction(engine):
    """When both files declare the same link, the incumbent row wins — stably.

    `_index_file_edges` skips inserting A -> B when the reverse B -> A already exists with
    the same edge type (builder.py:352). Before #123 was fixed, reindexing B destroyed both
    directions, so B's own declaration was reinserted and the surviving direction was
    whichever node happened to be reindexed last. Now the incumbent survives and B's
    declaration is skipped: deterministic, and NOT a regression.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    # Auto-linking is synchronous in engine.remember() and, above the similarity threshold,
    # writes its own related_to edge sourced at the new node — which would make the
    # un-filtered pair query below count 2 rows for reasons unrelated to this test.
    original_threshold = engine.settings.auto_link_similarity_threshold
    engine.settings.auto_link_similarity_threshold = 999.0
    try:
        id_a, _ = engine.remember(
            CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
        id_b, _ = engine.remember(
            CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")
    finally:
        engine.settings.auto_link_similarity_threshold = original_threshold

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="from A")
    )
    engine.file_store.save(node_a)

    node_b = engine.file_store.load(id_b)
    node_b.connections.append(
        Connection(target=id_a, edge=EdgeType.supports, weight=0.2, reason="from B")
    )
    engine.file_store.save(node_b)

    # A is indexed first, so A -> B becomes the incumbent row.
    engine.builder.index_single(engine.file_store._path_for(node_a))
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = engine.db.conn.execute(
        "SELECT source_id, reason FROM edges "
        "WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)",
        (id_a, id_b, id_b, id_a),
    ).fetchall()

    assert len(rows) == 1, "the pair must be represented by exactly one canonical row"
    assert rows[0]["source_id"] == id_a, "reindexing B flipped the canonical direction"
    assert rows[0]["reason"] == "from A", "the incumbent's metadata must be the one kept"


def test_incremental_update_preserves_incoming_edges(engine):
    """The path production actually takes: the 60s index updater (#123).

    `index_single` is not the production trigger. `incremental_update` is — it walks the
    store, sees B's file_hash changed, and calls `_remove_node(id, keep_vectors=True)` at
    builder.py:161, a DIFFERENT call site from the one index_single uses (:200). A fix
    applied only to index_single leaves this path destroying incoming edges once a minute.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.6, reason="via updater")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, reason FROM edges WHERE target_id = ?", (id_b,)
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
    assert rows[0]["reason"] == "via updater"


# --- lock order (0.14.7+ restore-exclusion lock) ---


def test_incremental_update_does_not_deadlock_against_a_memory_job(engine):
    """incremental_update must take L_mem BEFORE L_db, like every memory job.

    The restore-exclusion lock decorates 8 FileStore methods with the engine's own RLock
    (L_mem) -- MemoryEngine passes it in: FileStore(nodes_dir, self._memory_operation_lock).
    incremental_update opens the write txn (L_db) and only then calls file_store.list_paths /
    file_hash: L_db -> L_mem. Every background job apply step goes L_mem -> L_db (#240).
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
        """What every background job's apply step does: L_mem, then a write txn (#240)."""
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


def test_incremental_update_preserves_the_node_vector(engine):
    """incremental_update must not drop the `node_vectors` row (#123).

    `_clear_derived` takes `drop_vector` because `incremental_update` never re-embeds after
    it — unlike `index_single`, whose callers always call `_index_embedding` afterwards. If
    `incremental_update` ever passed `drop_vector=True`, the node would lose its embedding
    and stay unsearchable by similarity until the next startup backfill picks it up.
    """
    from ormah.models.node import CreateNodeRequest, NodeType

    node_id, _ = engine.remember(
        CreateNodeRequest(content="A fact to embed.", type=NodeType.fact), agent_id="t")

    def has_vector() -> bool:
        return engine.db.conn.execute(
            "SELECT 1 FROM node_vectors WHERE id = ?", (node_id,)
        ).fetchone() is not None

    assert has_vector(), "sanity: remember() must embed the node before the update runs"

    # Change the node's file so the updater sees a new file_hash and reindexes it.
    node = engine.file_store.load(node_id)
    node.touch_updated()
    engine.file_store.save(node)
    added, updated = engine.builder.incremental_update()

    assert updated == 1, "sanity: the updater must have seen the node as changed"
    assert has_vector(), "incremental_update dropped the node_vectors row"


def test_reindex_preserves_superseded_by(engine):
    """INSERT OR REPLACE drops omitted columns to their DEFAULT — the marker must be
    in the column list, or the consolidator's own update_node wipes it (#223)."""
    from ormah.models.node import CreateNodeRequest

    node_id, _ = engine.remember(CreateNodeRequest(content="a source about to be superseded"))

    node = engine.file_store.load(node_id)
    node.superseded_by = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    engine.builder.index_single(engine.file_store.save(node))

    row = engine.db.conn.execute(
        "SELECT superseded_by FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["superseded_by"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_full_rebuild_clears_lifecycle_keys(db, file_store):
    """#236: the index is derived state, so a rebuild must invalidate the
    lifecycle-migration markers the same way it already invalidates the
    auto-link watermark. Otherwise a restore onto an existing index finds
    'already migrated' and never seeds pre-FSRS nodes."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('fsrs_migrated', '1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_model_version', '2')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('auto_link_watermark', '7')"
        )
        # An unrelated key must survive: rebuild invalidates lifecycle state, not all of meta.
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('user_node_id', 'keep-me')"
        )

    IndexBuilder(db, file_store).full_rebuild()

    keys = {
        row["key"] for row in db.conn.execute("SELECT key FROM meta").fetchall()
    }
    assert "fsrs_migrated" not in keys
    assert "lifecycle_model_version" not in keys
    assert "auto_link_watermark" not in keys
    assert "user_node_id" in keys


def test_no_background_job_takes_l_mem_inside_a_write_transaction(engine):
    """Cross-cutting net for #240: the inversion #207 fixed must not come back.

    Every job now acquires and releases L_mem repeatedly instead of once, so this
    is not redundant with test_builder_never_takes_file_lock_inside_write_transaction
    above — that test covers the builder's own entry points, not the seven jobs.
    """
    import json
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from ormah.background.auto_cluster import run_auto_cluster
    from ormah.background.auto_linker import run_auto_linker
    from ormah.background.conflict_detector import run_conflict_detection
    from ormah.background.consolidator import run_consolidation
    from ormah.background.decay_manager import run_decay
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.importance_scorer import run_importance_scoring
    from ormah.models.node import (
        ConnectRequest,
        CreateNodeRequest,
        EdgeType,
        NodeType,
        UpdateNodeRequest,
    )

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

    engine._memory_operation_lock = OrderProbe()
    engine.file_store._operation_lock = engine._memory_operation_lock

    # Count L_mem acquisitions per job so a job that quietly finds zero candidates
    # (and so never reaches an apply step) fails loudly instead of the assertion
    # below passing vacuously for it. OrderProbe.__enter__ already runs on every
    # acquisition, so piggyback the count there instead of a second wrapper.
    acquisitions = {"n": 0}
    real_enter = OrderProbe.__enter__

    def counting_enter(self):
        acquisitions["n"] += 1
        return real_enter(self)

    OrderProbe.__enter__ = counting_enter

    # remember() auto-links highly-similar nodes at creation time via the same
    # similarity threshold the background auto_linker job uses -- if left on, the
    # 5 near-identical seed nodes below end up fully pairwise-linked before the job
    # ever runs, so it would find zero candidates. Disable it for the seeding only.
    real_auto_link = engine._auto_link_node
    engine._auto_link_node = lambda node: []
    ids = []
    for i in range(5):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"seed node {i} about project architecture", type=NodeType.fact,
            title=f"seed {i}"))
        ids.append(nid)
    engine._auto_link_node = real_auto_link

    # ids[0] <-> ids[4] manually connected so auto_cluster has a spaced neighbor to
    # vote from; ids[1..3] stay unconnected so auto_linker has real, not-already-
    # linked, above-threshold pairs to classify.
    engine.connect(ConnectRequest(
        source_id=ids[0], target_id=ids[4], edge=EdgeType.related_to, weight=1.0))
    # ids[4] is already space=None from creation -- nothing to set there.
    # ids[0]'s space must go through update_node, not a raw SQL UPDATE: the
    # markdown file (loaded by file_store) is the source of truth, and any later
    # engine.update_node call (decay's own demotion, right below) reloads from
    # the file and re-persists it -- silently reverting a DB-only `space` back
    # to None and starving auto_cluster of a spaced neighbor to vote from.
    engine.update_node(ids[0], UpdateNodeRequest(space="architecture"))
    # A bare SQL `datetime('now', '-30 days')` literal produces a naive,
    # space-separated string; decay_manager's anchor parse then mixes it with a
    # tz-aware `now`, raises TypeError, and silently skips the node -- vacuous.
    # Use the same tz-aware ISO string test_decay_manager.py's _make_stale uses.
    # last_accessed is read straight from the SQLite index by decay's own
    # candidate scan and revalidation, so a raw SQL UPDATE (unlike space above)
    # is exactly what's needed here -- and update_node's later reload/resave for
    # the tier demotion doesn't touch it since UpdateNodeRequest carries no
    # last_accessed field.
    stale_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, tier = 'working' WHERE id = ?",
        (stale_date, ids[0]))
    engine.db.conn.commit()

    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_min_cluster_size = 2
    # Cap the linker's source scan so it doesn't mark every pair as auto_link_checked
    # before conflict/duplicate detection run -- those two also skip already-checked
    # pairs, and with an unbounded scan the linker would starve them of candidates.
    engine.settings.auto_link_max_nodes_per_run = 2

    fake_link = json.dumps({"relationship": "supports", "reason": "same topic"})
    fake_conflict_true = json.dumps({
        "same_subject": True, "conflict": True, "type": "tension", "explanation": "x"})
    fake_conflict_false = json.dumps({
        "same_subject": True, "conflict": False, "type": "none", "explanation": "n/a"})
    fake_dup_true = json.dumps({
        "is_duplicate": True, "merged_title": "merged", "merged_content": "merged content"})
    fake_dup_false = json.dumps({"is_duplicate": False, "reason": "distinct"})
    fake_consolidate = json.dumps({
        "title": "merged", "summary": "merged content", "type": "fact"})

    # conflict_detection and duplicate_detection only reach their apply step (the
    # engine.memory_operation_at block) on a positive verdict -- a fixed "false"
    # response (as consolidation and auto_linker's "none"/"supports" pattern might
    # suggest) would leave those two jobs' apply steps completely unexercised. Flip
    # to positive for the first candidate of each type only, so exactly one real
    # apply happens per job instead of a cascade of merges/edges eating the fixture.
    done = {"conflict": False, "dup": False}

    def fake_llm(*args, **kwargs):
        prompt = args[1] if len(args) > 1 else kwargs.get("prompt", "")
        # Match on phrases unique to each job's prompt -- "contradict" alone also
        # appears inside the auto_linker prompt's "contradicts" edge-type option,
        # which would misroute every linker call into the conflict branch.
        if "duplicates that should be merged" in prompt:
            if not done["dup"]:
                done["dup"] = True
                return fake_dup_true
            return fake_dup_false
        if "contradict each other" in prompt:
            if not done["conflict"]:
                done["conflict"] = True
                return fake_conflict_true
            return fake_conflict_false
        if "consolidating a cluster" in prompt:
            return fake_consolidate
        return fake_link

    try:
        with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
            # decay gets its own check instead of the shared acquisitions-count guard:
            # run_decay unconditionally opens L_mem once at the top of every call to
            # clear stale proposals (decay_manager.py's one-time cleanup), before it
            # ever scans for demotion candidates. That means acquisitions["n"] > before
            # would hold even if decay found nothing to demote -- it doesn't prove the
            # apply step (the actual tier demotion) ran. Assert the observable effect
            # instead: the seeded stale node (ids[0]) really moved to archival.
            run_decay(engine)
            tier_row = engine.db.conn.execute(
                "SELECT tier FROM nodes WHERE id = ?", (ids[0],)).fetchone()
            assert tier_row is not None and tier_row["tier"] == "archival", (
                "decay never demoted the seeded stale node -- its apply step was "
                "never reached, so this net covers nothing for it"
            )

            for name, run_job in [
                ("importance_scoring", run_importance_scoring),
                ("auto_cluster", run_auto_cluster),
                ("auto_linker", run_auto_linker),
                ("conflict_detection", run_conflict_detection),
                ("duplicate_detection", run_duplicate_detection),
                ("consolidation", run_consolidation),
            ]:
                before = acquisitions["n"]
                run_job(engine)
                assert acquisitions["n"] > before, (
                    f"{name} never acquired L_mem -- its apply step was never "
                    "reached, so this net covers nothing for it"
                )
    finally:
        OrderProbe.__enter__ = real_enter

    assert not violations, f"L_mem acquired inside db.transaction(): depths {violations}"

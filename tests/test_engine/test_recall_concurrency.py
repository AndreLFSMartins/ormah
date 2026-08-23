"""Concurrency regression: recall must be safe when routes run in the threadpool.

The server runs engine-bound routes off the event loop (Starlette threadpool), so
``recall_search`` executes on many threads at once. GraphIndex / HybridSearch must
therefore resolve the per-thread ``Database`` connection on every access instead of
capturing a single shared ``sqlite3.Connection`` at construction. A shared connection
used concurrently raises ``sqlite3.InterfaceError: bad parameter or other API misuse``
(SQLITE_MISUSE) and returns corrupted rows under load.
"""

import threading

from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType


def _remember(engine, content):
    req = CreateNodeRequest(content=content, type=NodeType.fact, title=content[:40], tags=["t"])
    node_id, _ = engine.remember(req, agent_id="test")
    return node_id


def test_graph_conn_is_per_thread(engine):
    """engine.graph.conn must resolve to the calling thread's own connection."""
    main_conn = id(engine.graph.conn)
    worker_conn: dict[str, int] = {}

    def grab():
        worker_conn["id"] = id(engine.graph.conn)

    t = threading.Thread(target=grab)
    t.start()
    t.join()

    # A worker thread reading engine.graph.conn gets a *different* connection
    # object than the main thread — proof the connection is not captured/shared.
    assert worker_conn["id"] != main_conn


def test_concurrent_recall_does_not_raise(engine):
    """Hammering recall_search from many threads must not raise (shared-conn race)."""
    ids = [_remember(engine, f"memory {i} about postgres indexing and tuning strategy {i}") for i in range(30)]
    # Add edges so spreading activation exercises the graph read path on every recall.
    for i in range(0, len(ids) - 1):
        engine.connect(
            ConnectRequest(source_id=ids[i], target_id=ids[i + 1], edge=EdgeType.related_to, weight=0.8)
        )

    errors: list[str] = []
    stop = threading.Event()

    def hammer():
        try:
            for _ in range(40):
                if stop.is_set():
                    break
                engine.recall_search("postgres indexing tuning", limit=8)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
            stop.set()

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent recall raised: {errors[:3]}"


def test_decay_and_promotion_leave_disk_and_index_agreeing(engine):
    """"Did not raise" does not catch divergence — this compares disk against index.

    run_decay holds _memory_operation_lock for its whole run (serialized_memory_job
    -> engine.memory_operation()), and _record_confirmed_use takes the same RLock,
    so the two cannot interleave in-process.
    """
    from ormah.background.decay_manager import run_decay
    from ormah.models.node import Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="contended node"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))

    errors: list[BaseException] = []

    def decay():
        try:
            run_decay(engine)
        except BaseException as e:  # noqa: BLE001 - recorded and re-raised below
            errors.append(e)

    def promote():
        try:
            engine._record_confirmed_use(node_id)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=decay), threading.Thread(target=promote)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    on_disk = engine.file_store.load(node_id).tier.value
    in_index = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["tier"]
    assert on_disk == in_index

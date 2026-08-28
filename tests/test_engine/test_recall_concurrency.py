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
from tests.confirmed_use_helpers import reinforce


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
    """Decay and confirmed use race over one node; only two outcomes are legal.

    What this proves: run_decay holds _memory_operation_lock for its whole run
    (serialized_memory_job -> engine.memory_operation()) and _record_confirmed_use
    takes the same RLock, so the two cannot interleave in-process. Whichever wins
    the lock, disk and index end up agreeing and the final state is one of the two
    serializations enumerated below — no torn half-demoted/half-promoted state.

    What it cannot prove: nothing about cross-process safety. _memory_operation_lock
    is an in-process threading.RLock; a second OS process running the sleep cycle
    against the same store is not covered by this test at all.

    The node is seeded as a genuine decay candidate (tier=working, stability=1.0,
    last_accessed 30 days back => R = exp(-30) << fsrs_decay_threshold=0.3), so the
    decay thread really does have work to do rather than being a silent no-op.
    run_decay swallows its own exceptions, so `errors` can only ever fail on the
    promotion side — the outcome assertions below are what actually covers decay.
    """
    from datetime import datetime, timedelta, timezone

    from ormah.background.decay_manager import run_decay
    from ormah.models.node import Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="contended node"))
    node = engine.file_store.load(node_id)
    stale = datetime.now(timezone.utc) - timedelta(days=30)
    node.tier = Tier.working
    node.stability = 1.0
    node.last_accessed = stale
    node.last_review = stale
    node.importance = 0.0
    engine.builder.index_single(engine.file_store.save(node))

    errors: list[BaseException] = []

    def decay():
        try:
            run_decay(engine)
        except BaseException as e:  # noqa: BLE001 - recorded and asserted empty below
            errors.append(e)

    def promote():
        try:
            reinforce(engine, node_id)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=decay), threading.Thread(target=promote)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

    final = engine.file_store.load(node_id)
    in_index = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["tier"]
    assert final.tier.value == in_index

    # Both legal serializations end on `working`:
    #   decay first  -> demoted to archival, then confirmed use reinforces
    #                   (S=1, 30d -> 2.0) and the archival branch applies the
    #                   promotion floor max(2.0, fsrs_initial_stability=5.814)
    #                   -> back to working with S=5.814 and ONE promote entry.
    #   promotion first -> node is still `working`, so no promotion happens:
    #                   only the bounded reinforcement (S=1, 30d -> 2.0), and
    #                   last_accessed=now makes decay skip it -> working, 0 entries.
    assert final.tier is Tier.working
    assert in_index == Tier.working.value
    assert final.stability in (5.814, 2.0), final.stability

    promotes = engine.list_audit_log(node_id=node_id, operation="promote")
    expected_promotes = 1 if final.stability == 5.814 else 0
    assert len(promotes) == expected_promotes, (final.stability, promotes)

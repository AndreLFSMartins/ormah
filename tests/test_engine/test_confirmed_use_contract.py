"""Contract tests for issue #220: surfacing must not be confirmed use.

Every assertion reads the four lifecycle fields from BOTH the markdown file and
the SQLite row. A test that checked only the database would pass while the file
rotted, and vice versa.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_ui import router as ui_router
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.models.node import CreateNodeRequest

LIFECYCLE_FIELDS = ("access_count", "last_accessed", "stability", "last_review")


def _snapshot(engine, node_id):
    """Capture the four lifecycle fields from the markdown file and the DB row."""
    node = engine.file_store.load(node_id)
    row = engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    return {
        "file": tuple(getattr(node, f) for f in LIFECYCLE_FIELDS),
        "db": tuple(row[f] for f in LIFECYCLE_FIELDS),
    }


def _make_nodes(engine, count=2):
    """Create *count* nodes that a search for 'caching' will match."""
    ids = []
    for i in range(count):
        node_id, _ = engine.remember(CreateNodeRequest(
            content=f"caching architecture note number {i}",
            title=f"Caching {i}",
            type="fact",
            tier="working",
        ))
        ids.append(node_id)
    return ids


@pytest.fixture
def fts_only(engine):
    """Force the FTS fallback path by removing hybrid search."""
    with patch.object(engine, "_get_hybrid_search", return_value=None):
        yield engine


# --- Non-mutation contracts (issue #220 acceptance criteria) ---------------

def test_recall_search_does_not_write_lifecycle(engine):
    """Contract 1: broad formatted recall over N nodes mutates nothing."""
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id], (
            f"recall_search mutated lifecycle fields on {node_id}"
        )


def test_recall_search_fts_fallback_does_not_write_lifecycle(fts_only):
    """Contract 2: the FTS fallback path mutates nothing either."""
    engine = fts_only
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_recall_search_structured_does_not_write_lifecycle(engine):
    """Contract 3: called with no lifecycle kwarg — the default was the bug."""
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search_structured("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_recall_search_structured_fts_fallback_does_not_write_lifecycle(fts_only):
    """Contract 4: same for the FTS fallback."""
    engine = fts_only
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search_structured("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_ui_search_route_does_not_write_lifecycle(tmp_memory_dir):
    """Contract 5: the UI search route.

    This is the test that fails on clean upstream/main: routes_ui.search_nodes
    calls recall_search_structured without the kwarg, so the True default
    reinforced every result. Exercised through the route, not the engine.
    """
    settings = Settings(memory_dir=tmp_memory_dir, backup_dir=tmp_memory_dir.parent / "backups")
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        ids = _make_nodes(engine)
        before = {i: _snapshot(engine, i) for i in ids}

        app = FastAPI()
        app.include_router(ui_router)
        app.state.engine = engine
        with TestClient(app) as client:
            resp = client.get("/ui/search", params={"q": "caching architecture"})
        assert resp.status_code == 200

        for node_id in ids:
            assert _snapshot(engine, node_id) == before[node_id], (
                f"UI search mutated lifecycle fields on {node_id}"
            )
    finally:
        engine.shutdown()


def test_whisper_does_not_write_lifecycle(engine):
    """Contract 6: whisper still mutates nothing after losing its flag.

    Whisper was already correct (it passed touch_access=False). This pins that
    it stays correct once the flag is gone.
    """
    from ormah.engine.context_builder import ContextBuilder

    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    builder = ContextBuilder(engine.graph, engine=engine)
    builder.build_whisper_context("caching architecture", space=None, max_nodes=8)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_concurrent_confirmed_use_does_not_lose_increments(engine):
    """Issue #220: _record_confirmed_use is atomic across its read-modify-write.

    Without @_serialized_memory_operation, two threads can both load the same
    access_count and both save count+1, collapsing two confirmations into one.
    """
    import threading

    ids = _make_nodes(engine, count=1)
    target = ids[0]
    before = engine.file_store.load(target).access_count

    threads = [threading.Thread(target=engine._record_confirmed_use, args=(target,))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    after = engine.file_store.load(target)
    assert after.access_count == before + 8, (
        f"lost increments: expected {before + 8}, got {after.access_count}"
    )
    row = engine.db.conn.execute(
        "SELECT access_count FROM nodes WHERE id = ?", (target,)
    ).fetchone()
    assert row["access_count"] == after.access_count, "file and DB disagree after concurrency"


# --- Confirmed-use contracts ----------------------------------------------

def _seed_whisper_log(engine, node_id, prompt="what about caching?"):
    """Insert a whisper_log row so submit_feedback can resolve one.

    submit_feedback attaches feedback to a whisper/recall event; without a row
    it returns an error string instead of recording anything.
    """
    engine.recall_search(prompt, limit=10)
    row = engine.db.conn.execute(
        "SELECT id FROM whisper_log WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    assert row is not None, "no whisper_log row was created — check the surface used"
    return row["id"]


def test_recall_node_confirms_only_the_requested_node(engine):
    """Contract 7: recall_node confirms the node asked for, never its neighbours."""
    from ormah.models.node import CreateNodeRequest

    target, _ = engine.remember(CreateNodeRequest(
        content="caching architecture target node", title="Target", type="fact", tier="working",
    ))
    neighbour, _ = engine.remember(CreateNodeRequest(
        content="caching architecture neighbour node", title="Neighbour", type="fact",
        tier="working",
    ))
    engine.graph.conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, weight, created) "
        "VALUES (?, ?, 'related_to', 1.0, '2026-01-01T00:00:00Z')",
        (target, neighbour),
    )

    before_target = _snapshot(engine, target)
    before_neighbour = _snapshot(engine, neighbour)

    engine.recall_node(target)

    assert _snapshot(engine, target) != before_target, "recall_node did not confirm its node"
    assert _snapshot(engine, neighbour) == before_neighbour, (
        "recall_node confirmed a neighbour — only the requested node counts"
    )


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge"])
def test_qualified_positive_feedback_confirms_use(engine, source):
    """Contract 8: the three allowlisted sources confirm, with signal == 1."""
    ids = _make_nodes(engine, count=2)
    target, other = ids[0], ids[1]
    log_id = _seed_whisper_log(engine, target)

    before_target = _snapshot(engine, target)
    before_other = _snapshot(engine, other)

    engine.submit_feedback(target, signal=1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) != before_target, (
        f"positive {source} feedback did not confirm use"
    )
    assert _snapshot(engine, other) == before_other, "an unrelated node was confirmed"


def test_auto_heuristic_positive_does_not_confirm(engine):
    """Contract 9: auto_heuristic is excluded pending #218 — fail-closed."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=1, source="auto_heuristic", whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, "auto_heuristic must not confirm use"


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge", "auto_heuristic"])
def test_negative_feedback_never_confirms(engine, source):
    """Contract 10: -1 is evidence about the prompt/node pair, never a confirmed use."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=-1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, (
        f"negative {source} feedback changed lifecycle fields"
    )


# --- Idempotency contracts (second council round: the latch, not affinity) ---

def test_replaying_the_same_positive_feedback_confirms_once(engine):
    """Contract 10a: one confirmed-use event reinforces at most once.

    affinity and signals both use ON CONFLICT DO NOTHING, so a replayed request
    records no new evidence yet still returns success. Reinforcing on every call
    would let a retried tool call or a double-click manufacture retention.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "replaying the same positive feedback reinforced twice"
    )


def test_negative_then_positive_feedback_confirms(engine):
    """Contract 10b: a first-time positive confirms even after a negative.

    The negative claims nothing (it does not qualify), so the later positive is
    still the event's first confirmation. This is the case a naive 'did the
    signals INSERT add a row?' gate gets wrong: the unique key is
    (whisper_log_id, signal_type, source) with no polarity, so the second call
    hits ON CONFLICT DO NOTHING even though it is a genuine first confirmation.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=-1, source="explicit", whisper_log_id=log_id)
    after_negative = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) != after_negative, (
        "the event's first qualified positive did not confirm use"
    )


def test_second_source_on_an_already_confirmed_event_does_not_reconfirm(engine):
    """Contract 10c: the event is confirmed once, not once per source.

    This is the mirror failure: source is part of the signals unique key, so an
    implicit-positive followed by an explicit-positive DOES insert a second
    signals row. The event was already claimed; it must not reinforce again.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "a second positive source reconfirmed an already-confirmed event"
    )


def test_polarity_cycle_confirms_once(engine):
    """Contract 10d: +1 / -1 / +1 reinforces at most once — not twice.

    This is the false positive that killed the affinity-derived gate. affinity
    has one row per (node_id, whisper_log_id) and explicit feedback UPDATEs its
    signal in place, so reading affinity would see false->true twice and
    reinforce twice. The claim latch is never deleted, so the third call takes
    nothing.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    after_first_positive = _snapshot(engine, target)

    engine.submit_feedback(target, signal=-1, source="explicit", whisper_log_id=log_id)
    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first_positive, (
        "a polarity cycle reinforced the same event twice"
    )


def test_unqualified_affinity_does_not_block_a_later_qualified_positive(engine):
    """Contract 10e: a pre-existing auto_heuristic row must not swallow a real use.

    This is the false negative that killed the affinity-derived gate. The
    affinity unique key is (node_id, whisper_log_id) and only explicit feedback
    UPDATEs the row, so an auto_heuristic positive makes a later implicit
    positive a no-op INSERT that leaves source = auto_heuristic. Reading
    affinity would keep the gate false forever and lose the reinforcement in
    silence. The claim latch does not consult affinity at all.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="auto_heuristic", whisper_log_id=log_id)
    after_heuristic = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) != after_heuristic, (
        "a prior auto_heuristic affinity row blocked a genuine confirmed use"
    )


def test_reinforcement_failure_does_not_fail_the_feedback_call(engine):
    """Contract 10f: a raising mutator is logged, not propagated.

    The route returns submit_feedback's value directly, so an exception after
    COMMIT would 500 a call whose affinity and signals rows are already durably
    written. ZeroDivisionError is the realistic case, not a contrived one:
    stability is Field(default=1.0, ge=0.0), so zero is legal, and the mutator
    divides by it. Under the at-most-once contract this reinforcement is lost —
    that is the accepted cost, but it must be a logged miss, not an API error.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)

    with patch.object(
        engine, "_record_confirmed_use", side_effect=ZeroDivisionError("float division by zero")
    ):
        message = engine.submit_feedback(
            target, signal=1, source="explicit", whisper_log_id=log_id
        )

    assert "Feedback recorded" in message, "a failed reinforcement broke the feedback contract"
    assert _snapshot(engine, target) == before, "lifecycle advanced despite the failure"

    # The evidence itself is committed — this is about lifecycle, not observability.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ? AND node_id = ?",
        (log_id, target),
    ).fetchone()
    assert affinity is not None, "the feedback evidence was rolled back"


def test_recall_node_claims_its_own_event(engine):
    """Contract 7a: one deliberate fetch reinforces once, even when the agent
    then submits feedback on the event recall_node handed it.

    recall_node calls _log_feedback_candidates, which creates a whisper_log row
    for the very node it just confirmed and returns its id — the formatter
    attaches it as _whisper_log_id, and the agent instructions tell the model to
    submit_feedback(+1) with that id when it draws on the memory. Without a claim
    taken by recall_node itself, that feedback finds the event unclaimed and
    reinforces a second time, so one fetch counts twice. Found by whole-branch
    review, reproduced before the fix as access_count 0 -> 1 -> 2.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]

    before = _snapshot(engine, target)
    engine.recall_node(target)
    after_recall = _snapshot(engine, target)
    assert after_recall != before, "recall_node did not confirm its own node"

    row = engine.db.conn.execute(
        "SELECT id FROM whisper_log WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (target,),
    ).fetchone()
    assert row is not None, "recall_node logged no feedback candidate for its own node"

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=row["id"])

    assert _snapshot(engine, target) == after_recall, (
        "feedback on the event recall_node itself surfaced reinforced it a second time"
    )

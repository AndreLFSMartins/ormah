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

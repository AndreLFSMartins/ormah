"""Proves engine-calling routes run in the threadpool, not serialized on the loop."""

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_agent import router as agent_router
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine


@pytest.fixture
def client(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir, backup_dir=tmp_memory_dir.parent / "backups")
    engine = MemoryEngine(settings)
    engine.startup()
    app = FastAPI()
    app.include_router(agent_router)
    app.state.engine = engine
    with TestClient(app) as c:
        yield c, engine
    engine.shutdown()


def test_recall_routes_run_concurrently(client):
    c, engine = client

    live = 0
    max_live = 0
    counter_lock = threading.Lock()

    def slow_recall(*args, **kwargs):
        nonlocal live, max_live
        with counter_lock:
            live += 1
            max_live = max(max_live, live)
        time.sleep(0.3)
        with counter_lock:
            live -= 1
        return "ok"

    engine.recall_search = slow_recall  # type: ignore[method-assign]

    results: list[int] = []

    def hit():
        r = c.post("/agent/recall", json={"query": "x", "limit": 3})
        results.append(r.status_code)

    n = 5
    threads = [threading.Thread(target=hit) for _ in range(n)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - start

    assert results == [200] * n
    # If routes ran on the event loop they would serialize: wall ~= n*0.3 = 1.5s
    # and max_live would be 1. In the threadpool they overlap.
    assert max_live >= 2, f"routes serialized (max concurrent = {max_live})"
    assert wall < 0.3 * n, f"wall {wall:.2f}s suggests serialization"

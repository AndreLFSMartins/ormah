"""embedding_backfill must be a registered admin task in the sleep-cycle (#32)."""
from __future__ import annotations

from ormah.api import routes_admin


def test_embedding_backfill_in_task_registry():
    assert "embedding_backfill" in routes_admin._TASK_RUNNERS
    module, func = routes_admin._TASK_RUNNERS["embedding_backfill"]
    assert module == "ormah.background.embedding_backfill"
    assert func == "run_embedding_backfill"


def test_embedding_backfill_has_description():
    assert "embedding_backfill" in routes_admin._TASK_DESCRIPTIONS


def test_embedding_backfill_in_sleep_cycle_order():
    order = routes_admin._SLEEP_CYCLE_ORDER
    assert "embedding_backfill" in order
    # runs after the index is updated
    assert order.index("embedding_backfill") > order.index("index_updater")

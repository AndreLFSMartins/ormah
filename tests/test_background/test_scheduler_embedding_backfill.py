"""The embedding_backfill job must be registered with a post-bind first run (#32)."""
from __future__ import annotations

from ormah.background.scheduler import start_scheduler


def test_embedding_backfill_job_registered(engine):
    scheduler, _tracker = start_scheduler(engine)
    try:
        job = scheduler.get_job("embedding_backfill")
        assert job is not None
        assert job.name == "Embedding backfill"
        # next_run_time is set (post-bind first run), not None/deferred
        assert job.next_run_time is not None
    finally:
        scheduler.shutdown(wait=False)

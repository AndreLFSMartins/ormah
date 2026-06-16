# Task 07: Register the `embedding_backfill` job in the scheduler

Register the job like the others (`tracked()` + `JobTracker`, interval, `misfire_grace`), but
add a `next_run_time` ~10s after start so it fires once right after the port binds (the core
#32 recovery) even when the operator sets the interval to `999999`.

**Files:**
- Modify: `src/ormah/background/scheduler.py` (`timedelta` import ~L5; new `add_job` block ~after L61)
- Test: `tests/test_background/test_scheduler_embedding_backfill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_background/test_scheduler_embedding_backfill.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_scheduler_embedding_backfill.py -v`
Expected: FAIL — `assert job is not None` (job not registered yet).

- [ ] **Step 3: Add `timedelta` to the datetime import**

In `src/ormah/background/scheduler.py`, change the datetime import (~L5):

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Register the job**

In `start_scheduler()`, after the `forgetting_manager` `add_job(...)` block (~L54-61), add:

```python
    from ormah.background.embedding_backfill import run_embedding_backfill

    scheduler.add_job(
        tracked(tracker, "embedding_backfill", run_embedding_backfill, engine),
        "interval",
        minutes=s.embedding_backfill_interval_minutes,
        id="embedding_backfill",
        name="Embedding backfill",
        misfire_grace_time=_MISFIRE_GRACE,
        max_instances=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
```

(`max_instances=1` is the APScheduler default but is stated explicitly here because a slow
reconciliation on a large gap must never overlap the next tick.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_background/test_scheduler_embedding_backfill.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/scheduler.py tests/test_background/test_scheduler_embedding_backfill.py
git add src/ormah/background/scheduler.py tests/test_background/test_scheduler_embedding_backfill.py
git commit -m "feat(background): register embedding_backfill job with post-bind first run (#32)"
```

# Task 09: Scheduler-independent post-bind fallback

Council **I1**: the server treats `start_scheduler` as optional (`lifespan` catches its failure
and keeps serving). With the synchronous startup re-embed gone (Task 05), a scheduler that
fails to start would leave missing vectors unhealed indefinitely. Add a narrow fallback: when
the scheduler did **not** start, kick one reconciliation off a daemon thread (off the bind
path, so it never blocks). The happy path is unchanged — the scheduler's post-bind
`next_run_time` (Task 07) still drives the first run and the recurring cadence.

**Files:**
- Modify: `src/ormah/main.py` (add `_start_backfill_fallback`; call it in `lifespan` after the scheduler block ~L68-71)
- Test: `tests/test_main_backfill_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_backfill_fallback.py`:

```python
"""Scheduler-independent embedding backfill fallback (#32, council I1)."""
from __future__ import annotations

import time

from ormah import main


def test_start_backfill_fallback_runs_job_off_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        lambda engine: calls.append(engine),
    )
    sentinel = object()

    main._start_backfill_fallback(sentinel)

    # daemon thread; poll briefly for it to run
    for _ in range(100):
        if calls:
            break
        time.sleep(0.01)
    assert calls == [sentinel]


def test_start_backfill_fallback_swallows_errors(monkeypatch):
    def _boom(engine):
        raise RuntimeError("backfill blew up in fallback")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _boom
    )
    # must not raise on the calling thread
    main._start_backfill_fallback(object())
    time.sleep(0.05)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: FAIL — `AttributeError: module 'ormah.main' has no attribute '_start_backfill_fallback'`.

- [ ] **Step 3: Add the fallback helper**

In `src/ormah/main.py`, add near the top-level helpers (module already has a `logger`):

```python
def _start_backfill_fallback(engine) -> None:
    """Run one embedding reconciliation off a daemon thread when the scheduler is
    unavailable, so missing vectors are still healed without it (#32, council I1).
    Off the bind path — never blocks startup."""
    import threading

    def _run():
        from ormah.background.embedding_backfill import run_embedding_backfill
        try:
            run_embedding_backfill(engine)
        except Exception as e:
            logger.warning("Embedding backfill fallback failed: %s", e)

    threading.Thread(
        target=_run, name="embedding-backfill-fallback", daemon=True
    ).start()
```

- [ ] **Step 4: Call it in `lifespan` when the scheduler is absent**

In `lifespan`, immediately after the scheduler `try/except` block and before/after the
`maintenance_manager` fallback (~L68-71), add:

```python
    # If the scheduler did not start, the recurring embedding_backfill job won't run.
    # Heal missing vectors once off a daemon thread so recovery doesn't depend on it (#32).
    if not hasattr(app.state, "scheduler"):
        _start_backfill_fallback(engine)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/main.py tests/test_main_backfill_fallback.py
git add src/ormah/main.py tests/test_main_backfill_fallback.py
git commit -m "feat(server): scheduler-independent embedding backfill fallback (#32)"
```

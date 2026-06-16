# Task 09: Scheduler-independent fallback (retries with backoff)

Council **I1**: the server treats `start_scheduler` as optional (`lifespan` catches its failure
and keeps serving). With the synchronous startup re-embed gone (Task 05), a scheduler that
fails to start would leave missing vectors unhealed indefinitely. Add a narrow fallback: when
the scheduler did **not** start, kick reconciliation off a daemon thread (off the bind path,
so it never blocks) that **retries with exponential backoff until the gap closes or the
attempt budget is exhausted** — not a single one-shot. `run_embedding_backfill` raises while
the store is incomplete, so a transient encoder outage at startup doesn't leave vectors
unhealed until the next restart. The happy path is unchanged — the scheduler's post-bind
`next_run_time` (Task 07) still drives the first run and the recurring cadence.

**Files:**
- Modify: `src/ormah/main.py` (add constants + `_start_backfill_fallback`; call it in `lifespan` when the scheduler is absent)
- Test: `tests/test_main_backfill_fallback.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main_backfill_fallback.py`:

```python
"""Scheduler-independent embedding backfill fallback (#32, council I1).

The fallback retries with backoff until the gap closes (run_embedding_backfill
raises while it is incomplete) or the attempt budget is exhausted -- not a single
one-shot -- so a transient encoder outage at startup doesn't leave vectors
unhealed until the next restart.
"""
from __future__ import annotations

import time as _time

from ormah import main

real_sleep = _time.sleep


def _wait_for(predicate, timeout=2.0):
    waited = 0.0
    while not predicate() and waited < timeout:
        real_sleep(0.02)
        waited += 0.02


def test_fallback_runs_backfill_off_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        lambda engine: calls.append(engine),
    )
    sentinel = object()
    main._start_backfill_fallback(sentinel)  # returns immediately (off-thread)
    _wait_for(lambda: len(calls) >= 1)
    assert calls == [sentinel]


def test_fallback_retries_until_success(monkeypatch):
    calls = []

    def _flaky(engine):
        calls.append(engine)
        if len(calls) < 2:
            raise RuntimeError("still incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _flaky)
    monkeypatch.setattr("time.sleep", lambda s: real_sleep(0.001))

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 2)
    real_sleep(0.05)  # give a spurious 3rd attempt a chance to (not) happen
    assert len(calls) == 2  # retried once, then stopped on success


def test_fallback_gives_up_after_budget_without_raising(monkeypatch):
    calls = []

    def _boom(engine):
        calls.append(engine)
        raise RuntimeError("permanently incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _boom)
    monkeypatch.setattr("time.sleep", lambda s: real_sleep(0.001))

    main._start_backfill_fallback(object())  # must not raise on the main thread
    _wait_for(lambda: len(calls) >= main._BACKFILL_FALLBACK_MAX_ATTEMPTS)
    real_sleep(0.05)
    assert len(calls) == main._BACKFILL_FALLBACK_MAX_ATTEMPTS  # bounded, then gives up
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: FAIL — `AttributeError: module 'ormah.main' has no attribute '_start_backfill_fallback'`.

- [ ] **Step 3: Add the constants + fallback helper**

In `src/ormah/main.py`, add near the top-level helpers (module already has a `logger`):

```python
# Embedding-backfill fallback: how many times the daemon thread retries the
# reconciliation (with exponential backoff) before giving up. The recurring job /
# sleep-cycle remains the long-term net; this only covers a scheduler that failed
# to start plus a transient encoder outage at boot.
_BACKFILL_FALLBACK_MAX_ATTEMPTS = 5
_BACKFILL_FALLBACK_BASE_BACKOFF = 30.0  # seconds
_BACKFILL_FALLBACK_MAX_BACKOFF = 600.0  # seconds


def _start_backfill_fallback(engine) -> None:
    """Run embedding reconciliation off a daemon thread when the scheduler is
    unavailable, so missing vectors are still healed without it (#32, council I1).
    Off the bind path -- never blocks startup. Retries with exponential backoff
    until the gap closes (``run_embedding_backfill`` raises while incomplete) or
    the attempt budget is exhausted, instead of a single one-shot."""
    import threading
    import time

    def _run():
        from ormah.background.embedding_backfill import run_embedding_backfill

        for attempt in range(_BACKFILL_FALLBACK_MAX_ATTEMPTS):
            try:
                run_embedding_backfill(engine)
                return  # gap closed (the job raises while it is still incomplete)
            except Exception as e:
                logger.warning(
                    "Embedding backfill fallback attempt %d/%d failed: %s",
                    attempt + 1, _BACKFILL_FALLBACK_MAX_ATTEMPTS, e,
                )
                if attempt + 1 < _BACKFILL_FALLBACK_MAX_ATTEMPTS:
                    time.sleep(min(
                        _BACKFILL_FALLBACK_BASE_BACKOFF * (2 ** attempt),
                        _BACKFILL_FALLBACK_MAX_BACKOFF,
                    ))

    threading.Thread(
        target=_run, name="embedding-backfill-fallback", daemon=True
    ).start()
```

- [ ] **Step 4: Call it in `lifespan` when the scheduler is absent**

In `lifespan`, after the scheduler block (and alongside the `maintenance_manager` fallback),
add:

```python
    # If the scheduler did not start, its recurring embedding_backfill job won't
    # run. Heal missing vectors off a daemon thread so recovery doesn't depend on
    # the scheduler (#32, council I1). Off the bind path -- never blocks startup.
    if not hasattr(app.state, "scheduler"):
        _start_backfill_fallback(engine)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: PASS (3 tests — off-thread, retries-until-success, gives-up-after-budget).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/main.py tests/test_main_backfill_fallback.py
git add src/ormah/main.py tests/test_main_backfill_fallback.py
git commit -m "feat(server): scheduler-independent backfill fallback retries with backoff (#32)"
```

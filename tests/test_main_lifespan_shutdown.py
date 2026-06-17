"""Bounded scheduler shutdown + engine.shutdown() policy (Fix A / Fix D).

Tests the invariant: when the scheduler's shutdown(wait=True) does not
complete within _SHUTDOWN_TIMEOUT, engine.shutdown() must NOT be called
(avoids use-after-close). Symmetrically, when scheduler exits in time,
engine.shutdown() IS called (assuming fallback is not alive).

Design: avoids spinning up a full FastAPI + MemoryEngine for speed. We
exercise the decision logic via:
  1. A pure helper `_should_close_engine(fallback_alive, scheduler_alive)`
     extracted from the lifespan — unit-tests the policy table.
  2. A direct test that the scheduler-shutdown bounded path sets
     `scheduler_alive=True` when the scheduler.shutdown() blocks past the
     timeout (mock scheduler whose shutdown() blocks on an Event).
  3. An integration-style test that wires `_stop_backfill_fallback` + the
     scheduler bounded block together and asserts engine.shutdown() is NOT
     called when either is alive.
"""
from __future__ import annotations

import threading as _threading
import time as _time

import pytest

from ormah import main

real_sleep = _time.sleep


@pytest.fixture(autouse=True)
def _reset_fallback_state():
    main._stop_backfill_fallback()
    main._fallback_degraded = False
    yield
    main._stop_backfill_fallback()
    main._fallback_degraded = False


def _wait_for(predicate, timeout=2.0):
    waited = 0.0
    while not predicate() and waited < timeout:
        real_sleep(0.02)
        waited += 0.02


# ---------------------------------------------------------------------------
# 1. Pure policy helper — _should_close_engine
# ---------------------------------------------------------------------------

def test_should_close_engine_both_alive():
    assert main._should_close_engine(fallback_alive=True, scheduler_alive=True) is False


def test_should_close_engine_fallback_alive():
    assert main._should_close_engine(fallback_alive=True, scheduler_alive=False) is False


def test_should_close_engine_scheduler_alive():
    assert main._should_close_engine(fallback_alive=False, scheduler_alive=True) is False


def test_should_close_engine_neither_alive():
    assert main._should_close_engine(fallback_alive=False, scheduler_alive=False) is True


# ---------------------------------------------------------------------------
# 2. Bounded scheduler-shutdown: scheduler stuck past timeout → scheduler_alive=True
# ---------------------------------------------------------------------------

def test_scheduler_shutdown_timeout_sets_scheduler_alive(monkeypatch):
    """Fix A: scheduler.shutdown(wait=True) that blocks past _SHUTDOWN_TIMEOUT
    must result in scheduler_alive=True so engine.shutdown() is skipped."""
    monkeypatch.setattr(main, "_SHUTDOWN_TIMEOUT", 0.1)

    release = _threading.Event()

    class _BlockingScheduler:
        def shutdown(self, wait=True):
            # Simulates a job stuck in a non-interruptible encoder.encode()
            release.wait(timeout=10.0)

    scheduler_alive = main._bounded_scheduler_shutdown(_BlockingScheduler())

    assert scheduler_alive is True, (
        "scheduler_alive must be True when shutdown() does not complete within _SHUTDOWN_TIMEOUT"
    )
    # Cleanup
    release.set()


def test_scheduler_shutdown_completes_within_timeout(monkeypatch):
    """Fix A: scheduler.shutdown() that completes before timeout → scheduler_alive=False."""
    monkeypatch.setattr(main, "_SHUTDOWN_TIMEOUT", 5.0)

    class _QuickScheduler:
        def shutdown(self, wait=True):
            return  # exits immediately

    scheduler_alive = main._bounded_scheduler_shutdown(_QuickScheduler())

    assert scheduler_alive is False, (
        "scheduler_alive must be False when shutdown() completes before timeout"
    )


# ---------------------------------------------------------------------------
# 3. Integration: fallback preso → engine NOT closed
# ---------------------------------------------------------------------------

def test_engine_not_closed_when_fallback_alive(monkeypatch):
    """Fix D: when the fallback thread survives the join timeout, engine.shutdown()
    must NOT be called."""
    monkeypatch.setattr(main, "_FALLBACK_JOIN_TIMEOUT", 0.1)
    monkeypatch.setattr(main, "_SHUTDOWN_TIMEOUT", 0.1)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    release = _threading.Event()

    def _blocking_run(engine, stop_event=None):
        release.wait(timeout=10.0)

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        _blocking_run,
    )

    main._start_backfill_fallback(object())
    _wait_for(lambda: main._fallback_thread is not None
              and main._fallback_thread.is_alive(), timeout=2.0)

    fallback_alive = main._stop_backfill_fallback()

    shutdown_called = []

    class _FakeEngine:
        def shutdown(self):
            shutdown_called.append(True)

    if not main._should_close_engine(fallback_alive=fallback_alive, scheduler_alive=False):
        pass  # engine.shutdown() deliberately skipped
    else:
        _FakeEngine().shutdown()

    assert fallback_alive is True
    assert shutdown_called == [], "engine.shutdown() must NOT be called when fallback_alive=True"

    # Cleanup
    release.set()
    _wait_for(lambda: main._fallback_thread is None
              or not main._fallback_thread.is_alive(), timeout=3.0)
    with main._fallback_lock:
        main._fallback_thread = None
        main._fallback_stop_event = None


def test_engine_not_closed_when_scheduler_alive(monkeypatch):
    """Fix A: when scheduler shutdown does not complete in time, engine.shutdown()
    must NOT be called."""
    monkeypatch.setattr(main, "_SHUTDOWN_TIMEOUT", 0.1)

    release = _threading.Event()

    class _BlockingScheduler:
        def shutdown(self, wait=True):
            release.wait(timeout=10.0)

    scheduler_alive = main._bounded_scheduler_shutdown(_BlockingScheduler())

    shutdown_called = []

    class _FakeEngine:
        def shutdown(self):
            shutdown_called.append(True)

    if not main._should_close_engine(fallback_alive=False, scheduler_alive=scheduler_alive):
        pass
    else:
        _FakeEngine().shutdown()

    assert scheduler_alive is True
    assert shutdown_called == [], "engine.shutdown() must NOT be called when scheduler_alive=True"

    release.set()


def test_engine_closed_when_both_exit_cleanly(monkeypatch):
    """Positive path: both fallback and scheduler exit cleanly → engine.shutdown() called."""
    monkeypatch.setattr(main, "_FALLBACK_JOIN_TIMEOUT", 5.0)
    monkeypatch.setattr(main, "_SHUTDOWN_TIMEOUT", 5.0)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    def _quick_run(engine, stop_event=None):
        return  # exits immediately

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        _quick_run,
    )

    main._start_backfill_fallback(object())
    _wait_for(lambda: main._fallback_thread is not None, timeout=2.0)

    fallback_alive = main._stop_backfill_fallback()

    class _QuickScheduler:
        def shutdown(self, wait=True):
            return

    scheduler_alive = main._bounded_scheduler_shutdown(_QuickScheduler())

    shutdown_called = []

    class _FakeEngine:
        def shutdown(self):
            shutdown_called.append(True)

    if main._should_close_engine(fallback_alive=fallback_alive, scheduler_alive=scheduler_alive):
        _FakeEngine().shutdown()

    assert fallback_alive is False
    assert scheduler_alive is False
    assert shutdown_called == [True], "engine.shutdown() must be called when both exit cleanly"

"""Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).

The fallback retries indefinitely with backoff until the gap closes
(run_embedding_backfill raises while it is incomplete). Lifecycle is
controlled by a stop event and a singleton guard; _fallback_degraded exposes
a persistent outage to /admin/health while no scheduler exists.
"""
from __future__ import annotations

import threading as _threading
import time as _time

import pytest

from ormah import main

real_sleep = _time.sleep


@pytest.fixture(autouse=True)
def _reset_fallback_state():
    main._stop_backfill_fallback()  # tear down any thread a prior test started
    main._fallback_degraded = False
    yield
    main._stop_backfill_fallback()
    main._fallback_degraded = False


def _wait_for(predicate, timeout=2.0):
    waited = 0.0
    while not predicate() and waited < timeout:
        real_sleep(0.02)
        waited += 0.02


def test_fallback_runs_backfill_off_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        lambda engine, stop_event=None: calls.append(engine),
    )
    sentinel = object()
    main._start_backfill_fallback(sentinel)  # returns immediately (off-thread)
    _wait_for(lambda: len(calls) >= 1)
    assert calls == [sentinel]


def test_fallback_retries_until_success(monkeypatch):
    calls = []

    def _flaky(engine, stop_event=None):
        calls.append(engine)
        if len(calls) < 2:
            raise RuntimeError("still incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _flaky)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 2)
    real_sleep(0.05)  # give a spurious 3rd attempt a chance to (not) happen
    assert len(calls) == 2  # retried once, then stopped on success


def test_fallback_keeps_retrying_past_old_budget(monkeypatch):
    """C2: fallback does not give up after 5 attempts — retries until success."""
    calls = []

    def _mostly_failing(engine, stop_event=None):
        calls.append(engine)
        if len(calls) <= 6:  # fail more than the old hard budget of 5
            raise RuntimeError("still incomplete")
        # 7th call succeeds (returns None)

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        _mostly_failing,
    )
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 7, timeout=3.0)
    real_sleep(0.05)
    assert len(calls) == 7  # succeeded on the 7th attempt (past the old budget of 5)


def test_fallback_sets_degraded_flag_on_failure_clears_on_success(monkeypatch):
    """CH2: persistent failure is observable via _fallback_degraded; clears on recovery."""
    calls = []

    def _flaky(engine, stop_event=None):
        calls.append(engine)
        if len(calls) < 3:
            raise RuntimeError("still incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _flaky)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    # After the first failure, before success, the flag is set.
    _wait_for(lambda: main._fallback_degraded is True, timeout=2.0)
    assert main._fallback_degraded is True
    # On eventual success it clears.
    _wait_for(lambda: main._fallback_degraded is False and len(calls) >= 3, timeout=2.0)
    assert main._fallback_degraded is False


def test_fallback_is_singleton(monkeypatch):
    """CH1: a second start while one is alive does not spawn a second thread."""
    started = []

    def _block_forever(engine, stop_event=None):
        started.append(engine)
        raise RuntimeError("never closes")  # keeps the loop alive

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _block_forever)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: main._fallback_thread is not None
              and main._fallback_thread.is_alive(), timeout=2.0)
    first = main._fallback_thread
    main._start_backfill_fallback(object())  # second start — must be a no-op
    assert main._fallback_thread is first  # same thread, not replaced


def test_fallback_stops_on_shutdown(monkeypatch):
    """CH1: _stop_backfill_fallback stops a permanently-failing fallback."""
    calls = []

    def _boom(engine, stop_event=None):
        calls.append(engine)
        raise RuntimeError("permanently incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _boom)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 1, timeout=2.0)
    main._stop_backfill_fallback()
    assert main._fallback_thread is None or not main._fallback_thread.is_alive()
    settled = len(calls)
    real_sleep(0.1)
    assert len(calls) == settled  # no further attempts after stop


# ---------------------------------------------------------------------------
# Task B — new tests (CRB: atomic singleton, CR1 revert, stop_event forwarding)
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Blocks in backfill_embeddings until stop_event is set or 10s elapses.
    When stop_event is None (pre-implementation, stop_event not forwarded yet),
    blocks for the full safety-net duration so the thread stays alive long enough
    for the concurrent test to count it."""

    def __init__(self):
        self.entered = _threading.Event()
        self._internal_block = _threading.Event()

    def backfill_embeddings(self, stop_event=None):
        self.entered.set()
        # Use stop_event if provided, otherwise block on internal event (safety net 10s)
        waiter = stop_event if stop_event is not None else self._internal_block
        waiter.wait(timeout=10.0)
        return {"missing": 0}


class _QuickEngine:
    """Completes immediately with no missing nodes."""

    def backfill_embeddings(self, stop_event=None):
        return {"missing": 0}


class _CancellableEngine:
    """Loops checking stop_event; records whether it received it."""

    def __init__(self):
        self.entered = _threading.Event()
        self.saw_stop = False

    def backfill_embeddings(self, stop_event=None):
        self.entered.set()
        while True:
            if stop_event is not None and stop_event.is_set():
                self.saw_stop = True
                return {"missing": 0}
            _threading.Event().wait(timeout=0.01)


def _monkeypatch_run_embedding_backfill(monkeypatch):
    """Patch run_embedding_backfill to delegate to engine.backfill_embeddings(stop_event=...)."""
    def _fake_run(engine, stop_event=None):
        result = engine.backfill_embeddings(stop_event=stop_event)
        if result.get("missing", 0) > 0:
            raise RuntimeError(f"backfill incomplete: {result['missing']} missing")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        _fake_run,
    )


def test_concurrent_start_creates_single_thread(monkeypatch):
    """CRB: 8 threads racing _start_backfill_fallback must produce exactly 1 live thread."""
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    _monkeypatch_run_embedding_backfill(monkeypatch)

    engine = _FakeEngine()
    barrier = _threading.Barrier(8)

    def racer():
        barrier.wait()
        main._start_backfill_fallback(engine)

    threads = [_threading.Thread(target=racer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    alive = [
        t for t in _threading.enumerate()
        if t.name == "embedding-backfill-fallback" and t.is_alive()
    ]
    assert len(alive) == 1
    main._stop_backfill_fallback()


def test_stop_clears_handle(monkeypatch):
    """CR1 reverted: handle is always cleared after stop, even on quick completion."""
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    _monkeypatch_run_embedding_backfill(monkeypatch)

    main._start_backfill_fallback(_QuickEngine())
    main._stop_backfill_fallback()
    assert main._fallback_thread is None


def test_stop_cancels_long_backfill_within_join(monkeypatch):
    """stop_event is forwarded to the engine; handle is cleared; saw_stop is True."""
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    _monkeypatch_run_embedding_backfill(monkeypatch)

    eng = _CancellableEngine()
    main._start_backfill_fallback(eng)
    assert eng.entered.wait(timeout=2.0), "engine never entered backfill"
    main._stop_backfill_fallback()

    assert main._fallback_thread is None
    assert eng.saw_stop is True

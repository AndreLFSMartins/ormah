"""Scheduler-independent embedding backfill fallback (#32, council C2/CH1/CH2).

The fallback retries indefinitely with backoff until the gap closes
(run_embedding_backfill raises while it is incomplete). Lifecycle is
controlled by a stop event and a singleton guard; _fallback_degraded exposes
a persistent outage to /admin/health while no scheduler exists.
"""
from __future__ import annotations

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
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 2)
    real_sleep(0.05)  # give a spurious 3rd attempt a chance to (not) happen
    assert len(calls) == 2  # retried once, then stopped on success


def test_fallback_keeps_retrying_past_old_budget(monkeypatch):
    """C2: fallback does not give up after 5 attempts — retries until success."""
    calls = []

    def _mostly_failing(engine):
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

    def _flaky(engine):
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

    def _block_forever(engine):
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

    def _boom(engine):
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

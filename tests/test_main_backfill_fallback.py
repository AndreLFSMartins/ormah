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

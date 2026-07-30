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
  4. Per-lifespan stop event (R1): each lifespan execution creates a fresh
     Event in app.state so a reload cannot rearm an orphan worker.
"""
from __future__ import annotations

import contextlib
import threading as _threading
import time as _time

import pytest
from fastapi import FastAPI

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


# ---------------------------------------------------------------------------
# 4. Per-lifespan stop event (R1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_lifespan_gets_its_own_stop_event(tmp_path, monkeypatch):
    """R1: each lifespan execution must create a NEW threading.Event in
    app.state.lifecycle_stop_event. A reload must never reuse (or clear) the
    event from a previous lifespan so that orphan workers from a prior,
    expired shutdown cannot be rearmed.

    We monkeypatch heavy I/O (MemoryEngine, start_scheduler, watchers) so the
    test is fast and hermetic. The key invariants:
      - sched_ev1 is not sched_ev2  (distinct object per lifespan execution)
      - ev1 is sched_ev1 / ev2 is sched_ev2  (app.state holds the same object
        that was passed to start_scheduler)
    """
    import sys
    import threading

    # --- lightweight fakes ---

    class _FakeEngine:
        def startup(self): pass
        def shutdown(self): pass

    class _FakeScheduler:
        def shutdown(self, wait=True): pass

    class _FakeTracker:
        pass

    captured_stop_events: list[threading.Event] = []

    def _fake_start_scheduler(engine, stop_event=None):
        captured_stop_events.append(stop_event)
        return _FakeScheduler(), _FakeTracker()

    monkeypatch.setattr("ormah.main.MemoryEngine", lambda settings: _FakeEngine())
    monkeypatch.setattr(
        "ormah.main.settings",
        type(
            "S",
            (),
            {
                "port": 8787,
                "memory_dir": str(tmp_path),
                # #154 task 3: lifespan() now calls validate_llm_runtime_config(settings)
                # first thing, which reads these two fields. claude_cli/haiku mirrors the
                # _S fake later in this file (L496-499) — these tests exercise shutdown
                # behaviour, not config validation, so the guard must pass silently.
                "llm_provider": "claude_cli",
                "llm_model": "haiku",
            },
        )(),
    )
    monkeypatch.setattr("ormah.main.MaintenanceManager", lambda *a, **kw: object())

    # Use monkeypatch.setitem so pytest restores sys.modules on teardown,
    # preventing contamination of later tests (e.g. test_ingest_stores_node_ids).
    _fake_hippocampus = type(sys)("_fake_hippo")
    _fake_hippocampus.start_hippocampus = lambda engine: []
    _fake_hippocampus.stop_hippocampus = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.hippocampus", _fake_hippocampus)

    _fake_session_watcher = type(sys)("_fake_sw")
    _fake_session_watcher.start_session_watcher = lambda engine: []
    _fake_session_watcher.stop_session_watcher = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.session_watcher", _fake_session_watcher)

    _fake_scheduler_mod = type(sys)("_fake_sched")
    _fake_scheduler_mod.start_scheduler = _fake_start_scheduler
    monkeypatch.setitem(sys.modules, "ormah.background.scheduler", _fake_scheduler_mod)

    app = FastAPI(lifespan=main.lifespan)

    # --- first lifespan execution ---
    async with main.lifespan(app):
        ev1 = app.state.lifecycle_stop_event
        assert isinstance(ev1, threading.Event), "lifecycle_stop_event must be a threading.Event"

    # --- second lifespan execution (simulates in-process reload) ---
    async with main.lifespan(app):
        ev2 = app.state.lifecycle_stop_event
        assert isinstance(ev2, threading.Event), "lifecycle_stop_event must be a threading.Event"

    # Both lifespans must have passed a stop_event to start_scheduler
    assert len(captured_stop_events) == 2, (
        f"Expected 2 captured stop events, got {len(captured_stop_events)}"
    )
    sched_ev1, sched_ev2 = captured_stop_events

    # Invariant 1: each lifespan creates a DISTINCT Event — the R1 bug was
    # reusing (and clear()-ing) a single global Event across lifespans.
    assert sched_ev1 is not sched_ev2, (
        "Each lifespan must create a DISTINCT Event; reload must not reuse the old one (R1)"
    )

    # Invariant 2: app.state holds the same object that was passed to the scheduler
    assert ev1 is sched_ev1, (
        "app.state.lifecycle_stop_event must be the exact event passed to start_scheduler"
    )
    assert ev2 is sched_ev2, (
        "app.state.lifecycle_stop_event must be the exact event passed to start_scheduler"
    )

    # Invariant 3: both events were signalled during their respective shutdowns
    assert sched_ev1.is_set(), "First lifespan stop event must be set after its shutdown"
    assert sched_ev2.is_set(), "Second lifespan stop event must be set after its shutdown"


# ---------------------------------------------------------------------------
# 5. Always-on worker: shutdown drains the exact list startup stored (R1)
# ---------------------------------------------------------------------------

async def test_lifespan_shutdown_drains_always_on_worker(monkeypatch, tmp_path):
    """council R1: with the always-on worker, start_session_watcher returns a non-empty list
    even when disabled. The lifespan must store it on app.state.session_watches and shutdown
    must hand EXACTLY that list to stop_session_watcher — the bug this guards is startup
    writing the new app.state attribute while shutdown still reads the old observers one."""
    import sys

    class _FakeEngine:
        def startup(self): pass
        def shutdown(self): pass

    class _FakeScheduler:
        def shutdown(self, wait=True): pass

    class _FakeTracker:
        pass

    def _fake_start_scheduler(engine, stop_event=None):
        return _FakeScheduler(), _FakeTracker()

    monkeypatch.setattr("ormah.main.MemoryEngine", lambda settings: _FakeEngine())
    monkeypatch.setattr(
        "ormah.main.settings",
        type(
            "S",
            (),
            {
                "port": 8787,
                "memory_dir": str(tmp_path),
                # #154 task 3: lifespan() now calls validate_llm_runtime_config(settings)
                # first thing, which reads these two fields. claude_cli/haiku mirrors the
                # _S fake later in this file (L496-499) — these tests exercise shutdown
                # behaviour, not config validation, so the guard must pass silently.
                "llm_provider": "claude_cli",
                "llm_model": "haiku",
            },
        )(),
    )
    monkeypatch.setattr("ormah.main.MaintenanceManager", lambda *a, **kw: object())

    _fake_hippocampus = type(sys)("_fake_hippo")
    _fake_hippocampus.start_hippocampus = lambda engine: []
    _fake_hippocampus.stop_hippocampus = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.hippocampus", _fake_hippocampus)

    _fake_scheduler_mod = type(sys)("_fake_sched")
    _fake_scheduler_mod.start_scheduler = _fake_start_scheduler
    monkeypatch.setitem(sys.modules, "ormah.background.scheduler", _fake_scheduler_mod)

    sentinel = ["watch-sentinel"]
    stopped = []
    _fake_session_watcher = type(sys)("_fake_sw")
    _fake_session_watcher.start_session_watcher = lambda engine: sentinel
    _fake_session_watcher.stop_session_watcher = lambda w: stopped.append(w)
    _fake_session_watcher.run_session_reconcile = lambda w: 0
    monkeypatch.setitem(sys.modules, "ormah.background.session_watcher", _fake_session_watcher)

    app = FastAPI(lifespan=main.lifespan)
    async with main.lifespan(app):
        assert app.state.session_watches is sentinel
    assert stopped == [sentinel], "shutdown must drain the always-on worker"


# ---------------------------------------------------------------------------
# 6. ADR-0004 slice 2: LLM-cancellation ownership lives in the lifespan (council R7 HIGH-2 /
#    R1 HIGH-1), not in the watcher's shutdown/rollback sequence.
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _fake_lifespan_deps(tmp_path, monkeypatch, *, watcher_raises: bool = False):
    """Patch main.lifespan's heavy dependencies. Mirrors the fakes at L249-288."""
    import sys

    class _FakeEngine:
        def startup(self): pass
        def shutdown(self): pass

    class _FakeScheduler:
        def shutdown(self, wait=True): pass

    monkeypatch.setattr("ormah.main.MemoryEngine", lambda settings: _FakeEngine())
    monkeypatch.setattr(
        "ormah.main.settings",
        type(
            "S",
            (),
            {
                "port": 8787,
                "memory_dir": str(tmp_path),
                # #154 task 3: lifespan() now calls validate_llm_runtime_config(settings)
                # first thing, which reads these two fields. claude_cli/haiku mirrors the
                # _S fake later in this file (L496-499) — these tests exercise shutdown
                # behaviour, not config validation, so the guard must pass silently.
                "llm_provider": "claude_cli",
                "llm_model": "haiku",
            },
        )(),
    )
    monkeypatch.setattr("ormah.main.MaintenanceManager", lambda *a, **kw: object())

    _fake_hippocampus = type(sys)("_fake_hippo")
    _fake_hippocampus.start_hippocampus = lambda engine: []
    _fake_hippocampus.stop_hippocampus = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.hippocampus", _fake_hippocampus)

    def _raise(engine):
        raise RuntimeError("watcher down")

    _fake_session_watcher = type(sys)("_fake_sw")
    _fake_session_watcher.start_session_watcher = _raise if watcher_raises else (lambda engine: [])
    _fake_session_watcher.stop_session_watcher = lambda obs: None
    monkeypatch.setitem(sys.modules, "ormah.background.session_watcher", _fake_session_watcher)

    _fake_scheduler_mod = type(sys)("_fake_sched")
    _fake_scheduler_mod.start_scheduler = lambda engine, stop_event=None: (
        _FakeScheduler(), object()
    )
    monkeypatch.setitem(sys.modules, "ormah.background.scheduler", _fake_scheduler_mod)
    yield


@pytest.mark.asyncio
async def test_shutdown_cancels_llm_calls_even_when_the_watcher_failed_to_start(
    tmp_path, monkeypatch
):
    """R7 HIGH-2 regression.

    When start_session_watcher() raises, main.lifespan catches it at L274 and
    app.state.session_watches is never assigned — so the `if hasattr(...)` guard at L302
    skips stop_session_watcher(), which used to be the ONLY path calling
    cancel_active_llm_calls(). A scheduler-owned maintenance call then ran to its full
    provider timeout. The scheduler is an independent consumer of LLM calls; global
    cancellation must not depend on the watcher.
    """
    cancels: list[bool] = []

    def _record_cancel(*, final: bool = True) -> int:
        cancels.append(final)
        return 0

    monkeypatch.setattr(
        "ormah.background.llm_client.cancel_active_llm_calls", _record_cancel
    )

    with _fake_lifespan_deps(tmp_path, monkeypatch, watcher_raises=True):
        app = FastAPI(lifespan=main.lifespan)
        async with main.lifespan(app):
            assert not hasattr(app.state, "session_watches"), (
                "the fake watcher was supposed to raise before the assignment"
            )

    assert cancels, "shutdown never cancelled in-flight LLM calls"
    assert cancels[0] is True, "the lifespan's shutdown cancel must be final"


@pytest.mark.asyncio
async def test_a_second_lifespan_can_still_run_llm_calls(tmp_path, monkeypatch):
    """The adapter caches and the cancellation epoch are module-level and outlive a
    lifespan. A final cancel from the first shutdown must not poison the second -- proven
    here by actually driving an admitted LLM call through the facade in the second lifespan,
    not just reading the epoch snapshot (the old version of this test only asserted
    `snapshot()[1] is False`, so it would still pass even if admission itself stayed broken;
    this must fail if `begin_llm_lifespan()` is removed from lifespan startup)."""
    from ormah.background import llm_cancel, llm_client

    with _fake_lifespan_deps(tmp_path, monkeypatch):
        app = FastAPI(lifespan=main.lifespan)

        async with main.lifespan(app):
            pass
        _, cancelled_after_first = llm_cancel.snapshot()
        assert cancelled_after_first is True, "the first shutdown never cancelled"

        async with main.lifespan(app):
            _, cancelled_in_second = llm_cancel.snapshot()
            assert cancelled_in_second is False, (
                "the second lifespan started with a poisoned cancellation epoch"
            )

            # Restore the admission assertion the old test had (`llm_generate(...) == "ok"`):
            # a trivial fake adapter, driven through the real facade seam, proves calls are
            # actually ADMITTED in the second lifespan -- not merely that the epoch reads clean.
            llm_client.reset_adapter()

            class _FakeAdapter:
                def generate(self, *a, **kw):
                    return "ok"

            monkeypatch.setattr(llm_client, "get_adapter", lambda *a, **kw: _FakeAdapter())

            class _S:
                llm_provider = "claude_cli"
                llm_model = "haiku"
                ingest_llm_provider = None
                ingest_llm_model = None

            try:
                assert llm_client.llm_generate(_S(), "prompt") == "ok", (
                    "the second lifespan must be able to run an LLM call to completion"
                )
            finally:
                # Do not leak the fake adapter into the module-global cache for later tests.
                llm_client.reset_adapter()


@pytest.mark.asyncio
async def test_shutdown_cancels_llm_calls_when_the_lifespan_body_raises(tmp_path, monkeypatch):
    """Council R1 HIGH-1 regression.

    @asynccontextmanager throws a body exception at the `yield`, so teardown after a BARE yield is
    skipped. The cancel must sit in a `finally` so it still runs on the abnormal-shutdown path —
    exactly when a bounded shutdown matters. A bare-yield placement passes the normal-exit tests
    above and silently fails here."""
    cancels: list[bool] = []

    def _record_cancel(*, final: bool = True) -> int:
        cancels.append(final)
        return 0

    monkeypatch.setattr(
        "ormah.background.llm_client.cancel_active_llm_calls", _record_cancel
    )

    class _Boom(RuntimeError):
        pass

    with _fake_lifespan_deps(tmp_path, monkeypatch):
        app = FastAPI(lifespan=main.lifespan)
        with pytest.raises(_Boom):
            async with main.lifespan(app):
                raise _Boom("the app crashed mid-serve")

    assert cancels, "an abnormal shutdown skipped the LLM cancel (cancel not in a finally)"
    assert cancels[0] is True


"""Tests for the shared LLM facade — provider-configured detection."""
from __future__ import annotations

import contextlib
import threading

from ormah.background import llm_client
from ormah.background.llm_client import reset_adapter


def test_ingest_provider_configured_reflects_adapter(monkeypatch):
    reset_adapter()
    monkeypatch.setattr(llm_client, "get_adapter", lambda *a, **k: None)
    assert llm_client.ingest_provider_configured(object()) is False

    reset_adapter()
    sentinel = object()
    monkeypatch.setattr(llm_client, "get_adapter", lambda *a, **k: sentinel)

    class _S:
        ingest_llm_provider = "claude_cli"
        llm_provider = "claude_cli"
        ingest_llm_model = "claude-haiku-4-5-20251001"
        llm_model = "claude-haiku-4-5-20251001"

    assert llm_client.ingest_provider_configured(_S()) is True
    reset_adapter()


def test_cancel_and_resume_isolate_a_raising_adapter(monkeypatch):
    """ITEM 2 (council-pr R4, Codex): the loop visits _cached_adapter (maintenance) BEFORE
    _cached_ingest_adapter with no try per adapter. A consistently raising maintenance adapter
    killed the function there, so the INGEST adapter was never cancelled. Combined with the R3
    HIGH-3 fix — which now SUPPRESSES that exception in _stop_and_drain — every turn of the join
    fence restarted on the same raising adapter, so the fence spun without ever cancelling what
    mattered and waited out the provider timeout. The suppression we added to keep the fence
    running had made the fence useless on exactly the degraded path it was meant to tolerate.

    resume_llm_adapters() has the same defect in the twin function: if the first resume() raises,
    the second never runs and that adapter stays permanently cancelled."""

    class _RaisingAdapter:
        def cancel_active(self):
            raise RuntimeError("maintenance adapter blew up on cancel")

        def resume(self):
            raise RuntimeError("maintenance adapter blew up on resume")

    class _RecordingAdapter:
        def __init__(self):
            self.cancelled = 0
            self.resumed = 0

        def cancel_active(self):
            self.cancelled += 1
            return 1

        def resume(self):
            self.resumed += 1

    ingest = _RecordingAdapter()
    monkeypatch.setattr(llm_client, "_cached_adapter", _RaisingAdapter())
    monkeypatch.setattr(llm_client, "_adapter_initialised", True)
    monkeypatch.setattr(llm_client, "_cached_ingest_adapter", ingest)
    monkeypatch.setattr(llm_client, "_ingest_adapter_initialised", True)

    total = llm_client.cancel_active_llm_calls()
    assert ingest.cancelled == 1, \
        "a raising maintenance adapter must not stop the INGEST adapter from being cancelled"
    assert total == 1, "the surviving adapter's count is still reported"

    llm_client.resume_llm_adapters()
    assert ingest.resumed == 1, \
        "a raising maintenance resume must not leave the INGEST adapter permanently cancelled"


def _concurrent_first_use(factory, cache_name, monkeypatch):
    """Drive two threads into ``factory`` on FIRST use simultaneously and return
    (call_count, result_a, result_b, cached). A Barrier holds both inside the patched
    get_adapter at once on the unsynchronised code; under the lock only one can be there so the
    barrier times out and the second caller short-circuits on the initialised flag."""
    reset_adapter()
    call_count = [0]
    count_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def fake_get_adapter(*a, **k):
        with count_lock:
            call_count[0] += 1
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=1.5)
        return object()

    monkeypatch.setattr(llm_client, "get_adapter", fake_get_adapter)

    results = {}

    def _call(key):
        results[key] = factory(object())

    t1 = threading.Thread(target=_call, args=("a",))
    t2 = threading.Thread(target=_call, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    cached = getattr(llm_client, cache_name)
    reset_adapter()
    return call_count[0], results.get("a"), results.get("b"), cached


def test_concurrent_first_use_creates_exactly_one_adapter(monkeypatch):
    """HIGH-1 (council-pr, Codex): two drain threads on distinct acceptance roots enter the lazy
    factory on first use at the same time. The lock must guarantee get_adapter() runs ONCE and
    both threads observe the SAME cached adapter — otherwise the displaced first adapter keeps an
    in-flight call that cancel_active_llm_calls() (it visits only the cached global) can never
    reach, so shutdown waits the full provider timeout."""
    calls, a, b, cached = _concurrent_first_use(
        llm_client._get_or_create_adapter, "_cached_adapter", monkeypatch
    )
    assert calls == 1, f"get_adapter must run exactly once, ran {calls}x"
    assert a is b, "both threads must observe the same cached adapter"
    assert cached is a, "the cache must hold the one adapter both threads use"


def test_concurrent_first_use_ingest_adapter_is_single(monkeypatch):
    """Same guarantee for the ingest factory — the cache cancel_active_llm_calls() actually
    visits for server-side extraction (_cached_ingest_adapter)."""
    calls, a, b, cached = _concurrent_first_use(
        llm_client._get_or_create_ingest_adapter, "_cached_ingest_adapter", monkeypatch
    )
    assert calls == 1, f"get_adapter must run exactly once, ran {calls}x"
    assert a is b, "both threads must observe the same cached ingest adapter"
    assert cached is a, "the cache must hold the one ingest adapter both threads use"

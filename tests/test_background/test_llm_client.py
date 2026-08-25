"""Tests for the shared LLM facade — provider-configured detection."""
from __future__ import annotations

import contextlib
import threading

import pytest

from ormah.background import llm_client
from ormah.background.llm.ollama_adapter import OllamaAdapter
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
    both threads observe the SAME cached adapter — otherwise the displaced first adapter is a
    wasted construction (its process/connection spun up only to be thrown away when the second
    assignment overwrites the cache). ADR-0004 slice 2's cancellation epoch is global and reaches
    any adapter's generate() regardless of caching, so a duplicate is no longer an uncancellable
    call — it is simply waste this lock avoids."""
    calls, a, b, cached = _concurrent_first_use(
        llm_client._get_or_create_adapter, "_cached_adapter", monkeypatch
    )
    assert calls == 1, f"get_adapter must run exactly once, ran {calls}x"
    assert a is b, "both threads must observe the same cached adapter"
    assert cached is a, "the cache must hold the one adapter both threads use"


def test_concurrent_first_use_ingest_adapter_is_single(monkeypatch):
    """Same guarantee for the ingest factory (_cached_ingest_adapter): the lock must still
    guarantee at most one adapter is constructed for server-side extraction."""
    calls, a, b, cached = _concurrent_first_use(
        llm_client._get_or_create_ingest_adapter, "_cached_ingest_adapter", monkeypatch
    )
    assert calls == 1, f"get_adapter must run exactly once, ran {calls}x"
    assert a is b, "both threads must observe the same cached ingest adapter"
    assert cached is a, "the cache must hold the one ingest adapter both threads use"


def test_an_adapter_built_during_a_shutdown_is_born_cancelled(monkeypatch):
    """R6 regression. A factory holds _adapter_lock across get_adapter(), and during that
    window the cache global is still None. The old sweep enumerated the cache, saw nothing,
    returned 0 — and the factory then published an UNCANCELLED adapter that spawned a child.

    HONEST fake (council R1 HIGH-2): the adapter does NOT read llm_cancel — real Ollama/LiteLLM
    adapters don't either. The FACADE seam is what rejects the call: `llm_generate` snapshots
    the epoch AFTER `_get_or_create_adapter` returns, so it observes the cancel that landed
    while the factory held _adapter_lock, and admission raises before the fake ever runs a
    cancelled call. This is exactly the provider-independent gate the old design lacked."""
    from ormah.background import llm_cancel, llm_client

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()

    in_factory = threading.Event()
    may_finish = threading.Event()

    class _FakeAdapter:
        def generate(self, *a, **kw):
            return "UNCANCELLED_SUCCESS"   # dumb adapter; the facade seam does the gating

    def slow_get_adapter(settings, provider=None, model=None):
        in_factory.set()
        may_finish.wait(timeout=5)      # holds _adapter_lock, as the real factory does
        return _FakeAdapter()

    monkeypatch.setattr(llm_client, "get_adapter", slow_get_adapter)

    class _S:
        llm_provider = "claude_cli"
        llm_model = "haiku"
        ingest_llm_provider = None
        ingest_llm_model = None

    result: dict = {}

    def first_call():
        result["out"] = llm_client.llm_generate(_S(), "hi")

    t = threading.Thread(target=first_call)
    t.start()
    assert in_factory.wait(timeout=5), "the factory never entered"

    llm_client.cancel_active_llm_calls()   # the shutdown lands exactly in the window
    may_finish.set()
    t.join(timeout=10)
    assert not t.is_alive()

    assert result.get("out") != "UNCANCELLED_SUCCESS", (
        "an adapter published during a shutdown ran an uncancelled call"
    )
    llm_client.reset_adapter()


def test_facade_rejects_output_produced_after_a_mid_call_cancel(monkeypatch):
    """IMPORTANT-1 (final review). Deleting the post-call `if llm_cancel.epoch_changed(gen):
    raise LlmCancelledError(...)` line in `_guarded_generate` passes the ENTIRE suite -- it is
    the only thing protecting a non-claude_cli provider (Ollama/LiteLLM, or any future adapter)
    from having a cancelled call's output accepted, since those providers cannot be interrupted
    mid-flight and just keep running until their HTTP timeout.

    Simulates exactly that: a dumb fake adapter whose generate() calls
    `llm_cancel.begin_cancel(final=True)` -- a cancel landing WHILE the call is in flight -- and
    then returns a normal value, as an uninterruptible provider would. The fake does NOT read
    `llm_cancel` to decide what to return; the whole point is that the FACADE, not the adapter,
    is what must reject the output."""
    from ormah.background import llm_cancel
    from ormah.background.llm_errors import LlmCancelledError

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()

    class _FakeAdapter:
        def generate(self, *a, **kw):
            llm_cancel.begin_cancel(final=True)  # cancel lands mid-call
            return "STALE_OUTPUT_FROM_AN_UNINTERRUPTIBLE_CALL"

    monkeypatch.setattr(llm_client, "get_adapter", lambda *a, **kw: _FakeAdapter())

    class _S:
        llm_provider = "claude_cli"
        llm_model = "haiku"
        ingest_llm_provider = "claude_cli"
        ingest_llm_model = "haiku"

    with pytest.raises(LlmCancelledError):
        llm_client.ingest_llm_generate(_S(), "prompt")

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()


def test_ingest_propagates_cancel_while_maintenance_swallows_it(monkeypatch):
    """IMPORTANT-2 (final review). Wrapping `ingest_llm_generate`'s call in
    `except LlmCancelledError: return None` passes the entire suite too -- this asymmetry
    (maintenance swallows a cancel to None; ingest propagates it) is the whole point of the
    slice: a propagated cancel maps to a provider-wide transient so a cancelled extraction never
    advances the cursor nor burns the per-slice failure cap (see
    `memory_engine._extract_memories_llm`), while a maintenance call swallowing to None keeps its
    pre-slice contract unchanged.

    With the epoch already cancelled before either call starts, assert BOTH sides in one test:
    `ingest_llm_generate` raises `LlmCancelledError`, `llm_generate` returns `None`."""
    from ormah.background import llm_cancel
    from ormah.background.llm_errors import LlmCancelledError

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()

    class _FakeAdapter:
        def generate(self, *a, **kw):
            raise AssertionError("generate() must not run once the epoch is cancelled")

    monkeypatch.setattr(llm_client, "get_adapter", lambda *a, **kw: _FakeAdapter())

    class _S:
        llm_provider = "claude_cli"
        llm_model = "haiku"
        ingest_llm_provider = "claude_cli"
        ingest_llm_model = "haiku"

    llm_cancel.begin_cancel(final=True)  # epoch already cancelled before either call starts

    with pytest.raises(LlmCancelledError):
        llm_client.ingest_llm_generate(_S(), "prompt")

    assert llm_client.llm_generate(_S(), "prompt") is None

    llm_client.reset_adapter()
    llm_cancel.begin_lifespan()


class _StubAdapter:
    def generate(self, prompt, **kwargs):
        return "{}"


@pytest.fixture
def captured_num_ctx(monkeypatch):
    """Capture the num_ctx get_adapter is called with, with a clean adapter cache."""
    seen = {}

    def fake_get_adapter(settings, num_ctx=None):
        seen["num_ctx"] = num_ctx
        return _StubAdapter()

    monkeypatch.setattr(llm_client, "get_adapter", fake_get_adapter)
    llm_client.reset_adapter()
    yield seen
    llm_client.reset_adapter()


class TestConsolidationRoute:
    """#192: only the consolidation route pins an input window it can prove."""

    def test_consolidation_route_derives_num_ctx_from_the_budget(self, settings, captured_num_ctx):
        settings.llm_provider = "ollama"
        settings.consolidation_max_prompt_chars = 24000
        settings.llm_num_predict = 4096

        llm_client.llm_generate(settings, "prompt", route="consolidation")

        assert captured_num_ctx["num_ctx"] == 16096  # 24000/2 chars-per-token + 4096 output

    def test_shared_maintenance_adapter_still_omits_num_ctx(self, settings, captured_num_ctx):
        """auto_linker, conflict_detector and duplicate_merger share this adapter and must not
        pay the consolidation KV cache."""
        settings.llm_provider = "ollama"

        llm_client.llm_generate(settings, "prompt")

        assert captured_num_ctx["num_ctx"] is None

    def test_reset_adapter_clears_the_consolidation_cache(self, settings, captured_num_ctx):
        settings.llm_provider = "ollama"
        settings.consolidation_max_prompt_chars = 24000
        settings.llm_num_predict = 4096
        llm_client.llm_generate(settings, "prompt", route="consolidation")

        llm_client.reset_adapter()
        settings.consolidation_max_prompt_chars = 40000
        llm_client.llm_generate(settings, "prompt", route="consolidation")

        assert captured_num_ctx["num_ctx"] == 24096, "the cache was not rebuilt after reset"


class TestOllamaInputWindow:
    """num_ctx=None must OMIT the key, never substitute a default of our own."""

    def test_num_ctx_defaults_to_none(self):
        adapter = OllamaAdapter(model="m")
        assert adapter.num_ctx is None

    def test_num_ctx_reaches_the_ollama_options(self, monkeypatch):
        sent = {}

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "{}"}

        def fake_post(url, json=None, timeout=None):
            sent.update(json)
            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "post", fake_post)

        OllamaAdapter(model="m", num_ctx=16096).generate("p")
        assert sent["options"]["num_ctx"] == 16096

        sent.clear()
        OllamaAdapter(model="m").generate("p")
        assert "num_ctx" not in sent["options"]

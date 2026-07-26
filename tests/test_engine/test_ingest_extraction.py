"""Extraction error classification: timeout/call-failure must not read as 'no provider'."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ormah.engine.memory_engine import (
    EXTRACT_ERR_CALL_FAILED,
    EXTRACT_ERR_NO_PROVIDER,
    _split_for_extraction,
)

_CONTENT = "User asked about X. " * 20  # > 50 chars so extraction runs


def test_extraction_call_failure_is_distinct_from_no_provider(engine):
    # ingest_llm_generate is imported locally inside _extract_memories_llm (per call),
    # so it must be patched at its defining module (ormah.background.llm_client) —
    # matching the convention used by every other ingest test (see test_ingest.py's
    # _LLM_PATCH). ingest_provider_configured is imported at module scope in
    # memory_engine, so it is patched there instead.
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(_CONTENT)
    assert result == EXTRACT_ERR_CALL_FAILED

    # No provider configured -> the honest "unavailable" message.
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=False):
        result = engine._extract_memories_llm(_CONTENT)
    assert result == EXTRACT_ERR_NO_PROVIDER


def test_cancelled_extraction_maps_to_call_failed_not_slice_failure(engine):
    """A LlmCancelledError from the adapter (shutdown/stop mid-extraction, ADR-0004 slice 2)
    must surface as EXTRACT_ERR_CALL_FAILED (provider-wide transient), NOT as a slice-specific
    failure that _ingest_session would count toward MAX_EXTRACT_FAILURES and eventually skip
    (data loss). Must be caught BEFORE the generic `except Exception` handler."""
    from ormah.background.llm_errors import LlmCancelledError

    def _raise(*a, **k):
        raise LlmCancelledError("shutdown")

    with patch("ormah.background.llm_client.ingest_llm_generate", side_effect=_raise):
        result = engine._extract_memories_llm(_CONTENT)
    assert result == EXTRACT_ERR_CALL_FAILED


def test_oversized_payload_is_chunked_not_truncated(engine):
    """Content larger than ingest_chunk_chars is split at line boundaries and every chunk is
    extracted — the tail is never dropped."""
    engine.settings.ingest_chunk_chars = 100  # tiny, to force multiple chunks
    # 5 lines * ~60 chars = ~300 chars -> at least 3 chunks of <=100.
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        # Each chunk yields one memory tagged with the call index so we can count.
        return json.dumps({"memories": [
            {"content": f"mem for call {len(calls)}", "type": "fact", "title": "t"},
        ]})

    with patch("ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert isinstance(result, list)
    assert len(calls) >= 3            # split into >=3 chunks
    assert len(result) == len(calls)  # every chunk's memory survived (no tail drop)


def test_partial_chunk_failure_is_retryable(engine):
    """A single failing chunk makes the WHOLE slice a retryable error (council B1): a partial
    commit would advance the byte cursor past unextracted content = permanent silent loss.
    Instead the partial result is discarded so session_watcher's per-slice cap retries the whole
    slice and durably quarantines it after MAX_EXTRACT_FAILURES."""
    engine.settings.ingest_chunk_chars = 100
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    calls = []

    def fake_generate(settings, prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 2:  # fail the second chunk
            return None
        return json.dumps({"memories": [
            {"content": f"mem for call {len(calls)}", "type": "fact", "title": "t"},
        ]})

    with patch("ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert result == EXTRACT_ERR_CALL_FAILED  # retryable, not a partial list
    assert len(calls) == 2  # short-circuits at the first failure — no wasted calls on later chunks


def test_all_chunks_failing_returns_retryable_error(engine):
    """If every chunk's call fails while a provider is configured, the whole extraction is a
    retryable error (so Task 04's per-slice cap governs it)."""
    engine.settings.ingest_chunk_chars = 100
    content = "\n".join(f"Turn {i}: " + "x" * 50 for i in range(5))

    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=None), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        result = engine._extract_memories_llm(content)

    assert result == EXTRACT_ERR_CALL_FAILED


def test_confidence_floor_drops_low_value_memories(engine):
    """Extracted memories below ingest_min_confidence are dropped before node creation."""
    engine.settings.ingest_min_confidence = 0.5
    resp = json.dumps({"memories": [
        {"content": "keep me", "type": "fact", "title": "hi", "confidence": 0.9},
        {"content": "drop me", "type": "fact", "title": "lo", "confidence": 0.2},
    ]})
    with patch("ormah.background.llm_client.ingest_llm_generate", return_value=resp), \
         patch("ormah.engine.memory_engine.ingest_provider_configured", return_value=True):
        created = engine.ingest_conversation(content="x" * 100, space="test")

    titles = [c["title"] for c in created]
    assert "hi" in titles
    assert "lo" not in titles


def test_oversized_line_is_split_not_truncated():
    """A single line (turn) longer than hard_cap is split into <=hard_cap pieces, never truncated:
    reassembling the chunks reproduces the input exactly, so no tail is dropped and the byte cursor
    never advances past unextracted content (council-pr C2)."""
    content = "x" * 5000  # one line, no turn boundaries
    chunks = _split_for_extraction(content, chunk_chars=1000, hard_cap=1000)
    assert len(chunks) == 5
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == content  # nothing dropped


def test_oversized_line_among_normal_turns_loses_nothing():
    """An oversized turn between normal turns is split without dropping any turn or its tail."""
    content = "short turn 1\n" + "y" * 2500 + "\n" + "short turn 2\n"
    chunks = _split_for_extraction(content, chunk_chars=1000, hard_cap=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == content  # every turn + the oversized tail preserved


# --- provider fit: payload-derived timeout + pinned Ollama input window (ADR-0001 Amendment 3) ---

def test_extraction_passes_a_payload_proportional_timeout_hint(tmp_path):
    """A variable payload against a fixed provider timeout is the bug. The hint must grow with
    the payload, using the same base+rate idiom as pair_batch."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 1000)
            small = hints[-1]
            engine._extract_memories_llm("x" * 50000)
            large = hints[-1]
    finally:
        engine.shutdown()

    assert small is not None, "ingest still sends no timeout hint at all"
    assert large > small, "the hint does not scale with the payload"


def test_timeout_hint_never_lowers_the_active_provider_baseline(tmp_path):
    """Council R1, both peers: adapters treat the hint as a REPLACEMENT
    (`timeout_hint_seconds or self.timeout`), and claude_cli's own baseline is 120s while
    llm_timeout_seconds is 60s. A hint derived from the 60s base would hand a short flush 84s --
    a regression on the most common path. The hint must be a floor-raiser, never a reducer."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(
        memory_dir=tmp_path, ingest_llm_provider="claude_cli", ingest_llm_model="haiku",
    )
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 1000)   # tiny: the derived term is negligible
    finally:
        engine.shutdown()

    assert hints[-1] >= settings.claude_cli_timeout_seconds, (
        f"hint {hints[-1]}s is BELOW the claude_cli baseline "
        f"{settings.claude_cli_timeout_seconds}s -- this regresses short flushes"
    )


def test_extraction_timeout_hint_is_bounded(tmp_path):
    """A hung provider must not be waited on indefinitely just because the payload was big.

    The provider is pinned to ollama on purpose. ``ingest_timeout_max_seconds=100`` is only a
    LEGAL config under a provider whose own baseline is <= 100 (the cross-field validator rejects
    a cap below the active baseline), and the ambient ~/.config/ormah/.env sets
    ORMAH_INGEST_LLM_PROVIDER=claude_cli (baseline 120) -- so leaving the provider implicit would
    make this fixture pass or ValidationError depending on the machine.
    """
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(
        memory_dir=tmp_path, ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat",
        ingest_timeout_max_seconds=100,
    )
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 60000)
    finally:
        engine.shutdown()

    # == not <=: a 60000-char payload derives ~457s, so the cap is what MUST produce this number.
    # `<= 100` would also hold if the size term were dropped entirely.
    assert hints[-1] == 100


def test_timeout_max_below_the_provider_baseline_is_rejected():
    """min(max(baseline, derived), max) still returns `max` when max < baseline -- recreating the
    very short-flush regression the floor exists to remove. Reject that config at boot."""
    from pydantic import ValidationError

    from ormah.config import Settings

    with pytest.raises(ValidationError):
        Settings(ingest_llm_provider="claude_cli", ingest_llm_model="haiku",
                 ingest_timeout_max_seconds=100)   # claude_cli baseline is 120


def test_ollama_adapter_pins_the_input_window():
    """num_predict bounds OUTPUT; num_ctx bounds INPUT. Leaving num_ctx unset inherits the
    Ollama server's default, which we neither control nor version -- and a default below the
    payload truncates the prompt SILENTLY, killing recall with no signal."""
    from ormah.background.llm.ollama_adapter import OllamaAdapter

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _Resp()

    import httpx
    original = httpx.post
    httpx.post = fake_post
    try:
        OllamaAdapter(model="gemma3:12b-it-qat", num_ctx=70000).generate("hello")
    finally:
        httpx.post = original

    assert captured["options"]["num_ctx"] == 70000


def test_factory_passes_configured_num_ctx_to_the_request():
    """The constructor default must never be what ships -- the value an operator sets has to reach
    the actual HTTP request.

    Driven through ``ingest_llm_generate`` rather than ``get_adapter(settings)``: ``num_ctx`` is a
    THREADED factory parameter (maintenance must not pay for the ingest window), so only the ingest
    adapter factory in llm_client.py reads ``settings.ollama_num_ctx``. Calling ``get_adapter``
    bare would assert the constructor default and prove nothing about the wiring.
    """
    import httpx

    from ormah.background.llm_client import ingest_llm_generate, reset_adapter
    from ormah.config import Settings

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    original = httpx.post
    httpx.post = lambda url, json=None, timeout=None: (captured.update(json), _Resp())[1]
    reset_adapter()
    try:
        # 70000, not 8192: the boot validator rejects a window too small for the worst
        # payload, so an 8192 fixture would ValidationError before reaching the factory.
        settings = Settings(
            llm_provider="ollama", llm_model="gemma3:12b-it-qat",
            ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat",
            ollama_num_ctx=70000,
        )
        ingest_llm_generate(settings, "hello")
    finally:
        httpx.post = original
        reset_adapter()

    assert captured["options"]["num_ctx"] == 70000


def test_maintenance_adapter_does_not_inherit_the_ingest_window():
    """Council R3 (Codex): get_adapter builds BOTH adapters. Wiring ollama_num_ctx unconditionally
    would hand every maintenance pair-judging call a 65536-token KV cache -- a large memory cost and
    a plausible OOM on a local machine, for no benefit (maintenance judges small pairs)."""
    import httpx

    from ormah.background.llm_client import llm_generate, reset_adapter
    from ormah.config import Settings

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    original = httpx.post
    httpx.post = lambda url, json=None, timeout=None: (captured.update(json), _Resp())[1]
    reset_adapter()
    try:
        settings = Settings(
            llm_provider="ollama", llm_model="gemma3:12b-it-qat",
            ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat",
            ollama_num_ctx=70000,
        )
        llm_generate(settings, "hello")
    finally:
        httpx.post = original
        reset_adapter()

    # Pinned, not "!= 70000": the contract is that maintenance sends NO num_ctx key at all, so the
    # operator's server/Modelfile window stays in charge. A hardcoded adapter-side default would
    # satisfy "!= 70000" while silently narrowing every pair-judging call -- pair_batch renders K
    # pairs into one ~40K-char prompt and parse_batch_verdicts accepts a PARTIAL verdict list, so
    # the truncation would under-judge without erroring.
    assert "num_ctx" not in captured["options"]


def test_prompt_overhead_tracks_the_real_template():
    """If the extraction prompt grows and this drifts, the boot guarantee silently weakens."""
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT
    from ormah.ingest_capacity import prompt_overhead_chars

    assert prompt_overhead_chars() == len(_INGEST_LLM_PROMPT.format(conversation=""))
    assert prompt_overhead_chars() > 100   # a plausible template, not an empty string


def test_capacity_preflight_refuses_an_oversized_prompt():
    """Unit-test the estimator directly.

    It cannot be driven through Settings any more: the boot validator now rejects any config whose
    window is too small for the largest emittable payload, which is exactly what makes the runtime
    refusal unreachable in normal operation. The preflight stays as a guard against paths that
    bypass validation (mutated engine.settings, a future config route) and against content denser
    than the estimator's bound.
    """
    from types import SimpleNamespace

    from ormah.engine.memory_engine import _prompt_exceeds_provider_capacity

    tight = SimpleNamespace(
        ingest_llm_provider="ollama", llm_provider="ollama",
        ollama_num_ctx=8192, llm_num_predict=4096,   # usable 4096 tokens
    )
    assert _prompt_exceeds_provider_capacity(tight, "x" * 60000) is not None
    assert _prompt_exceeds_provider_capacity(tight, "x" * 100) is None

    # Non-ollama providers are not introspectable, so the guard must stay silent rather than
    # invent a limit and reject valid work.
    other = SimpleNamespace(ingest_llm_provider="claude_cli", llm_provider="claude_cli")
    assert _prompt_exceeds_provider_capacity(other, "x" * 10_000_000) is None


def test_refusal_returns_the_retryable_sentinel_and_sends_nothing(tmp_path):
    """When the guard does fire, nothing may reach the provider and the cursor must not advance."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import EXTRACT_ERR_CALL_FAILED, MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)   # boot-valid
    engine = MemoryEngine(settings)
    engine.startup()
    calls = []

    try:
        # Bypass validation deliberately: this is the path the guard exists to cover.
        engine.settings.ingest_llm_provider = "ollama"
        engine.settings.ollama_num_ctx = 8192
        with patch(
            "ormah.background.llm_client.ingest_llm_generate",
            side_effect=lambda *a, **k: calls.append(1) or '{"memories": []}',
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            out = engine._extract_memories_llm("x" * 60000)
    finally:
        engine.shutdown()

    assert not calls, "the oversized prompt was SENT — the provider will truncate it silently"
    assert out == EXTRACT_ERR_CALL_FAILED, "must return the retryable sentinel, not any string"


def test_ollama_window_too_small_for_the_worst_payload_fails_at_boot():
    """Deterministic capacity failure must surface at startup, not as a transcript that retries
    forever (the refusal is TRANSIENT and never reaches the failure cap)."""
    from pydantic import ValidationError

    from ormah.config import Settings

    with pytest.raises(ValidationError):
        Settings(ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat",
                 ollama_num_ctx=8192)


def test_default_ollama_window_admits_the_worst_payload():
    """The shipped default must not fail its own boot check."""
    from ormah.config import Settings
    from ormah.ingest_capacity import estimated_tokens, prompt_overhead_chars, usable_input_tokens

    s = Settings(ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat")
    worst = estimated_tokens(s.ingest_max_content_chars + prompt_overhead_chars())
    assert worst <= usable_input_tokens(s)


def test_ollama_num_ctx_must_be_positive():
    """The cross-field capacity check only runs on the ollama branch, so a non-ollama config would
    otherwise accept a zero/negative window outright."""
    from pydantic import ValidationError

    from ormah.config import Settings

    with pytest.raises(ValidationError):
        Settings(ollama_num_ctx=0)
    with pytest.raises(ValidationError):
        Settings(ollama_num_ctx=-1)


# --- CRITICAL regression: the boot validator must not drag memory_engine into import time ---

def _run_in_subprocess(code: str):
    """Run `code` in a fresh interpreter pinned to the SAME source tree as this test.

    A subprocess is not optional here. Inside pytest, `ormah.config` is already in `sys.modules`
    long before these tests run, and importing it first is exactly what MASKS the cycle -- an
    in-process assertion could never fail. The PYTHONPATH pin is derived from the live `ormah`
    package so the child cannot silently resolve an editable install pointing at another clone.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import ormah

    env = {
        **os.environ,
        "PYTHONPATH": str(Path(ormah.__file__).resolve().parents[1]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "ORMAH_LLM_PROVIDER": "ollama",
        "ORMAH_INGEST_LLM_PROVIDER": "ollama",
        "ORMAH_INGEST_LLM_MODEL": "gemma3:12b-it-qat",
    }
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=180,
    )


def test_importing_memory_engine_first_under_ollama_does_not_cycle():
    """config.py builds a module-level `settings = Settings()`, so the ollama capacity validator
    runs during `import ormah.config`. Reaching the prompt overhead through
    engine/memory_engine.py -- which itself imports ormah.config -- made that a REAL circular
    import: `import ormah.engine.memory_engine` crashed, while `import ormah.config` first
    survived, so whether a process lived depended purely on module load order. `make server` is
    `python -m ormah.main`.

    The failing configuration is the SHIPPED DEFAULT (ollama_num_ctx=65536), which the capacity
    arithmetic accepts -- this is a valid config crashing, not an invalid one being rejected.
    """
    r = _run_in_subprocess("import ormah.engine.memory_engine; print('IMPORT OK')")
    assert r.returncode == 0, (
        "importing memory_engine FIRST under an ollama config crashed -- the boot validator "
        f"reaches back into it:\n{r.stderr[-2500:]}"
    )
    assert "IMPORT OK" in r.stdout


def test_computing_the_prompt_overhead_never_loads_the_engine_or_config():
    """The invariant behind the fix, asserted directly so it cannot silently rot.

    `prompt_overhead_chars()` is CALLED by the boot validator, i.e. during `import ormah.config`.
    Whatever it touches -- at module level or lazily inside the function, which is how the cycle
    was introduced -- must not reach `engine.memory_engine` (which imports `ormah.config`) nor
    `ormah.config` itself. So the check is on the state AFTER the call, not merely after the
    import: a lazy import is not a fix, it only relocates the cycle to call time.
    """
    r = _run_in_subprocess(
        "import sys; import ormah.ingest_capacity as c; c.prompt_overhead_chars(); "
        "print('CONFIG_LOADED' if 'ormah.config' in sys.modules else 'CLEAN-config'); "
        "print('ENGINE_LOADED' if 'ormah.engine.memory_engine' in sys.modules else 'CLEAN-engine')"
    )
    assert r.returncode == 0, r.stderr[-2500:]
    assert "ENGINE_LOADED" not in r.stdout, (
        "computing the overhead loads engine.memory_engine, which imports ormah.config -- "
        "that is the cycle, restored"
    )
    assert "CONFIG_LOADED" not in r.stdout, (
        "computing the overhead loads ormah.config -- that is the cycle, restored"
    )

"""Shared LLM facade for background tasks.

All callers import ``llm_generate`` from here — the function signature is
unchanged.  Internally we delegate to the adapter returned by
``get_adapter(settings)``.
"""

from __future__ import annotations

import json
import logging
import re
import threading

from ormah.background import llm_cancel
from ormah.background.llm import LLMAdapter, get_adapter
from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_json(raw: str) -> str:
    """Extract a JSON document from an LLM response.

    Thinking-capable models (e.g. qwen3.5) wrap their output in markdown
    ``` fences or surround it with prose even when asked for JSON mode, which
    makes a naive ``json.loads(raw)`` fail. This recovers the embedded JSON so
    callers parse it instead of discarding a valid response.
    """
    stripped = raw.strip()

    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass

    for match in _FENCE_RE.finditer(raw):
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    decoder = json.JSONDecoder()
    for start, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(raw[start:])
            return raw[start : start + end]
        except json.JSONDecodeError:
            continue

    return stripped

_cached_adapter: LLMAdapter | None = None
_adapter_initialised: bool = False

_cached_ingest_adapter: LLMAdapter | None = None
_ingest_adapter_initialised: bool = False

# HIGH-1 (council-pr, Codex): serialise lazy init + cache access. Without this, two drain
# threads on distinct acceptance roots (the Beta has ~/.claude/projects + ~/.codex/sessions)
# can both enter a factory on first use, both call get_adapter(...), and the second assignment
# overwrites the cache — the first thread's now-uncached adapter is simply leaked (never
# reused, GC'd once its call returns). ADR-0004 slice 2 made cancellation a global epoch
# (see llm_cancel.py) that every adapter's generate() reads at call time, cached or not, so a
# displaced adapter's in-flight call IS still reached by a shutdown cancel — that is no longer
# what this lock buys. What it still buys: holding the lock across check+construct+assign
# guarantees at most one adapter is ever constructed per cache, so a duplicate is never built
# (and its process/connection never spun up) just to be thrown away.
_adapter_lock = threading.Lock()


def reset_adapter() -> None:
    """Clear the cached adapters (useful for test isolation)."""
    global _cached_adapter, _adapter_initialised, _cached_ingest_adapter, _ingest_adapter_initialised
    with _adapter_lock:
        _cached_adapter = None
        _adapter_initialised = False
        _cached_ingest_adapter = None
        _ingest_adapter_initialised = False


def _get_or_create_adapter(settings) -> LLMAdapter | None:
    global _cached_adapter, _adapter_initialised
    with _adapter_lock:
        if not _adapter_initialised:
            _cached_adapter = get_adapter(settings)
            _adapter_initialised = True
        return _cached_adapter


def _resolve_ingest_provider(settings) -> str | None:
    return getattr(settings, "ingest_llm_provider", None) or getattr(settings, "llm_provider", None)


def _resolve_ingest_model(settings) -> str | None:
    return getattr(settings, "ingest_llm_model", None) or getattr(settings, "llm_model", None)


def _get_or_create_ingest_adapter(settings) -> LLMAdapter | None:
    global _cached_ingest_adapter, _ingest_adapter_initialised
    with _adapter_lock:
        if not _ingest_adapter_initialised:
            _cached_ingest_adapter = get_adapter(
                settings,
                provider=_resolve_ingest_provider(settings),
                model=_resolve_ingest_model(settings),
                # ONLY the ingest adapter gets the large Ollama input window: a full Batch is
                # ~60000 chars and the server default would truncate it silently. The maintenance
                # factory above deliberately leaves this None (small pairs, no KV-cache cost).
                num_ctx=getattr(settings, "ollama_num_ctx", None),
            )
            _ingest_adapter_initialised = True
        return _cached_ingest_adapter


def _guarded_generate(adapter, prompt, **kwargs) -> str | None:
    """Provider-independent cancellation seam. Admission at entry, in-flight accounting around
    the call, and rejection of any output produced in a cancelled era.

    Only the SUBPROCESS kill is claude-specific (the adapter does that from its own thread).
    Ollama/LiteLLM are not interruptible mid-flight — they still block until their HTTP timeout,
    unchanged — but this seam stops them RETURNING output that a shutdown already invalidated,
    and stops a NEW call starting once shutdown began."""
    gen, cancelled = llm_cancel.snapshot()
    if cancelled:
        raise LlmCancelledError("llm call aborted: shutdown in progress")
    llm_cancel.note_call_started()
    try:
        result = adapter.generate(prompt, **kwargs)
        if llm_cancel.epoch_changed(gen):
            # An in-flight call whose era was superseded while it ran: reject its output for
            # every provider (the claude adapter also rejects internally; this covers the rest).
            raise LlmCancelledError("llm call cancelled: shutdown in progress")
        return result
    finally:
        llm_cancel.note_call_finished()


def ingest_llm_generate(settings, prompt: str, json_mode: bool = True, **kwargs) -> str | None:
    """Ingest path: PROPAGATE LlmCancelledError. The engine maps it to a provider-wide transient
    so a cancelled extraction never advances the cursor nor burns the per-slice failure cap — do
    NOT swallow it here (that safety is the whole point of the slice)."""
    adapter = _get_or_create_ingest_adapter(settings)
    if adapter is None:
        return None
    return _guarded_generate(adapter, prompt, json_mode=json_mode, **kwargs)


def ingest_provider_configured(settings) -> bool:
    """True when a server-side extraction adapter is available (ingest provider != none).

    Lets callers tell "no provider" (a global, temporary state) apart from "the call failed"
    (a timeout/error while a provider IS configured) — both of which surface as a None from
    ``ingest_llm_generate``."""
    return _get_or_create_ingest_adapter(settings) is not None


def llm_generate(
    settings,
    prompt: str,
    json_mode: bool = True,
    *,
    response_format: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_hint_seconds: float | None = None,
) -> str | None:
    """Maintenance path: swallow cancel/timeout to None (unchanged contract)."""
    adapter = _get_or_create_adapter(settings)
    if adapter is None:
        return None
    try:
        return _guarded_generate(
            adapter, prompt, json_mode=json_mode, response_format=response_format,
            temperature=temperature, max_tokens=max_tokens,
            timeout_hint_seconds=timeout_hint_seconds,
        )
    except (LlmCancelledError, LlmTimeoutError):
        return None


def cancel_active_llm_calls(*, final: bool = True) -> int:
    """Cancel every in-flight LLM call. Returns how many calls the cancel invalidated.

    ADR-0004 slice 2 redesign: this is now a single epoch bump — no adapter-cache sweep, no
    lock held across process I/O. An adapter built after this returns still reads the
    cancelled epoch at generate() entry, so there is no cache-boundary window (R6) and no
    two-phase transition to interleave (R7).

    ``final=True`` (the default) is a shutdown cancel that resume() must not undo. The
    watcher's startup rollback passes ``final=False``, because that process keeps serving.
    """
    return llm_cancel.begin_cancel(final=final)


def resume_llm_adapters() -> None:
    """Re-admit new LLM calls after a RECOVERABLE cancel (the watcher's startup rollback).

    A no-op after a final cancel. Calls already in flight are NOT un-cancelled — the epoch
    bump keeps them aborting (R4).
    """
    llm_cancel.resume()


def begin_llm_lifespan() -> None:
    """Start a clean cancellation era. Called once per lifespan startup.

    The adapter caches here are module-level and outlive a lifespan, so a final cancel from
    the previous one must be cleared or every call in this process stays dead until restart.
    """
    llm_cancel.begin_lifespan()

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
# overwrites the cache. The first thread keeps running generate() on its now-uncached adapter,
# which cancel_active_llm_calls() (it only visits the cached globals) can never reach — so that
# displaced in-flight call is never cancelled and shutdown waits its full provider timeout.
# Holding the lock across check+construct+assign guarantees at most one adapter per cache.
_adapter_lock = threading.Lock()

# HIGH (council-pr R6, Codex): shutdown gate for the CACHE BOUNDARY. The sweep used to read the
# cache globals without ``_adapter_lock``, but a factory HOLDS that lock across
# ``get_adapter(settings)`` — and during that window the global is still None. A shutdown landing
# there saw "no adapters", returned 0, the watcher's fence concluded there was nothing to cancel,
# and the factory then published an UNCANCELLED adapter that went on to spawn `claude -p`.
#
# Taking the lock in the sweep + this gate partition every adapter into exactly two cases:
#   * published BEFORE the sweep wins the lock -> it is in the snapshot -> the sweep cancels it;
#   * built AFTER the gate went up             -> the factory sees the gate and cancels it at birth.
# Nothing can be published "during" the sweep: both require ``_adapter_lock``. The sweep therefore
# waits for an in-progress factory, which is bounded — ``get_adapter`` is pure object construction
# (at worst a ``shutil.which``), never I/O.
_shutdown_started: bool = False


def _cancel_newborn_if_shutting_down(adapter) -> None:
    """Cancel a freshly built adapter when shutdown already started. Call with the lock HELD.

    Bounded: ``get_adapter`` returns a BRAND NEW instance whose tracked-process map is empty, so
    ``cancel_active()`` here only flips the adapter's cancel flag and iterates nothing — it never
    reaches the ``p.wait(timeout=5)`` kill fence. That is what makes it safe to run while holding
    ``_adapter_lock``. Lock order is ``_adapter_lock -> _cancel_lock -> _active_lock``; the adapter
    never calls back into this module from inside its own locks, so the order is strictly one-way.
    """
    cancel = getattr(adapter, "cancel_active", None)
    if not _shutdown_started or not callable(cancel):
        return
    try:
        cancel()
    except Exception as e:
        logger.warning("Cancelling a newly built adapter during shutdown failed: %s", e)


def _snapshot_adapters() -> list[tuple[str, object]]:
    """Names + instances of the cached adapters. Call with ``_adapter_lock`` HELD (R6)."""
    return [(name, globals().get(name)) for name in ("_cached_adapter", "_cached_ingest_adapter")]


def reset_adapter() -> None:
    """Clear the cached adapters (useful for test isolation)."""
    global _cached_adapter, _adapter_initialised, _cached_ingest_adapter, _ingest_adapter_initialised
    global _shutdown_started
    with _adapter_lock:
        _cached_adapter = None
        _adapter_initialised = False
        _cached_ingest_adapter = None
        _ingest_adapter_initialised = False
        # Also lower the gate: a leaked one would make every later adapter be born cancelled.
        _shutdown_started = False


def _get_or_create_adapter(settings) -> LLMAdapter | None:
    global _cached_adapter, _adapter_initialised
    with _adapter_lock:
        if not _adapter_initialised:
            _cached_adapter = get_adapter(settings)
            _adapter_initialised = True
            # R6: born cancelled if shutdown started while we were building it.
            _cancel_newborn_if_shutting_down(_cached_adapter)
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
            )
            _ingest_adapter_initialised = True
            # R6: born cancelled if shutdown started while we were building it.
            _cancel_newborn_if_shutting_down(_cached_ingest_adapter)
        return _cached_ingest_adapter


def ingest_llm_generate(settings, prompt: str, json_mode: bool = True, **kwargs) -> str | None:
    """Generate for server-side extraction, using ingest_llm_provider/model (not the
    maintenance-path llm_provider/llm_model)."""
    adapter = _get_or_create_ingest_adapter(settings)
    if adapter is None:
        return None
    return adapter.generate(prompt, json_mode=json_mode, **kwargs)


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
    """Call configured LLM. Returns raw response text, or None on failure."""
    adapter = _get_or_create_adapter(settings)
    if adapter is None:
        return None
    try:
        return adapter.generate(
            prompt,
            json_mode=json_mode,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_hint_seconds=timeout_hint_seconds,
        )
    except (LlmCancelledError, LlmTimeoutError):
        return None


def cancel_active_llm_calls() -> int:
    """Best-effort cancellation of in-flight LLM calls at shutdown.

    Adapters opt in by defining cancel_active(); adapters without it (upstream, non-claude_cli
    providers) are skipped so the drain there stays bounded only by their own HTTP timeouts.

    ITEM 2 (council-pr R4, Codex): each adapter is isolated. A raising maintenance adapter used
    to kill this whole function, so the INGEST adapter was never cancelled — and because the R3
    HIGH-3 fix suppresses this exception in _stop_and_drain, every turn of the join fence
    restarted on the same raising adapter and the fence spun without ever cancelling what
    mattered, waiting out the provider timeout.

    R6 (Codex): the gate goes up and the cache is snapshotted in ONE critical section, closing the
    cache-boundary window where a factory held ``_adapter_lock`` across ``get_adapter`` and the
    global was still None. The ``cancel_active()`` calls themselves run OUTSIDE the lock on
    purpose — they run the kill fence (``p.wait(timeout=5)`` per child), and holding
    ``_adapter_lock`` through that would stall every thread that merely wants an adapter."""
    global _shutdown_started
    with _adapter_lock:
        _shutdown_started = True
        adapters = _snapshot_adapters()  # the ingest cache exists only on the Beta
    total = 0
    for name, adapter in adapters:
        cancel = getattr(adapter, "cancel_active", None)
        if callable(cancel):
            try:
                total += cancel()
            except Exception as e:
                logger.warning("Cancelling in-flight LLM calls on %s failed: %s", name, e)
    return total


def resume_llm_adapters() -> None:
    """Re-arm cancelled adapters. Called at lifespan startup and after a recoverable startup
    rollback — the module-level caches outlive a single lifespan (council R7).

    ITEM 2: same per-adapter isolation as ``cancel_active_llm_calls`` — if the first resume()
    raised, the second never ran and that adapter stayed permanently cancelled (ingest OR
    maintenance dead until restart).

    R6: this also LOWERS the shutdown gate. Without that, every adapter built after a recoverable
    rollback would be born cancelled and ingest + maintenance would stay dead until restart —
    exactly the failure mode HIGH-A (council R1) exists to prevent."""
    global _shutdown_started
    with _adapter_lock:
        _shutdown_started = False
        adapters = _snapshot_adapters()
    for name, adapter in adapters:
        resume = getattr(adapter, "resume", None)
        if callable(resume):
            try:
                resume()
            except Exception as e:
                logger.warning("Re-arming LLM adapter %s failed: %s", name, e)

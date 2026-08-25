"""Shared LLM facade for background tasks.

All callers import ``llm_generate`` from here — the function signature is
unchanged.  Internally we delegate to the adapter returned by
``get_adapter(settings)``.
"""

from __future__ import annotations

import json
import logging
import re

from ormah.background.llm import LLMAdapter, get_adapter

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

_cached_consolidation_adapter: LLMAdapter | None = None
_consolidation_adapter_initialised: bool = False

# Chars per token assumed when converting a character budget into an input window. English prose
# runs ~4 chars/token; 2.0 is a deliberate 2x safety margin, so a denser payload (hex digests,
# base64, CJK) still fits the window we ask for. Erring large costs KV cache; erring small costs
# a silently truncated prompt, which is the failure #192 exists to remove.
_CHARS_PER_TOKEN = 2.0


def reset_adapter() -> None:
    """Clear the cached adapters (useful for test isolation)."""
    global _cached_adapter, _adapter_initialised
    global _cached_consolidation_adapter, _consolidation_adapter_initialised
    _cached_adapter = None
    _adapter_initialised = False
    _cached_consolidation_adapter = None
    _consolidation_adapter_initialised = False


def _get_or_create_adapter(settings) -> LLMAdapter | None:
    global _cached_adapter, _adapter_initialised
    if not _adapter_initialised:
        _cached_adapter = get_adapter(settings)
        _adapter_initialised = True
    return _cached_adapter


def _consolidation_num_ctx(settings) -> int:
    """The input window the consolidation route needs, derived from the budget it packs against.

    Both sides of the call use the same number: the splitter fills at most
    ``consolidation_max_prompt_chars``, and this converts that to tokens, leaving room for the
    model's own output budget.
    """
    return int(settings.consolidation_max_prompt_chars / _CHARS_PER_TOKEN) + (
        settings.llm_num_predict
    )


def _get_or_create_consolidation_adapter(settings) -> LLMAdapter | None:
    global _cached_consolidation_adapter, _consolidation_adapter_initialised
    if not _consolidation_adapter_initialised:
        # Consolidation is the ONE maintenance route whose prompt carries full source content
        # (#192), and its output DISPLACES that content: every source is demoted to archival the
        # moment the summary is written. Inheriting the operator's server default here would let
        # Ollama truncate the prompt silently -- exactly the bug #192 fixes, one level down. The
        # SHARED adapter above deliberately passes no num_ctx: auto_linker, conflict_detector and
        # duplicate_merger judge small pairs and must not pay this KV cache.
        _cached_consolidation_adapter = get_adapter(
            settings, num_ctx=_consolidation_num_ctx(settings)
        )
        _consolidation_adapter_initialised = True
    return _cached_consolidation_adapter


def llm_generate(
    settings,
    prompt: str,
    json_mode: bool = True,
    *,
    response_format: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    route: str = "maintenance",
) -> str | None:
    """Call configured LLM. Returns raw response text, or None on failure.

    ``route="consolidation"`` selects the adapter that pins its own input window (#192); every
    other route shares the maintenance adapter, which leaves the window to the operator.
    """
    adapter = (
        _get_or_create_consolidation_adapter(settings)
        if route == "consolidation"
        else _get_or_create_adapter(settings)
    )
    if adapter is None:
        return None
    return adapter.generate(
        prompt,
        json_mode=json_mode,
        response_format=response_format,
        temperature=temperature,
        max_tokens=max_tokens,
    )

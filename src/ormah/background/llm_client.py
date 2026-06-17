"""Shared LLM facade for background tasks.

All callers import ``llm_generate`` from here — the function signature is
unchanged.  Internally we delegate to the adapter returned by
``get_adapter(settings)``.
"""

from __future__ import annotations

import logging
import re

from ormah.background.llm import LLMAdapter, get_adapter

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def extract_json(raw: str) -> str:
    """Extract a JSON document from an LLM response.

    Thinking-capable models (e.g. qwen3.5) wrap their output in markdown
    ``` fences or surround it with prose even when asked for JSON mode, which
    makes a naive ``json.loads(raw)`` fail. This recovers the embedded JSON so
    callers parse it instead of discarding a valid response.
    """
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        return stripped

    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()

    # Last resort: first opening bracket to last matching closing bracket.
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = raw.find(start_char)
        end = raw.rfind(end_char)
        if start != -1 and end > start:
            return raw[start : end + 1]

    return stripped

_cached_adapter: LLMAdapter | None = None
_adapter_initialised: bool = False


def reset_adapter() -> None:
    """Clear the cached adapter (useful for test isolation)."""
    global _cached_adapter, _adapter_initialised
    _cached_adapter = None
    _adapter_initialised = False


def _get_or_create_adapter(settings) -> LLMAdapter | None:
    global _cached_adapter, _adapter_initialised
    if not _adapter_initialised:
        _cached_adapter = get_adapter(settings)
        _adapter_initialised = True
    return _cached_adapter


def llm_generate(settings, prompt: str, json_mode: bool = True) -> str | None:
    """Call configured LLM. Returns raw response text, or None on failure."""
    adapter = _get_or_create_adapter(settings)
    if adapter is None:
        return None
    return adapter.generate(prompt, json_mode=json_mode)

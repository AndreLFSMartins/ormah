"""Shared capacity arithmetic for ingest payloads.

Deliberately dependency-free: `config.py` and `engine/memory_engine.py` both import it, and
importing either from the other would cycle. The boot validator and the runtime preflight MUST
use the same numbers — a boot check computed differently from the runtime check guarantees
nothing.
"""

from __future__ import annotations

# Upper bound for token-dense content (base64, minified blobs, hashes, non-Latin script, heavy
# PT-BR diacritics), NOT the ~4 chars/token average used for documentation. Chosen below the
# 60000/28672 ≈ 2.09 overflow threshold the council computed.
_DENSE_CHARS_PER_TOKEN = 2.0


def prompt_overhead_chars() -> int:
    """Chars the extraction template and schema add around the conversation.

    Computed from the template itself rather than hardcoded, so it cannot go stale when the
    prompt is edited.
    """
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT  # local: avoids an import cycle

    return len(_INGEST_LLM_PROMPT.format(conversation=""))


def estimated_tokens(chars: int) -> int:
    return int(chars / _DENSE_CHARS_PER_TOKEN)


def usable_input_tokens(settings) -> int:
    return settings.ollama_num_ctx - settings.llm_num_predict

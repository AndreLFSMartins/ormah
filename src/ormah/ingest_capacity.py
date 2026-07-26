"""Shared capacity arithmetic for ingest payloads.

Imported by BOTH `config.py` (boot validator) and `engine/memory_engine.py` (runtime preflight),
which must agree: a boot check computed differently from the runtime check guarantees nothing.

Its only ormah dependency is the LEAF module `ormah.ingest_prompt`, and that is load-bearing.
`config.py` builds a module-level `Settings()`, so the boot validator runs during
`import ormah.config`; an earlier version reached the prompt through `engine/memory_engine.py`,
which imports `ormah.config`, and the result was a real circular import that crashed
`import ormah.engine.memory_engine` for every ollama operator. A lazy import does not avoid a
cycle — it only moves it to call time, and here call time IS import time. Never import anything
from this module that transitively reaches `ormah.config`.
"""

from __future__ import annotations

from ormah.ingest_prompt import _INGEST_LLM_PROMPT

# Upper bound for token-dense content (base64, minified blobs, hashes, non-Latin script, heavy
# PT-BR diacritics), NOT the ~4 chars/token average used for documentation. Chosen below the
# 60000/28672 ≈ 2.09 overflow threshold the council computed.
_DENSE_CHARS_PER_TOKEN = 2.0


def prompt_overhead_chars() -> int:
    """Chars the extraction template and schema add around the conversation.

    Computed from the template itself rather than hardcoded, so it cannot go stale when the
    prompt is edited.
    """
    return len(_INGEST_LLM_PROMPT.format(conversation=""))


def estimated_tokens(chars: int) -> int:
    return int(chars / _DENSE_CHARS_PER_TOKEN)


def usable_input_tokens(settings) -> int:
    return settings.ollama_num_ctx - settings.llm_num_predict

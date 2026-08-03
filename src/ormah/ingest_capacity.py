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

# Chars per token assumed by the capacity estimate. This is an empirical heuristic, NOT an upper
# bound over arbitrary text: measured against gemma3:4b via Ollama's own prompt_eval_count, hex
# digests and emoji run at 1.0 tok/char and base64 at 0.625 — all denser than the 0.5 assumed here.
#
# It holds for what actually reaches this estimate. The payload is the CLEANED conversation:
# parse_transcript keeps only user/assistant text blocks and drops tool_use, tool_result and
# thinking, so file dumps, image data and attachments never arrive here. Measured over 12 real
# transcripts, cleaned density was 0.251–0.323 tok/char (3.1–4.0 chars/token, median 0.290) — a
# 1.8x margin below the 0.579 tok/char at which the shipped window actually overflows. Pasting a
# large digest or base64 blob into the chat as prose is the way past that margin, and it would
# have to dominate ~41% of a full payload (hex) or ~86% (base64) to overflow.
#
# The margin cannot erode silently: config.py's boot validator refuses any configuration whose
# worst payload divided by this constant exceeds the usable window — algebraically the condition
# (ingest_max_content_chars + prompt_overhead) / usable_input_tokens > this constant. With the
# shipped defaults that ratio is 1.727. (The "60000/28672 ≈ 2.09" threshold this comment used to
# cite was computed against defaults that no longer hold; it is not the current margin.)
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

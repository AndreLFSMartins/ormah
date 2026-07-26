"""LLM adapter package — pluggable backends for background jobs."""

from __future__ import annotations

from ormah.background.llm.base import LLMAdapter
from ormah.background.llm.normalize import normalize_conflict_type, normalize_link_type

__all__ = [
    "LLMAdapter",
    "get_adapter",
    "normalize_conflict_type",
    "normalize_link_type",
]


def get_adapter(settings, provider: str | None = None, model: str | None = None,
                num_ctx: int | None = None) -> LLMAdapter | None:
    """Build an adapter from the application settings.

    Returns ``None`` when the resolved provider is ``"none"``.

    ``num_ctx`` is threaded rather than read off ``settings`` on purpose (council R3, Codex): this
    factory builds BOTH the maintenance adapter and the ingest adapter, and wiring the large ingest
    window unconditionally would give every maintenance pair-judging call a 65536-token KV cache --
    a real memory cost, and a plausible OOM on a local machine, even for users whose ingest runs on
    claude_cli. Only the ingest factory in ``llm_client.py`` opts in.
    """
    provider = provider or settings.llm_provider
    timeout = getattr(settings, "llm_timeout_seconds", 60)

    if provider == "ollama":
        from ormah.background.llm.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=model or settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=timeout,
            num_predict=getattr(settings, "llm_num_predict", 4096),
            # None -> the adapter OMITS num_ctx entirely, leaving the operator's server/Modelfile
            # window in charge. There is deliberately no adapter-side default: maintenance judges
            # small pairs, and a number invented here would silently NARROW every one of those
            # calls (pair_batch renders K pairs into one prompt, and parse_batch_verdicts accepts
            # a PARTIAL verdict list, so truncation under-judges without erroring).
            num_ctx=num_ctx,
        )

    if provider == "litellm":
        from ormah.background.llm.litellm_adapter import LiteLLMAdapter

        return LiteLLMAdapter(model=model or settings.llm_model, timeout=timeout)

    if provider == "none":
        return None

    if provider == "claude_cli":
        from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter

        return ClaudeCliAdapter(
            model=model or settings.llm_model,
            timeout=settings.claude_cli_timeout_seconds,
            bin_path=settings.claude_cli_bin,
            max_concurrency=settings.claude_cli_max_concurrency,
        )

    raise NotImplementedError(f"LLM provider {provider!r} not implemented")

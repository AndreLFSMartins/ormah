"""Ollama LLM adapter — HTTP calls to a local Ollama instance."""

from __future__ import annotations

import logging

from ormah.background.llm.base import LLMAdapter

logger = logging.getLogger(__name__)


class OllamaAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: int = 60,
        num_predict: int = 4096,
        num_ctx: int | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.num_predict = num_predict
        # INPUT window. num_predict bounds output only; leaving num_ctx unset inherits the
        # server's default, which is neither controlled nor versioned by us. A default below the
        # payload truncates the prompt SILENTLY -- recall dies with no error, which is the exact
        # failure class ADR-0001/0003/0004 exist to eliminate.
        self.num_ctx = num_ctx or 8192   # ingest overrides via settings.ollama_num_ctx

    def generate(
        self,
        prompt: str,
        json_mode: bool = True,
        *,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_hint_seconds: float | None = None,
    ) -> str | None:
        import httpx

        options: dict = {
            "num_predict": max_tokens or self.num_predict,
            "num_ctx": self.num_ctx,
        }
        if temperature is not None:
            options["temperature"] = temperature

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Disable thinking: reasoning tokens consume the num_predict budget
            # and on large transcripts starve the JSON, yielding empty/truncated
            # extractions. Non-thinking models ignore this flag.
            "think": False,
            "options": options,
        }
        if response_format and response_format.get("type") == "json_schema":
            payload["format"] = response_format.get("json_schema", {}).get("schema", "json")
        elif json_mode:
            payload["format"] = "json"

        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=timeout_hint_seconds or self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response")
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning("Ollama unavailable: %s", e)
            return None
        except Exception as e:
            logger.warning("Ollama call failed: %s", e)
            return None

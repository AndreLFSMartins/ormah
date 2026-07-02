"""Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid API)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading

from ormah.background.llm.base import LLMAdapter

logger = logging.getLogger(__name__)

# Hooks-off mechanism confirmed by Task 01 (SPIKE-FINDINGS.md). Keeps the child from firing
# ormah hooks -> no extraction recursion.
_HOOKS_OFF_ARGS = ["--settings", '{"hooks":{}}']

# Trust boundary: the transcript is UNTRUSTED input (prompt-injection vector). Deny ALL agent
# tools so a malicious transcript can only produce text, never act. Confirmed by Task 01.
_TOOL_DENY_ARGS = ["--allowed-tools", ""]

# Bound concurrent `claude -p` across all adapter instances/threads. One shared semaphore per max.
_SEMAPHORES: dict[int, threading.Semaphore] = {}
_SEM_LOCK = threading.Lock()


def _semaphore(max_concurrency: int) -> threading.Semaphore:
    with _SEM_LOCK:
        sem = _SEMAPHORES.get(max_concurrency)
        if sem is None:
            sem = threading.Semaphore(max_concurrency)
            _SEMAPHORES[max_concurrency] = sem
        return sem


class ClaudeCliAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        timeout: int = 120,
        bin_path: str | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.bin_path = bin_path or shutil.which("claude") or "claude"
        self.max_concurrency = max(1, max_concurrency)

    def generate(
        self,
        prompt: str,
        json_mode: bool = True,
        *,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        # Force subscription auth: strip the API key so the child never bills the paid API.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # Prompt on stdin (never argv) — avoids leaking transcript text to the process list and
        # ARG_MAX failures on large transcripts.
        argv = [
            self.bin_path, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--no-session-persistence",
            *_HOOKS_OFF_ARGS,
            *_TOOL_DENY_ARGS,
        ]
        sem = _semaphore(self.max_concurrency)
        with sem:
            try:
                proc = subprocess.run(
                    argv, input=prompt, capture_output=True, text=True,
                    timeout=self.timeout, cwd=tempfile.gettempdir(), env=env,
                )
            except subprocess.TimeoutExpired:
                logger.warning("claude -p timed out after %ss", self.timeout)
                return None
            except Exception as e:  # binary missing, OSError, etc.
                logger.warning("claude -p failed to run: %s", e)
                return None
        if proc.returncode != 0:
            logger.warning("claude -p exited %s: %s", proc.returncode, proc.stderr[:300])
            return None
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            logger.warning("claude -p returned a non-JSON envelope")
            return None
        if not isinstance(envelope, dict):
            return None
        if envelope.get("is_error"):
            logger.warning("claude -p returned is_error envelope: %s", str(envelope.get("subtype"))[:100])
            return None
        result = envelope.get("result")
        return result if isinstance(result, str) else None

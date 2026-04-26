"""Logging configuration — text or JSON format."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_SECRET_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "AZURE_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b("
    + "|".join(re.escape(name) for name in _SECRET_ENV_VARS)
    + r")=([^\s,;]+)"
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _redact_secrets(text: str) -> str:
    """Redact known API-key values from log text."""
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", text)

    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)

    for name in _SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 4:
            redacted = redacted.replace(value, "[REDACTED]")

    return redacted


def _redact_obj(value):
    """Redact strings inside JSON log extras without changing non-secret types."""
    if isinstance(value, str):
        return _redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_obj(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_obj(item) for item in value)
    return value


class _RedactingFormatter(logging.Formatter):
    """Text formatter that redacts API-key values from the final rendered line."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact_secrets(super().format(record))


class _JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line.

    Fields: ``ts``, ``level``, ``logger``, ``msg``, plus any ``extra``
    keys attached to the LogRecord.
    """

    # Keys that are standard LogRecord attributes (skip when dumping extras)
    _BUILTIN = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": _redact_secrets(record.getMessage()),
        }
        if record.exc_info and record.exc_info[1] is not None:
            obj["exception"] = _redact_secrets(self.formatException(record.exc_info))

        # Attach extra keys (e.g. job_id, duration_ms)
        for key, val in record.__dict__.items():
            if key not in self._BUILTIN and key not in obj:
                obj[key] = _redact_obj(val)

        return json.dumps(obj, default=str)


def setup_logging(
    log_format: str = "text",
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Configure the root logger.

    Args:
        log_format: ``"text"`` for human-readable lines, ``"json"`` for
            machine-parseable JSON (one object per line).
        level: logging level (default ``INFO``).
        log_file: optional path to a rotating log file. When provided, logs are
            written to both stderr and the file (5 MB max, 3 backups kept).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers (e.g. from basicConfig)
    for h in root.handlers[:]:
        root.removeHandler(h)

    if log_format == "json":
        formatter = _JSONFormatter()
    else:
        formatter = _RedactingFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        root.addHandler(rotating)

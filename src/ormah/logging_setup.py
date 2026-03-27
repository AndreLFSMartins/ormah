"""Logging configuration — text or JSON format."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path


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
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            obj["exception"] = self.formatException(record.exc_info)

        # Attach extra keys (e.g. job_id, duration_ms)
        for key, val in record.__dict__.items():
            if key not in self._BUILTIN and key not in obj:
                obj[key] = val

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
        formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

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

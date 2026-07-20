"""Durable, append-only quarantine ledger for memories dropped by the relevance gate.

JSONL, not a DB table: append-only audit log, no migration needed, inspectable with
`jq`. ADR-0002 promises the drop is "recoverable/measurable" — this ledger is the
recovery mechanism (full content + source + provider/model + prompt version) and lets
the canary measure the false-drop rate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator


def quarantine_path(settings) -> Path:
    """Path to the quarantine JSONL file, beside the store DB (settings.db_path)."""
    return settings.db_path.parent / "relevance_gate_quarantine.jsonl"


def prompt_version() -> str:
    """First 12 hex chars of sha256 of the ingest LLM rules prompt text."""
    from ormah.engine.memory_engine import _INGEST_LLM_RULES

    return hashlib.sha256(_INGEST_LLM_RULES.encode()).hexdigest()[:12]


def record_dropped(
    settings,
    *,
    content: str,
    title: str,
    node_type: str,
    space: str | None,
    provider: str,
    model: str,
    dropped_at: str,
) -> None:
    """Append one dropped-candidate record to the quarantine ledger."""
    path = quarantine_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "dropped_at": dropped_at,
        "title": title,
        "content": content,
        "node_type": node_type,
        "space": space,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version(),
        "label": "material",
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def iter_dropped(settings) -> Iterator[dict]:
    """Yield each quarantined record; yields nothing if the file is absent."""
    path = quarantine_path(settings)
    if not path.exists():
        return
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

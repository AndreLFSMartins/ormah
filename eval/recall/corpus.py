"""Load and validate eval corpus files (JSONL format)."""

from __future__ import annotations

import json
from pathlib import Path


class CorpusError(Exception):
    """Raised on corpus file errors."""


def load_corpus(path: Path) -> list[dict]:
    """Load a corpus JSONL file. Skips header lines. Returns list of cases.

    Raises CorpusError if the file does not exist.
    """
    if not path.exists():
        raise CorpusError(f"Corpus file not found: {path}")

    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("_header"):
            continue
        validate_case(obj)
        cases.append(obj)
    return cases


def validate_case(case: dict) -> None:
    """Validate a single corpus case. Raises CorpusError on structural issues."""
    case_id = case.get("id", "<unknown>")
    seen_ids: set[str] = set()
    for i, mem in enumerate(case.get("memories", [])):
        node_id = mem.get("node_id")
        if not node_id:
            raise CorpusError(
                f"Case '{case_id}' memory[{i}] missing required 'node_id' field"
            )
        if node_id in seen_ids:
            raise CorpusError(
                f"Case '{case_id}' has duplicate node_id: '{node_id}'"
            )
        seen_ids.add(node_id)

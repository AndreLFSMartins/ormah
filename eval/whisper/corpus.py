"""Load and validate whisper eval corpus files (JSONL format)."""
from __future__ import annotations

import json
from pathlib import Path

VALID_CATEGORIES = frozenset({
    "preference", "factual", "decision", "technical",
    "identity", "temporal", "noise", "continuation",
})


class CorpusError(Exception):
    """Raised on corpus file or validation errors."""


def load_corpus(path: Path) -> list[dict]:
    """Load a JSONL corpus file. Skips blank lines. Validates each case."""
    if not path.exists():
        raise CorpusError(f"Corpus file not found: {path}")
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
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
            raise CorpusError(f"Case '{case_id}' memory[{i}] missing 'node_id' field")
        if node_id in seen_ids:
            raise CorpusError(f"Case '{case_id}' has duplicate node_id: '{node_id}'")
        seen_ids.add(node_id)

    for i, prompt in enumerate(case.get("prompts", [])):
        category = prompt.get("category")
        if category and category not in VALID_CATEGORIES:
            raise CorpusError(
                f"Case '{case_id}' prompt[{i}] has invalid category '{category}'. "
                f"Valid: {sorted(VALID_CATEGORIES)}"
            )
        expected = prompt.get("expected", {})
        for label_field in ("should_inject", "should_not_inject"):
            for nid in expected.get(label_field, []):
                if nid not in seen_ids:
                    raise CorpusError(
                        f"Case '{case_id}' prompt[{i}] references unknown node_id "
                        f"'{nid}' in '{label_field}'"
                    )

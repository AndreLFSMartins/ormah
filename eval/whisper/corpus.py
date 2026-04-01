"""Load and validate whisper eval corpus files (JSONL format)."""
from __future__ import annotations

import json
from pathlib import Path

# Kept for report ordering and examples. The eval harness should not be
# restricted to these categories.
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

    # Validate optional in-case connections (enables spread activation / identity graph evals).
    from ormah.models.node import EdgeType
    for i, mem in enumerate(case.get("memories", [])):
        for j, conn in enumerate(mem.get("connections", []) or []):
            if not isinstance(conn, dict):
                raise CorpusError(f"Case '{case_id}' memory[{i}] connections[{j}] must be an object")
            target = conn.get("target")
            if not target:
                raise CorpusError(f"Case '{case_id}' memory[{i}] connections[{j}] missing 'target'")
            if target not in seen_ids:
                raise CorpusError(
                    f"Case '{case_id}' memory[{i}] connections[{j}] references unknown node_id '{target}'"
                )
            edge = conn.get("edge", "related_to")
            try:
                EdgeType(edge)
            except Exception:
                raise CorpusError(
                    f"Case '{case_id}' memory[{i}] connections[{j}] has invalid edge '{edge}'. "
                    f"Valid: {[e.value for e in EdgeType]}"
                )

    for i, prompt in enumerate(case.get("prompts", [])):
        category = prompt.get("category")
        if category is not None:
            if not isinstance(category, str) or not category.strip():
                raise CorpusError(f"Case '{case_id}' prompt[{i}] category must be a non-empty string")
        expected = prompt.get("expected", {})
        # Backwards compatible fields: should_inject / should_not_inject / should_suppress
        # Newer fields: must_include / may_include / must_not_include / must_be_silent
        id_fields = (
            "should_inject",
            "should_not_inject",
            "must_include",
            "may_include",
            "must_not_include",
        )
        for label_field in id_fields:
            for nid in expected.get(label_field, []):
                if nid not in seen_ids:
                    raise CorpusError(
                        f"Case '{case_id}' prompt[{i}] references unknown node_id "
                        f"'{nid}' in '{label_field}'"
                    )

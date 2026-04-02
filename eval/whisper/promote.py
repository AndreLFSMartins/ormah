"""Promote mined whisper candidates into eval-ready corpus cases."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PromotionSummary:
    candidates_read: int
    cases_emitted: int
    skipped_candidates: int
    duplicate_candidates: int
    output_path: Path
    manifest_path: Path


def load_mined_candidates(path: Path) -> list[dict[str, Any]]:
    """Load mined candidate JSONL records."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    candidates: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        candidates.append(json.loads(line))
    return candidates


def _candidate_review(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("review") or {}


def _candidate_category(candidate: dict[str, Any]) -> str:
    review = _candidate_review(candidate)
    if review.get("category"):
        return str(review["category"])
    categories = candidate.get("classification", {}).get("intent_categories") or []
    if categories:
        return str(categories[0])
    return "general"


def _candidate_should_inject(candidate: dict[str, Any]) -> list[str]:
    review = _candidate_review(candidate)
    if isinstance(review.get("should_inject"), list):
        return [str(x) for x in review["should_inject"]]
    preview = candidate.get("whisper_preview", {})
    return [str(x) for x in preview.get("injected_ids", [])]


def _candidate_should_not_inject(candidate: dict[str, Any]) -> list[str]:
    review = _candidate_review(candidate)
    if isinstance(review.get("should_not_inject"), list):
        return [str(x) for x in review["should_not_inject"]]
    return []


def _candidate_should_suppress(candidate: dict[str, Any]) -> bool:
    review = _candidate_review(candidate)
    return bool(review.get("should_suppress", False))


def _candidate_is_rejected(candidate: dict[str, Any]) -> bool:
    review = _candidate_review(candidate)
    return str(review.get("status", "")).lower() == "rejected"


def _memory_payload(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node["id"],
        "title": node.get("title"),
        "content": node.get("content", ""),
        "type": node.get("type", "fact"),
        "tier": node.get("tier", "working"),
        "space": node.get("space"),
        "tags": node.get("tags", []),
    }


def candidate_to_case(candidate: dict[str, Any], engine) -> dict[str, Any] | None:
    """Convert one mined candidate into a valid corpus case, or None if skipped."""
    if _candidate_is_rejected(candidate):
        return None

    should_inject = _candidate_should_inject(candidate)
    should_not_inject = _candidate_should_not_inject(candidate)
    should_suppress = _candidate_should_suppress(candidate)

    if not should_inject and not should_suppress:
        return None

    memory_ids = list(
        dict.fromkeys(
            should_inject
            + should_not_inject
            + [str(x) for x in candidate.get("whisper_preview", {}).get("injected_ids", [])]
        )
    )
    memories: list[dict[str, Any]] = []
    for node_id in memory_ids:
        node = engine.graph.get_node(node_id)
        if node is None:
            continue
        memories.append(_memory_payload(node))

    referenced_ids = {m["node_id"] for m in memories}
    filtered_should_inject = [node_id for node_id in should_inject if node_id in referenced_ids]
    filtered_should_not = [node_id for node_id in should_not_inject if node_id in referenced_ids]

    if not filtered_should_inject and not should_suppress:
        return None

    prompt = {
        "text": candidate.get("prompt", {}).get("text", ""),
        "category": _candidate_category(candidate),
        "expected": {
            "should_inject": filtered_should_inject,
            "should_not_inject": filtered_should_not,
            "should_suppress": should_suppress,
        },
    }
    recent_prompts = candidate.get("prompt", {}).get("recent_prompts") or []
    if recent_prompts:
        prompt["recent_prompts"] = recent_prompts

    case_id = f"promoted-{candidate.get('candidate_id', 'unknown')}"
    return {
        "id": case_id,
        "space": candidate.get("space"),
        "memories": memories,
        "prompts": [prompt],
        "provenance": {
            "candidate_id": candidate.get("candidate_id"),
            "transcript_path": candidate.get("source", {}).get("transcript_path"),
            "session_id": candidate.get("source", {}).get("session_id"),
            "prompt_index": candidate.get("source", {}).get("prompt_index"),
        },
    }


def promote_candidates(
    candidates_path: Path,
    output_path: Path,
    engine,
    *,
    replace_output: bool = False,
    limit: int | None = None,
) -> PromotionSummary:
    """Promote mined candidates into a corpus JSONL file."""
    candidates = load_mined_candidates(candidates_path)
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_suffix(".manifest.json")

    existing_cases: list[dict[str, Any]] = []
    existing_ids: set[str] = set()
    if output_path.exists() and not replace_output:
        for line in output_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            existing_cases.append(case)
            case_id = case.get("id")
            if case_id:
                existing_ids.add(case_id)

    emitted_cases: list[dict[str, Any]] = []
    duplicate_candidates = 0
    skipped_candidates = 0

    for candidate in candidates:
        if limit is not None and len(emitted_cases) >= limit:
            break
        case = candidate_to_case(candidate, engine)
        if case is None:
            skipped_candidates += 1
            continue
        if case["id"] in existing_ids:
            duplicate_candidates += 1
            continue
        emitted_cases.append(case)
        existing_ids.add(case["id"])

    all_cases = emitted_cases if replace_output else existing_cases + emitted_cases
    all_cases = sorted(all_cases, key=lambda case: case.get("id", ""))

    with open(output_path, "w") as f:
        for case in all_cases:
            f.write(json.dumps(case) + "\n")

    manifest = {
        "input_path": str(Path(candidates_path).expanduser()),
        "output_path": str(output_path),
        "replace_output": replace_output,
        "candidates_read": len(candidates),
        "cases_emitted": len(emitted_cases),
        "skipped_candidates": skipped_candidates,
        "duplicate_candidates": duplicate_candidates,
        "emitted_case_ids": [case["id"] for case in emitted_cases],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    return PromotionSummary(
        candidates_read=len(candidates),
        cases_emitted=len(emitted_cases),
        skipped_candidates=skipped_candidates,
        duplicate_candidates=duplicate_candidates,
        output_path=output_path,
        manifest_path=manifest_path,
    )

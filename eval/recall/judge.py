"""Labeling workflow: export unlabeled pairs for Claude Code, import scored labels."""

from __future__ import annotations

import json
from pathlib import Path

from eval.recall.corpus import load_corpus


def export_for_labeling(corpus_dir: Path, write: bool = False) -> list[dict]:
    """Find all unlabeled (prompt, memory) pairs across all corpus files.

    A case is unlabeled if ALL its prompts have empty should_inject AND
    empty should_not_inject. Returns a list of pending label entries.

    If write=True, also writes corpus_dir/pending_labels.jsonl.
    """
    pending: list[dict] = []
    corpus_files = list((corpus_dir / "golden").glob("*.jsonl"))
    if (corpus_dir / "synthetic").exists():
        corpus_files += list((corpus_dir / "synthetic").glob("*.jsonl"))

    for corpus_file in corpus_files:
        try:
            cases = load_corpus(corpus_file)
        except Exception:
            continue

        for case in cases:
            for prompt_idx, prompt_obj in enumerate(case.get("prompts", [])):
                exp = prompt_obj.get("expected", {})
                if exp.get("should_inject") or exp.get("should_not_inject"):
                    continue  # already labeled
                for mem in case.get("memories", []):
                    pending.append({
                        "case_id": case["id"],
                        "prompt_idx": prompt_idx,
                        "memory_id": mem["node_id"],
                        "prompt_text": prompt_obj["text"],
                        "memory_title": mem.get("title", ""),
                        "memory_content": mem.get("content", ""),
                    })

    if write:
        out = corpus_dir / "pending_labels.jsonl"
        out.write_text("\n".join(json.dumps(p) for p in pending) + "\n" if pending else "")

    return pending


def import_labels(corpus_dir: Path, labels_file: Path) -> int:
    """Read labels_file and update corpus files with scored labels.

    Score 2 → should_inject, Score 0 → should_not_inject, Score 1 → ignored (ambiguous).
    Returns number of labels applied.
    """
    labels = []
    for line in labels_file.read_text().splitlines():
        line = line.strip()
        if line:
            labels.append(json.loads(line))

    by_case: dict[str, list[dict]] = {}
    for label in labels:
        by_case.setdefault(label["case_id"], []).append(label)

    applied = 0
    corpus_files = list((corpus_dir / "golden").glob("*.jsonl"))
    if (corpus_dir / "synthetic").exists():
        corpus_files += list((corpus_dir / "synthetic").glob("*.jsonl"))

    for corpus_file in corpus_files:
        try:
            cases = load_corpus(corpus_file)
        except Exception:
            continue

        modified = False
        for case in cases:
            case_labels = by_case.get(case["id"], [])
            if not case_labels:
                continue
            for label in case_labels:
                pidx = label["prompt_idx"]
                mid = label["memory_id"]
                score = label["score"]
                if pidx >= len(case.get("prompts", [])):
                    continue
                prompt_obj = case["prompts"][pidx]
                exp = prompt_obj.setdefault("expected", {"should_inject": [], "should_not_inject": []})
                if score == 2 and mid not in exp["should_inject"]:
                    exp["should_inject"].append(mid)
                    applied += 1
                    modified = True
                elif score == 0 and mid not in exp["should_not_inject"]:
                    exp["should_not_inject"].append(mid)
                    applied += 1
                    modified = True

        if modified:
            corpus_file.write_text(
                "\n".join(json.dumps(c) for c in cases) + "\n"
            )

    return applied

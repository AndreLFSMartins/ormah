"""Mine real transcripts into reviewable whisper-eval candidates."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ormah.engine.context_builder import _is_follow_up_prompt
from ormah.transcript.parser import extract_user_prompts


@dataclass
class MiningSummary:
    transcripts_scanned: int
    prompts_seen: int
    candidates_written: int
    category_counts: dict[str, int]
    output_path: Path


def discover_transcripts(root: Path, max_sessions: int | None = None) -> list[Path]:
    """Discover transcript JSONL files under *root*, newest first."""
    root = Path(root).expanduser()
    if not root.exists():
        return []
    paths = sorted(
        (p for p in root.rglob("*.jsonl") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if max_sessions is not None:
        return paths[:max_sessions]
    return paths


def mine_transcript_candidates(
    transcript_paths: list[Path],
    engine,
    output_path: Path,
    *,
    space: str | None = None,
    max_candidates: int = 100,
    recent_prompt_count: int = 2,
    min_user_turns: int = 5,
    include_whisper_text: bool = False,
) -> MiningSummary:
    """Generate reviewable whisper candidates from transcript user turns."""
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    classifier = None
    try:
        classifier = engine.context_builder._get_classifier()
    except Exception:
        classifier = None

    prompts_seen = 0
    candidates: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()

    for transcript_path in transcript_paths:
        prompts = extract_user_prompts(transcript_path)
        if len(prompts) < min_user_turns:
            continue

        session_id = transcript_path.stem
        for idx, prompt in enumerate(prompts):
            prompt = prompt.strip()
            if len(prompt) < 3:
                continue

            prompts_seen += 1
            recent_prompts = prompts[max(0, idx - recent_prompt_count):idx] or None

            categories = ["general"]
            if classifier is not None:
                try:
                    categories = classifier.classify(prompt).categories
                except Exception:
                    categories = ["general"]

            whisper_text, injected_ids = engine.get_whisper_context(
                prompt=prompt,
                space=space,
                recent_prompts=recent_prompts,
                session_id=session_id,
                _return_debug=True,
            )

            interesting = (
                bool(injected_ids)
                or _is_follow_up_prompt(prompt)
                or categories != ["conversational"]
            )
            if not interesting:
                continue

            injected_memories = []
            for node_id in injected_ids:
                node = engine.graph.get_node(node_id)
                if node is None:
                    continue
                injected_memories.append({
                    "node_id": node_id,
                    "title": node.get("title"),
                    "type": node.get("type"),
                    "space": node.get("space"),
                })

            primary_category = categories[0] if categories else "general"
            category_counts[primary_category] += 1
            candidate = {
                "candidate_id": f"mined-{session_id[:8]}-{idx + 1:03d}",
                "source": {
                    "transcript_path": str(transcript_path),
                    "session_id": session_id,
                    "prompt_index": idx + 1,
                },
                "space": space,
                "prompt": {
                    "text": prompt,
                    "recent_prompts": recent_prompts or [],
                },
                "classification": {
                    "intent_categories": categories,
                    "follow_up": _is_follow_up_prompt(prompt),
                },
                "whisper_preview": {
                    "injected_ids": injected_ids,
                    "injected_memories": injected_memories,
                    "text": whisper_text if include_whisper_text else None,
                },
                "review": {
                    "status": "pending",
                    "category": primary_category,
                    "should_inject": injected_ids,
                    "should_not_inject": [],
                    "should_suppress": False,
                    "notes": "Review this candidate and convert it into a golden eval case if useful.",
                },
            }
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    with open(output_path, "w") as f:
        for candidate in candidates:
            f.write(json.dumps(candidate) + "\n")

    return MiningSummary(
        transcripts_scanned=len(transcript_paths),
        prompts_seen=prompts_seen,
        candidates_written=len(candidates),
        category_counts=dict(category_counts),
        output_path=output_path,
    )


def format_mining_summary(summary: MiningSummary) -> str:
    """Format mining summary for terminal output."""
    lines = [
        "Whisper transcript mining complete",
        f"  transcripts scanned: {summary.transcripts_scanned}",
        f"  prompts seen:        {summary.prompts_seen}",
        f"  candidates written:  {summary.candidates_written}",
        f"  output:              {summary.output_path}",
    ]
    if summary.category_counts:
        lines.append("  categories:")
        for category, count in sorted(summary.category_counts.items()):
            lines.append(f"    - {category}: {count}")
    return "\n".join(lines)

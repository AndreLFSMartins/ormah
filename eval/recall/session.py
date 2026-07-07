"""Capture and parse Claude Code session transcripts into unlabeled corpus entries."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path


def capture_session(transcript_path: Path, sessions_dir: Path) -> dict:
    """Copy a Claude Code JSONL transcript and create an unlabeled corpus entry.

    Returns the corpus entry dict (caller should save it to sessions/*.jsonl).
    Session cases have no embedded memories — they run against the full corpus.
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)

    dest = sessions_dir / transcript_path.name
    shutil.copy2(transcript_path, dest)

    prompts = []
    for line in transcript_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "user":
            continue
        msg = obj.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        else:
            text = str(content)
        text = text.strip()
        if text:
            prompts.append({
                "text": text,
                "expected": {"should_inject": [], "should_not_inject": []},
            })

    session_id = f"session-{uuid.uuid4().hex[:8]}"
    return {
        "id": session_id,
        "memories": [],
        "prompts": prompts,
        "source_file": str(dest),
    }

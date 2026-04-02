"""Tests for transcript-derived whisper eval mining."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from eval.whisper.mine import discover_transcripts, mine_transcript_candidates


def _write_jsonl(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


class TestDiscoverTranscripts:
    def test_discovers_newest_first(self, tmp_path):
        older = _write_jsonl(tmp_path / "a" / "older.jsonl", [])
        newer = _write_jsonl(tmp_path / "b" / "newer.jsonl", [])
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_800_000_000, 1_800_000_000))
        paths = discover_transcripts(tmp_path)
        assert paths[0].name == "newer.jsonl"


class TestMineTranscriptCandidates:
    def test_writes_reviewable_candidates(self, tmp_path):
        transcript = _write_jsonl(
            tmp_path / "proj" / "session-123.jsonl",
            [
                {"type": "user", "message": {"content": "how does the whisper eval pipeline work?"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}},
                {"type": "user", "message": {"content": "what about the report format?"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}},
                {"type": "user", "message": {"content": "and for Codex?"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}},
                {"type": "user", "message": {"content": "show me the current metrics"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}},
                {"type": "user", "message": {"content": "thanks"}},
            ],
        )

        mock_engine = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.classify.side_effect = [
            MagicMock(categories=["technical"]),
            MagicMock(categories=["continuation"]),
            MagicMock(categories=["continuation"]),
            MagicMock(categories=["technical"]),
            MagicMock(categories=["conversational"]),
        ]
        mock_engine.context_builder._get_classifier.return_value = mock_classifier
        mock_engine.get_whisper_context.side_effect = [
            ("text-1", ["node-1"]),
            ("text-2", ["node-2"]),
            ("text-3", ["node-3"]),
            ("", []),
            ("", []),
        ]
        mock_engine.graph.get_node.side_effect = lambda node_id: {
            "id": node_id,
            "title": f"title-{node_id}",
            "type": "fact",
            "space": "ormah",
        }

        output = tmp_path / "mined.jsonl"
        summary = mine_transcript_candidates(
            [transcript],
            mock_engine,
            output,
            space="ormah",
            max_candidates=10,
            min_user_turns=5,
            include_whisper_text=True,
        )

        assert summary.candidates_written == 4
        lines = [json.loads(line) for line in output.read_text().splitlines()]
        assert lines[0]["prompt"]["text"] == "how does the whisper eval pipeline work?"
        assert lines[1]["prompt"]["recent_prompts"] == ["how does the whisper eval pipeline work?"]
        assert lines[1]["classification"]["follow_up"] is True
        assert lines[2]["whisper_preview"]["injected_memories"][0]["title"] == "title-node-3"

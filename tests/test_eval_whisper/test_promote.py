"""Tests for whisper candidate promotion."""
from __future__ import annotations

import json
from pathlib import Path

from eval.whisper.promote import (
    candidate_to_case,
    load_mined_candidates,
    promote_candidates,
)
from ormah.models.node import CreateNodeRequest, NodeType, Tier


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


class TestPromoteCandidates:
    def test_load_mined_candidates(self, tmp_path):
        path = _write_jsonl(tmp_path / "candidates.jsonl", [{"candidate_id": "a"}, {"candidate_id": "b"}])
        rows = load_mined_candidates(path)
        assert [row["candidate_id"] for row in rows] == ["a", "b"]

    def test_candidate_to_case_maps_review_labels(self, engine):
        node_id, _ = engine.remember(
            CreateNodeRequest(
                content="Ormah uses SQLite for local-first storage.",
                title="SQLite storage",
                type=NodeType.fact,
                tier=Tier.working,
            )
        )
        candidate = {
            "candidate_id": "mined-123",
            "space": "ormah",
            "source": {"session_id": "sess-1", "prompt_index": 1},
            "prompt": {"text": "what database does ormah use?", "recent_prompts": []},
            "classification": {"intent_categories": ["factual"], "follow_up": False},
            "whisper_preview": {"injected_ids": [node_id], "injected_memories": []},
            "review": {
                "status": "pending",
                "category": "factual",
                "should_inject": [node_id],
                "should_not_inject": [],
                "should_suppress": False,
            },
        }

        case = candidate_to_case(candidate, engine)
        assert case is not None
        assert case["id"] == "promoted-mined-123"
        assert case["prompts"][0]["expected"]["should_inject"] == [node_id]
        assert case["memories"][0]["node_id"] == node_id

    def test_promote_candidates_skips_unlabeled_and_duplicates(self, engine, tmp_path):
        node_id, _ = engine.remember(
            CreateNodeRequest(
                content="Use SQLite for the graph index.",
                title="SQLite graph index",
                type=NodeType.fact,
                tier=Tier.working,
            )
        )
        candidates_path = _write_jsonl(
            tmp_path / "candidates.jsonl",
            [
                {
                    "candidate_id": "keep-me",
                    "space": "ormah",
                    "source": {"session_id": "sess-1", "prompt_index": 1},
                    "prompt": {"text": "what database?", "recent_prompts": []},
                    "classification": {"intent_categories": ["factual"], "follow_up": False},
                    "whisper_preview": {"injected_ids": [node_id], "injected_memories": []},
                    "review": {"should_inject": [node_id], "should_not_inject": [], "should_suppress": False},
                },
                {
                    "candidate_id": "skip-me",
                    "space": "ormah",
                    "source": {"session_id": "sess-2", "prompt_index": 1},
                    "prompt": {"text": "unlabeled", "recent_prompts": []},
                    "classification": {"intent_categories": ["general"], "follow_up": False},
                    "whisper_preview": {"injected_ids": [], "injected_memories": []},
                    "review": {"should_inject": [], "should_not_inject": [], "should_suppress": False},
                },
            ],
        )
        output_path = tmp_path / "mined.jsonl"

        first = promote_candidates(candidates_path, output_path, engine)
        second = promote_candidates(candidates_path, output_path, engine)

        lines = [json.loads(line) for line in output_path.read_text().splitlines()]
        assert first.cases_emitted == 1
        assert first.skipped_candidates == 1
        assert second.cases_emitted == 0
        assert second.duplicate_candidates == 1
        assert len(lines) == 1
        manifest = json.loads(output_path.with_suffix(".manifest.json").read_text())
        assert manifest["duplicate_candidates"] == 1

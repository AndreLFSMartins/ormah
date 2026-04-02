"""End-to-end tests for mine -> promote -> eval flow."""
from __future__ import annotations

import json

from eval.whisper.corpus import load_corpora
from eval.whisper.promote import promote_candidates
from eval.whisper.runner import run_whisper_eval
from ormah.models.node import CreateNodeRequest, NodeType, Tier


class TestPromoteE2E:
    def test_promoted_cases_run_in_eval(self, engine, tmp_path):
        node_id, _ = engine.remember(
            CreateNodeRequest(
                content="Ormah uses SQLite for local-first storage.",
                title="SQLite storage",
                type=NodeType.fact,
                tier=Tier.working,
            )
        )

        candidates_path = tmp_path / "candidates.jsonl"
        candidates_path.write_text(
            json.dumps(
                {
                    "candidate_id": "sqlite-fact",
                    "space": "ormah",
                    "source": {
                        "transcript_path": "/tmp/session.jsonl",
                        "session_id": "sess-1",
                        "prompt_index": 1,
                    },
                    "prompt": {
                        "text": "what database does ormah use?",
                        "recent_prompts": [],
                    },
                    "classification": {
                        "intent_categories": ["factual"],
                        "follow_up": False,
                    },
                    "whisper_preview": {
                        "injected_ids": [node_id],
                        "injected_memories": [{"node_id": node_id, "title": "SQLite storage"}],
                    },
                    "review": {
                        "status": "pending",
                        "category": "factual",
                        "should_inject": [node_id],
                        "should_not_inject": [],
                        "should_suppress": False,
                    },
                }
            )
            + "\n"
        )

        output_path = tmp_path / "mined.jsonl"
        promote_candidates(candidates_path, output_path, engine, replace_output=True)
        cases = load_corpora([output_path])
        result = run_whisper_eval(cases, engine)

        assert result.aggregate["total_prompts"] == 1
        assert result.aggregate["injection_recall"] == 1.0
        assert result.aggregate["injection_precision"] == 1.0

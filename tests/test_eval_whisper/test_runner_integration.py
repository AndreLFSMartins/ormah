"""End-to-end integration coverage for the whisper eval harness."""
from __future__ import annotations

import pytest

from eval.whisper.cli import _EVAL_SETTINGS_OVERRIDES
from eval.whisper.runner import run_whisper_eval


@pytest.mark.integration
def test_run_whisper_eval_end_to_end_with_real_engine(tmp_path):
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    settings = Settings(memory_dir=tmp_path, **_EVAL_SETTINGS_OVERRIDES)
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        if settings.whisper_reranker_enabled and not engine._whisper_reranker_available:
            pytest.skip("requires whisper reranker availability")

        cases = [
            {
                "id": "fact-case",
                "space": "ormah",
                "memories": [
                    {
                        "node_id": "fact-hit",
                        "title": "Zephyr sentinel code",
                        "content": "The zephyr sentinel code is amber-42.",
                        "type": "fact",
                        "tier": "working",
                        "space": "ormah",
                    },
                    {
                        "node_id": "fact-miss",
                        "title": "Default port",
                        "content": "Ormah runs on port 8787.",
                        "type": "fact",
                        "tier": "working",
                        "space": "ormah",
                    },
                ],
                "prompts": [
                    {
                        "text": "what is the zephyr sentinel code",
                        "category": "factual",
                        "expected": {
                            "must_include": ["fact-hit"],
                            "must_not_include": ["fact-miss"],
                            "must_be_silent": False,
                        },
                    }
                ],
            },
            {
                "id": "noise-case",
                "space": "ormah",
                "memories": [
                    {
                        "node_id": "noise-fact",
                        "title": "Port setting",
                        "content": "Ormah runs on port 8787.",
                        "type": "fact",
                        "tier": "working",
                        "space": "ormah",
                    }
                ],
                "prompts": [
                    {
                        "text": "hello",
                        "category": "noise",
                        "expected": {
                            "must_include": [],
                            "must_not_include": ["noise-fact"],
                            "must_be_silent": True,
                        },
                    }
                ],
            },
        ]

        result = run_whisper_eval(cases, engine)

        assert len(result.prompt_results) == 2
        factual = next(r for r in result.prompt_results if r.case_id == "fact-case")
        noise = next(r for r in result.prompt_results if r.case_id == "noise-case")

        assert "fact-hit" in factual.injected_ids
        assert "fact-miss" not in factual.injected_ids
        assert factual.metrics["injection_recall"] == 1.0
        assert factual.metrics["injection_precision"] == 1.0
        assert factual.metrics["false_positive_present"] is False

        assert noise.injected_ids == []
        assert noise.metrics["suppression_correct"] is True

        assert result.aggregate["injection_recall"] == 1.0
        assert result.aggregate["injection_precision"] == 1.0
        assert result.aggregate["f1"] == 1.0
        assert result.aggregate["false_positive_rate"] == 0.0
        assert result.aggregate["suppression_accuracy"] == 1.0
    finally:
        engine.shutdown()

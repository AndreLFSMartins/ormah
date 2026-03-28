"""Tests for eval/whisper/runner.py."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from eval.whisper.runner import run_whisper_eval, _aggregate, _aggregate_by_category


_CASES = [
    {
        "id": "w-fact-001",
        "space": "ormah",
        "memories": [
            {"node_id": "mem-001", "title": "Port fact", "content": "Runs on 8787.", "type": "fact", "tier": "working"},
            {"node_id": "mem-002", "title": "Distractor", "content": "Unrelated.", "type": "fact", "tier": "working"},
        ],
        "prompts": [
            {
                "text": "what port does ormah run on",
                "category": "factual",
                "expected": {
                    "should_inject": ["mem-001"],
                    "should_not_inject": ["mem-002"],
                    "should_suppress": False,
                },
            }
        ],
    },
    {
        "id": "w-noise-001",
        "space": "ormah",
        "memories": [
            {"node_id": "mem-003", "title": "Some fact", "content": "Content.", "type": "fact", "tier": "working"},
        ],
        "prompts": [
            {
                "text": "hello",
                "category": "noise",
                "expected": {"should_inject": [], "should_not_inject": [], "should_suppress": True},
            }
        ],
    },
]


class TestRunWhisperEval:
    def test_returns_result_per_prompt(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),  # factual case: hit
            ("", []),                        # noise case: suppressed
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        assert len(result.prompt_results) == 2

    def test_factual_hit_metrics(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        factual = next(r for r in result.prompt_results if r.category == "factual")
        assert factual.metrics["injection_recall"] == 1.0
        assert factual.metrics["false_positive_present"] is False

    def test_noise_suppression_metrics(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("whisper text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        noise = next(r for r in result.prompt_results if r.category == "noise")
        assert noise.metrics["suppression_correct"] is True

    def test_engine_called_with_correct_args(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.return_value = ("", [])
        with patch("eval.whisper.runner.seed_case"):
            run_whisper_eval([_CASES[0]], mock_engine)
        call_kwargs = mock_engine.get_whisper_context.call_args
        assert call_kwargs.kwargs["recent_prompts"] == []
        assert call_kwargs.kwargs["session_id"] is None
        assert call_kwargs.kwargs["_return_debug"] is True
        assert call_kwargs.kwargs["space"] == "ormah"

    def test_seed_called_once_per_case(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.return_value = ("", [])
        with patch("eval.whisper.runner.seed_case") as mock_seed:
            run_whisper_eval(_CASES, mock_engine)
        assert mock_seed.call_count == 2

    def test_category_aggregates_split_by_category(self):
        mock_engine = MagicMock()
        mock_engine.get_whisper_context.side_effect = [
            ("text", ["mem-001"]),
            ("", []),
        ]
        with patch("eval.whisper.runner.seed_case"):
            result = run_whisper_eval(_CASES, mock_engine)
        assert "factual" in result.category_aggregates
        assert "noise" in result.category_aggregates


class TestAggregate:
    def _make_result(self, category, recall, suppression_correct=None):
        from eval.whisper.runner import PromptResult
        metrics = {
            "injection_recall": recall,
            "injection_precision": recall,
            "f1": recall,
            "top2_recall": recall,
            "suppression_correct": suppression_correct,
            "false_positive_present": False,
            "injection_fired": recall is not None and recall > 0,
        }
        return PromptResult(
            case_id="x", prompt="q", category=category,
            should_inject=[], injected_ids=[], metrics=metrics,
        )

    def test_mean_recall_across_prompts(self):
        results = [self._make_result("factual", 1.0), self._make_result("factual", 0.5)]
        agg = _aggregate(results)
        assert agg["injection_recall"] == pytest.approx(0.75)

    def test_suppression_accuracy(self):
        results = [
            self._make_result("noise", None, suppression_correct=True),
            self._make_result("noise", None, suppression_correct=False),
        ]
        agg = _aggregate(results)
        assert agg["suppression_accuracy"] == pytest.approx(0.5)

    def test_no_labeled_non_noise_returns_none_for_recall(self):
        results = [self._make_result("noise", None, suppression_correct=True)]
        agg = _aggregate(results)
        assert agg["injection_recall"] is None

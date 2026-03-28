"""Tests for eval/whisper/report.py."""
from __future__ import annotations
from eval.whisper.runner import PromptResult, WhisperEvalResult
from eval.whisper.report import format_report


def _make_result(category, recall, suppression_correct=None, fp=False,
                 case_id="c-1", prompt="q", should_inject=None, injected_ids=None):
    prec = recall
    metrics = {
        "injection_recall": recall,
        "injection_precision": prec,
        "f1": recall,
        "top2_recall": recall,
        "suppression_correct": suppression_correct,
        "false_positive_present": fp,
        "injection_fired": bool(recall),
    }
    return PromptResult(
        case_id=case_id, prompt=prompt, category=category,
        should_inject=should_inject or [],
        injected_ids=injected_ids or [],
        metrics=metrics,
    )


def _make_eval_result(prompt_results):
    from eval.whisper.runner import _aggregate
    from collections import defaultdict
    by_cat = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    return WhisperEvalResult(
        prompt_results=prompt_results,
        aggregate=_aggregate(prompt_results),
        category_aggregates={cat: _aggregate(rs) for cat, rs in by_cat.items()},
    )


class TestFormatReport:
    def test_report_contains_overall(self):
        result = _make_eval_result([_make_result("factual", 0.8)])
        report = format_report(result)
        assert "OVERALL" in report

    def test_report_contains_category_name(self):
        result = _make_eval_result([_make_result("preference", 0.67)])
        report = format_report(result)
        assert "preference" in report

    def test_report_contains_noise_suppression_accuracy(self):
        result = _make_eval_result([
            _make_result("noise", None, suppression_correct=True),
            _make_result("noise", None, suppression_correct=False),
        ])
        report = format_report(result)
        assert "suppression" in report.lower()
        assert "0.50" in report or "50%" in report

    def test_failures_shown_when_flag_set(self):
        result = _make_eval_result([
            _make_result(
                "factual", 0.0,
                case_id="w-fact-001", prompt="what port",
                should_inject=["mem-001"], injected_ids=[],
            )
        ])
        report = format_report(result, show_failures=True)
        assert "w-fact-001" in report
        assert "what port" in report

    def test_failures_hidden_by_default(self):
        result = _make_eval_result([
            _make_result("factual", 0.0, case_id="w-fail-001", prompt="failing prompt")
        ])
        report = format_report(result, show_failures=False)
        assert "failing prompt" not in report

    def test_prompt_count_in_header(self):
        results = [_make_result("factual", 1.0) for _ in range(5)]
        result = _make_eval_result(results)
        report = format_report(result)
        assert "5" in report

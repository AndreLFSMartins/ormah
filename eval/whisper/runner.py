"""Whisper eval runner — seeds DB, calls full pipeline, collects metrics per prompt."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from eval.whisper.metrics import compute_prompt_metrics
from eval.whisper.seeder import seed_case


@dataclass
class PromptResult:
    case_id: str
    prompt: str
    category: str
    should_inject: list[str]
    injected_ids: list[str]
    metrics: dict


@dataclass
class WhisperEvalResult:
    prompt_results: list[PromptResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    category_aggregates: dict = field(default_factory=dict)


def run_whisper_eval(cases: list[dict], engine) -> WhisperEvalResult:
    """Run the whisper eval pipeline over *cases*."""
    prompt_results: list[PromptResult] = []

    for case in cases:
        seed_case(engine, case)
        space = case.get("space")

        for prompt_obj in case.get("prompts", []):
            text = prompt_obj["text"]
            category = prompt_obj.get("category", "general")
            expected = prompt_obj.get("expected", {})
            should_inject = expected.get("should_inject", [])
            should_not_inject = expected.get("should_not_inject", [])
            should_suppress = expected.get("should_suppress", False)

            whisper_text, injected_ids = engine.get_whisper_context(
                prompt=text,
                space=space,
                recent_prompts=[],
                session_id=None,
                _return_debug=True,
            )

            metrics = compute_prompt_metrics(
                should_inject=should_inject,
                should_not_inject=should_not_inject,
                should_suppress=should_suppress,
                injected_ids=injected_ids,
                injection_fired=bool(whisper_text.strip()),
            )

            prompt_results.append(PromptResult(
                case_id=case["id"],
                prompt=text,
                category=category,
                should_inject=should_inject,
                injected_ids=injected_ids,
                metrics=metrics,
            ))

    aggregate = _aggregate(prompt_results)
    by_cat = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    category_aggregates = {cat: _aggregate(results) for cat, results in by_cat.items()}

    return WhisperEvalResult(
        prompt_results=prompt_results,
        aggregate=aggregate,
        category_aggregates=category_aggregates,
    )


def _aggregate(prompt_results: list[PromptResult]) -> dict:
    """Aggregate metrics across prompt results. Noise and non-noise are separated."""
    non_noise = [r for r in prompt_results if r.metrics["suppression_correct"] is None]
    noise = [r for r in prompt_results if r.metrics["suppression_correct"] is not None]

    def _avg(key: str, results: list[PromptResult]) -> Optional[float]:
        vals = [r.metrics[key] for r in results if r.metrics.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    result: dict = {
        "total_prompts": len(prompt_results),
        "injection_recall": _avg("injection_recall", non_noise),
        "injection_precision": _avg("injection_precision", non_noise),
        "f1": _avg("f1", non_noise),
        "top2_recall": _avg("top2_recall", non_noise),
        "false_positive_rate": (
            sum(1 for r in prompt_results if r.metrics["false_positive_present"]) / len(prompt_results)
            if prompt_results else None
        ),
    }

    if noise:
        correct = sum(1 for r in noise if r.metrics["suppression_correct"])
        result["suppression_accuracy"] = correct / len(noise)
        result["suppression_correct_count"] = correct
        result["suppression_count"] = len(noise)

    return result


def _aggregate_by_category(prompt_results: list[PromptResult]) -> dict:
    by_cat: dict[str, list[PromptResult]] = defaultdict(list)
    for r in prompt_results:
        by_cat[r.category].append(r)
    return {cat: _aggregate(results) for cat, results in by_cat.items()}

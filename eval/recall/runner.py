"""Recall eval runner: orchestrates per-case seeding, retrieval, and scoring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from eval.recall.metrics import compute_case_metrics
from eval.recall.seeder import seed_case

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    case_results: list[dict] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)


def run_eval(
    cases: list[dict],
    engine,
    k: int = 8,
    min_score: float | None = None,
    injection_gate: float | None = None,
) -> EvalResult:
    """Run the recall eval pipeline over *cases*. Returns EvalResult with per-case and aggregate metrics.

    min_score and injection_gate default to the ENGINE's own settings
    (recall_min_relevance_score / whisper_injection_gate) so the eval
    measures production behavior instead of hard-coded constants that
    can silently drift from it.

    For each case:
    1. Seed eval DB with only that case's memories (full corpus cleared first)
    2. Run recall_search_structured for each prompt
    3. Compute metrics against ground truth labels
    """
    settings = getattr(engine, "settings", None)
    if min_score is None:
        min_score = getattr(settings, "recall_min_relevance_score", 0.35)
    if injection_gate is None:
        injection_gate = getattr(settings, "whisper_injection_gate", 0.45)

    all_case_results = []

    for case in cases:
        case_result = _eval_case(case, engine, k=k, min_score=min_score, injection_gate=injection_gate)
        all_case_results.append(case_result)

    aggregate = _aggregate(all_case_results, k=k)
    return EvalResult(case_results=all_case_results, aggregate=aggregate)


def _eval_case(case: dict, engine, k: int, min_score: float, injection_gate: float) -> dict:
    """Seed and evaluate a single corpus case."""
    seed_case(engine, case)

    prompt_results = []
    for prompt_obj in case.get("prompts", []):
        prompt_text = prompt_obj["text"]
        expected = prompt_obj.get("expected", {})
        should_inject = expected.get("should_inject", [])
        should_not_inject = expected.get("should_not_inject", [])

        try:
            raw = engine.recall_search_structured(
                query=prompt_text,
                limit=k * 2,  # over-fetch before filtering
                # Production callers always pass the project space (MCP/route
                # default_space) — mirror it so space scoring is measured.
                default_space=case.get("space"),
                tiers=["core", "working"],
                touch_access=False,
            )
        except Exception as e:
            logger.warning("recall_search_structured failed for case %s: %s", case["id"], e)
            raw = []

        filtered = [r for r in raw if r.get("score", 0) >= min_score]
        ranked_ids = [r["node"]["id"] for r in filtered]
        ranked_scores = [r.get("score", 0.0) for r in filtered]

        metrics = compute_case_metrics(
            should_inject=should_inject,
            ranked_ids=ranked_ids,
            injection_gate=injection_gate,
            ranked_scores=ranked_scores,
            k=k,
            should_not_inject=should_not_inject,
        )
        prompt_results.append({
            "prompt": prompt_text,
            "should_inject": should_inject,
            "should_not_inject": should_not_inject,
            "all_ranked_ids": ranked_ids,
            "metrics": metrics,
        })

    return {
        "case_id": case["id"],
        "prompt_results": prompt_results,
    }


def _aggregate(case_results: list[dict], k: int) -> dict:
    """Compute aggregate metrics across all prompt results. Returns None for each metric if no labeled cases."""
    all_metrics = [
        pr["metrics"]
        for cr in case_results
        for pr in cr.get("prompt_results", [])
    ]
    labeled = [m for m in all_metrics if m["recall"] is not None]

    # fp_rate covers every prompt with negative labels — including
    # negative-only prompts, whose positive metrics stay None.
    neg_labeled = [m for m in all_metrics if m.get("false_positive_present") is not None]
    fp_rate = (
        sum(1 for m in neg_labeled if m["false_positive_present"]) / len(neg_labeled)
        if neg_labeled else None
    )
    fired = [m for m in all_metrics if m["injection_fired"]]
    # injection_rate uses all prompts (labeled + unlabeled) — it measures pipeline fire rate,
    # not retrieval quality. Positive metrics use only positively-labeled prompts.
    injection_rate = len(fired) / len(all_metrics) if all_metrics else None

    if not labeled:
        return {
            "recall": None, "precision": None, "f1": None,
            "mrr": None, "false_negative_rate": None,
            "false_positive_rate": fp_rate,
            "injection_rate": injection_rate,
            "case_count": len(case_results),
            "labeled_prompt_count": 0,
        }

    def _avg(key):
        vals = [m[key] for m in labeled if m[key] is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "recall": _avg("recall"),
        "precision": _avg("precision"),
        "f1": _avg("f1"),
        "mrr": _avg("mrr"),
        "false_negative_rate": _avg("false_negative_rate"),
        "false_positive_rate": fp_rate,
        "injection_rate": injection_rate,
        "case_count": len(case_results),
        "labeled_prompt_count": len(labeled),
    }

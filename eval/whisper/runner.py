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
    may_include: list[str] = field(default_factory=list)
    should_not_inject: list[str] = field(default_factory=list)
    should_suppress: bool = False
    intent_categories: list[str] | None = None
    has_temporal_phrases: bool | None = None
    session_id: str | None = None
    recent_prompts: list[str] | None = None


@dataclass
class WhisperEvalResult:
    prompt_results: list[PromptResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    category_aggregates: dict = field(default_factory=dict)


def run_whisper_eval(
    cases: list[dict],
    engine,
    *,
    simulate_session: bool = False,
    preserve_self: bool | None = None,
) -> WhisperEvalResult:
    """Run the whisper eval pipeline over *cases*."""
    prompt_results: list[PromptResult] = []

    for case in cases:
        effective_preserve_self = (
            bool(case.get("preserve_self", False)) if preserve_self is None else preserve_self
        )
        seed_case(engine, case, preserve_self=effective_preserve_self)
        space = case.get("space")
        case_simulate_session = bool(case.get("simulate_session", False)) or simulate_session
        case_session_id = case.get("session_id")
        session_buf: list[str] = []

        for prompt_obj in case.get("prompts", []):
            text = prompt_obj["text"]
            category = prompt_obj.get("category", "general")
            expected = prompt_obj.get("expected", {})
            should_inject = expected.get("must_include") or expected.get("should_inject", [])
            may_include = expected.get("may_include", [])
            should_not_inject = expected.get("must_not_include") or expected.get("should_not_inject", [])
            should_suppress = expected.get("must_be_silent", expected.get("should_suppress", False))

            # Capture intent classification (same one used by whisper) for analysis.
            intent_categories = None
            has_temporal_phrases = None
            try:
                classifier = engine.context_builder._get_classifier()
                if classifier is not None:
                    intent_categories = classifier.classify(text).categories
                from ormah.engine.prompt_classifier import has_temporal_phrases as _htp
                has_temporal_phrases = _htp(text)
            except Exception:
                pass

            # Session simulation: mimic /agent/whisper route behavior.
            session_id = prompt_obj.get("session_id") or case_session_id
            if "recent_prompts" in prompt_obj:
                recent_prompts = prompt_obj.get("recent_prompts")
            elif case_simulate_session and session_id and text.strip():
                # First message: None; subsequent: all prior prompts (bounded by settings buffer size).
                if session_buf:
                    buf_size = getattr(engine.settings, "whisper_context_buffer_size", 5)
                    recent_prompts = session_buf[-buf_size:]
                else:
                    recent_prompts = None
            else:
                recent_prompts = []

            whisper_text, injected_ids = engine.get_whisper_context(
                prompt=text,
                space=space,
                recent_prompts=recent_prompts,
                session_id=session_id,
                _return_debug=True,
            )
            if case_simulate_session and session_id and text.strip():
                session_buf.append(text.strip())

            metrics = compute_prompt_metrics(
                should_inject=should_inject,
                should_not_inject=should_not_inject,
                should_suppress=should_suppress,
                injected_ids=injected_ids,
                injection_fired=bool(whisper_text.strip()),
                may_include=may_include,
            )

            prompt_results.append(PromptResult(
                case_id=case["id"],
                prompt=text,
                category=category,
                should_inject=should_inject,
                may_include=may_include,
                should_not_inject=should_not_inject,
                should_suppress=should_suppress,
                intent_categories=intent_categories,
                has_temporal_phrases=has_temporal_phrases,
                session_id=session_id,
                recent_prompts=recent_prompts,
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

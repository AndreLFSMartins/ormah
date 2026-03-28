"""Format whisper eval results as a human-readable table."""
from __future__ import annotations

from eval.whisper.runner import WhisperEvalResult

_CATEGORY_ORDER = [
    "preference", "factual", "decision", "technical",
    "identity", "temporal", "continuation", "noise",
]


def _fmt(val, width=6) -> str:
    if val is None:
        return " " * width
    return f"{val:.2f}".rjust(width)


def format_report(result: WhisperEvalResult, show_failures: bool = False) -> str:
    lines = []
    total = result.aggregate.get("total_prompts", 0)
    n_cats = len(result.category_aggregates)
    lines.append(f"Whisper Eval  ({total} prompts, {n_cats} categories)")
    lines.append("═" * 72)
    lines.append(f"{'':20s}  {'recall':>7}  {'prec':>7}  {'f1':>7}  {'top2':>7}  {'fp_rate':>7}")

    for cat in _CATEGORY_ORDER:
        agg = result.category_aggregates.get(cat)
        if agg is None:
            continue
        count = agg.get("total_prompts", 0)
        label = f"{cat} ({count})"

        if cat == "noise":
            acc = agg.get("suppression_accuracy")
            correct = agg.get("suppression_correct_count", 0)
            total_noise = agg.get("suppression_count", 0)
            lines.append("─" * 72)
            lines.append(
                f"{'noise':20s}  suppression_accuracy: {_fmt(acc).strip()}"
                f"  ({correct}/{total_noise} correctly silent)"
            )
            lines.append("─" * 72)
        else:
            lines.append(
                f"{label:20s}"
                f"  {_fmt(agg.get('injection_recall'))}"
                f"  {_fmt(agg.get('injection_precision'))}"
                f"  {_fmt(agg.get('f1'))}"
                f"  {_fmt(agg.get('top2_recall'))}"
                f"  {_fmt(agg.get('false_positive_rate'))}"
            )

    agg = result.aggregate
    lines.append("═" * 72)
    lines.append(
        f"{'OVERALL':20s}"
        f"  {_fmt(agg.get('injection_recall'))}"
        f"  {_fmt(agg.get('injection_precision'))}"
        f"  {_fmt(agg.get('f1'))}"
        f"  {_fmt(agg.get('top2_recall'))}"
        f"  {_fmt(agg.get('false_positive_rate'))}"
    )

    if show_failures:
        failures = _collect_failures(result)
        if failures:
            lines.append("")
            lines.append(f"FAILURES ({len(failures)}):")
            for f in failures:
                lines.append(f"  {f['case_id']:20s}  [{f['category']}]  \"{f['prompt']}\"")
                expected_str = str(f['should_inject']) if f['should_inject'] else "(suppress)"
                got_str = str(f['injected_ids']) if f['injected_ids'] else "[]"
                lines.append(f"    expected: {expected_str}  injected: {got_str}")

    return "\n".join(lines)


def _collect_failures(result: WhisperEvalResult) -> list[dict]:
    failures = []
    for r in result.prompt_results:
        m = r.metrics
        is_failure = (
            (m["injection_recall"] is not None and m["injection_recall"] < 1.0)
            or m["false_positive_present"]
            or m["suppression_correct"] is False
        )
        if is_failure:
            failures.append({
                "case_id": r.case_id,
                "category": r.category,
                "prompt": r.prompt,
                "should_inject": r.should_inject,
                "injected_ids": r.injected_ids,
            })
    return failures

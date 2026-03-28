"""Metrics for whisper eval: injection recall, precision, f1, top2_recall, suppression."""
from __future__ import annotations
from typing import Optional


def injection_recall(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of should_inject nodes that appeared in injected output."""
    if not should_inject:
        return None
    injected_set = set(injected_ids)
    return sum(1 for nid in should_inject if nid in injected_set) / len(should_inject)


def injection_precision(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of injected nodes that were in should_inject."""
    if not should_inject:
        return None
    if not injected_ids:
        return 0.0
    relevant = set(should_inject)
    return sum(1 for nid in injected_ids if nid in relevant) / len(injected_ids)


def f1_score(recall: Optional[float], precision: Optional[float]) -> Optional[float]:
    if recall is None or precision is None:
        return None
    if recall + precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


def top2_recall(should_inject: list[str], injected_ids: list[str]) -> Optional[float]:
    """Fraction of should_inject nodes in top-2 injected positions (shown in full)."""
    if not should_inject:
        return None
    top2 = set(injected_ids[:2])
    return sum(1 for nid in should_inject if nid in top2) / len(should_inject)


def has_false_positive(should_not_inject: list[str], injected_ids: list[str]) -> bool:
    """True if any should_not_inject node appeared in injected output."""
    injected_set = set(injected_ids)
    return any(nid in injected_set for nid in should_not_inject)


def suppression_correct(should_suppress: bool, injection_fired: bool) -> Optional[bool]:
    """For noise cases: True if pipeline correctly stayed silent. None for non-noise."""
    if not should_suppress:
        return None
    return not injection_fired


def compute_prompt_metrics(
    should_inject: list[str],
    should_not_inject: list[str],
    should_suppress: bool,
    injected_ids: list[str],
    injection_fired: bool,
) -> dict:
    rec = injection_recall(should_inject, injected_ids)
    prec = injection_precision(should_inject, injected_ids)
    return {
        "injection_recall": rec,
        "injection_precision": prec,
        "f1": f1_score(rec, prec),
        "top2_recall": top2_recall(should_inject, injected_ids),
        "suppression_correct": suppression_correct(should_suppress, injection_fired),
        "false_positive_present": has_false_positive(should_not_inject, injected_ids),
        "injection_fired": injection_fired,
    }

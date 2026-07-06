"""Precision, recall, and related retrieval metrics for recall eval."""

from __future__ import annotations


def recall_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Fraction of should_inject nodes appearing in top-k ranked results.

    Returns None if should_inject is empty (undefined metric).
    """
    if not should_inject:
        return None
    top_k = set(ranked_ids[:k])
    hits = sum(1 for nid in should_inject if nid in top_k)
    return hits / len(should_inject)


def precision_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Fraction of top-k injected nodes that are in should_inject.

    Returns None if should_inject is empty (undefined metric).
    """
    if not should_inject:
        return None
    top_k = ranked_ids[:k]
    if not top_k:
        return 0.0
    relevant = set(should_inject)
    hits = sum(1 for nid in top_k if nid in relevant)
    return hits / len(top_k)


def f1_at_k(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Harmonic mean of recall@k and precision@k. Returns None if recall is None."""
    r = recall_at_k(should_inject, ranked_ids, k)
    if r is None:
        return None
    p = precision_at_k(should_inject, ranked_ids, k)
    if r + p == 0:
        return 0.0
    return 2 * p * r / (p + r)


def mrr(should_inject: list[str], ranked_ids: list[str]) -> float | None:
    """Mean Reciprocal Rank of the first relevant result.

    Returns None if should_inject is empty (undefined metric).
    """
    if not should_inject:
        return None
    relevant = set(should_inject)
    for rank, nid in enumerate(ranked_ids, start=1):
        if nid in relevant:
            return 1.0 / rank
    return 0.0


def false_negative_rate(
    should_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> float | None:
    """Fraction of should_inject nodes completely missed (not in top-k).

    Returns None if should_inject is empty.
    """
    if not should_inject:
        return None
    top_k = set(ranked_ids[:k])
    missed = sum(1 for nid in should_inject if nid not in top_k)
    return missed / len(should_inject)


def false_positive_present(
    should_not_inject: list[str],
    ranked_ids: list[str],
    k: int,
) -> bool | None:
    """True if any forbidden node appears in top-k.

    Returns None if the prompt has no negative labels (undefined metric).
    """
    if not should_not_inject:
        return None
    top_k = set(ranked_ids[:k])
    return any(nid in top_k for nid in should_not_inject)


def compute_case_metrics(
    should_inject: list[str],
    ranked_ids: list[str],
    injection_gate: float,
    ranked_scores: list[float],
    k: int,
    should_not_inject: list[str] | None = None,
) -> dict:
    """Compute all metrics for a single (prompt, results) pair.

    injection_fired: True if at least one result passes the injection_gate.
    Negative-only cases (empty should_inject, non-empty should_not_inject)
    contribute false_positive_present while positive metrics stay None.
    """
    above_gate = [nid for nid, score in zip(ranked_ids, ranked_scores) if score >= injection_gate]
    return {
        "recall": recall_at_k(should_inject, ranked_ids, k),
        "precision": precision_at_k(should_inject, ranked_ids, k),
        "f1": f1_at_k(should_inject, ranked_ids, k),
        "mrr": mrr(should_inject, ranked_ids),
        "false_negative_rate": false_negative_rate(should_inject, ranked_ids, k),
        "false_positive_present": false_positive_present(should_not_inject or [], ranked_ids, k),
        "injection_fired": len(above_gate) > 0,
    }

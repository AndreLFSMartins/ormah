"""Batch judgment of candidate pairs — shared by the pairwise maintenance jobs (#87).

K=1 (the default) never builds a batch prompt: callers' existing single-pair
functions run unchanged, so upstream behavior is byte-identical out of the box.
At K>1, an LLM-unavailable chunk aborts the remaining chunks (outage guard).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from ormah.background.llm_client import extract_json, llm_generate

logger = logging.getLogger(__name__)

_BATCH_PREAMBLE = """\
You will judge {n} independent pairs below. Judge each pair strictly on its own; \
do not let any other pair influence a verdict.

Return ONE JSON object: {{"verdicts": [<one verdict object per pair, with the fields \
specified above PLUS a "pair_id" integer matching the pair's number>]}}. \
Include every pair_id exactly once."""


def build_batch_prompt(instruction_block: str, rendered_pairs: list[str]) -> str:
    parts = [instruction_block, _BATCH_PREAMBLE.format(n=len(rendered_pairs))]
    parts += [
        f'### Pair {i}\nRequired field in this pair\'s verdict object: '
        f'{{"pair_id": {i}}}\n{rendered}'
        for i, rendered in enumerate(rendered_pairs)
    ]
    return "\n\n".join(parts)


class _ZeroUsable:
    """Sentinel for parsed payloads without usable pair IDs."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ZERO_USABLE"


ZERO_USABLE = _ZeroUsable()

_MAX_LOGGED_INTEGER_DIGITS = 32


def _diagnostic_pair_id(pair_id: Any) -> Any:
    """Return a safe representation of a model-supplied pair ID for logs."""
    if isinstance(pair_id, str):
        return f"<str len={len(pair_id)}>"
    if type(pair_id) is int:
        digit_count = len(str(abs(pair_id)))
        if digit_count > _MAX_LOGGED_INTEGER_DIGITS:
            return f"<int digits={digit_count}>"
        return pair_id
    if pair_id is None or isinstance(pair_id, (bool, float)):
        return pair_id
    return f"<{type(pair_id).__name__}>"


def parse_batch_verdicts(
    raw: str, valid_ids: set[int]
) -> dict[int, dict] | _ZeroUsable | None:
    """Verdicts keyed by pair_id, or a sentinel when no ID is usable."""
    try:
        data = json.loads(extract_json(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, list):
        return None
    out: dict[int, dict] = {}
    duplicate_ids: set[int] = set()
    received_ids: list[Any] = []
    discarded_ids: list[Any] = []
    for item in verdicts:
        if not isinstance(item, dict):
            marker = f"<{type(item).__name__}>"
            received_ids.append(marker)
            discarded_ids.append(marker)
            continue
        pair_id = item.get("pair_id")
        is_valid = type(pair_id) is int and pair_id in valid_ids
        received_ids.append(pair_id if is_valid else _diagnostic_pair_id(pair_id))
        if is_valid:
            if pair_id in out:
                out.pop(pair_id)
                duplicate_ids.add(pair_id)
            elif pair_id not in duplicate_ids:
                out[pair_id] = item
        else:
            discarded_ids.append(pair_id)

    expected = sorted(valid_ids)
    if valid_ids and not out:
        logger.warning(
            "batch verdict payload has no usable pair_id; expected=%s received=%r",
            expected,
            received_ids,
        )
        return ZERO_USABLE
    if discarded_ids:
        logger.warning(
            "batch verdict payload discarded unusable pair_id values; "
            "expected=%s received=%r",
            expected,
            received_ids,
        )
    if duplicate_ids:
        logger.warning(
            "batch verdict payload discarded ambiguous duplicate pair_id values; "
            "expected=%s received=%r",
            expected,
            received_ids,
        )
    return out


def judge_pairs(
    settings,
    instruction_block: str,
    pairs: list[Any],
    render_pair: Callable[[Any], str],
    judge_single: Callable[[Any], dict | None],
    k: int | None = None,
) -> list[dict | None]:
    """Judge every pair; result aligned by index. None = no verdict this run.

    *k* overrides settings.maintenance_pairs_per_call (jobs pass their per-job
    K resolved as `job_pairs_per_call or maintenance_pairs_per_call`).
    """
    k = settings.maintenance_pairs_per_call if k is None else k
    if k <= 1:
        return [judge_single(p) for p in pairs]   # legacy flow, unchanged
    results: list[dict | None] = [None] * len(pairs)
    for start in range(0, len(pairs), k):
        idx = list(range(start, min(start + k, len(pairs))))
        if not _judge_chunk(settings, instruction_block, pairs, render_pair,
                            judge_single, idx, results):
            logger.warning("LLM unavailable; leaving %d of %d pairs unjudged this run",
                           len(pairs) - start, len(pairs))
            break
    return results


def _judge_singles(pairs, judge_single, idx, results) -> bool:
    """Judge each index individually. False = LLM unavailable (abort signal)."""
    for i in idx:
        verdict = judge_single(pairs[i])
        results[i] = verdict
        if verdict is None:
            return False
    return True


def _judge_chunk(settings, instruction_block, pairs, render_pair, judge_single,
                 idx, results, zero_usable_probes: int = 1) -> bool:
    """Judge one chunk. Returns False when the LLM looks unavailable (abort signal)."""
    if len(idx) == 1:
        return _judge_singles(pairs, judge_single, idx, results)
    rendered = [render_pair(pairs[i]) for i in idx]
    prompt = build_batch_prompt(instruction_block, rendered)
    hint = settings.llm_timeout_seconds + settings.maintenance_timeout_per_pair_seconds * len(idx)
    raw = llm_generate(settings, prompt, json_mode=True, timeout_hint_seconds=hint)
    if raw is None:
        return False   # transient outage — no bisect, abort remaining work
    verdicts = parse_batch_verdicts(raw, set(range(len(idx))))

    if verdicts is ZERO_USABLE:
        if zero_usable_probes <= 0:
            logger.warning(
                "batch of %d pairs returned no usable pair_id again; "
                "judging %d pairs individually", len(idx), len(idx))
            return _judge_singles(pairs, judge_single, idx, results)
        logger.warning(
            "batch of %d pairs returned no usable pair_id; probing one bisect level",
            len(idx))
        return _bisect(settings, instruction_block, pairs, render_pair,
                       judge_single, idx, results, zero_usable_probes - 1)

    if verdicts is None:
        if zero_usable_probes <= 0:
            logger.warning(
                "batch of %d pairs returned unparseable output after the "
                "zero-usable probe budget was exhausted; judging %d pairs individually",
                len(idx), len(idx))
            return _judge_singles(pairs, judge_single, idx, results)
        logger.warning("batch of %d pairs returned unparseable output; bisecting", len(idx))
        return _bisect(settings, instruction_block, pairs, render_pair,
                       judge_single, idx, results, zero_usable_probes)
    for local_id, item in verdicts.items():
        results[idx[local_id]] = item
    if zero_usable_probes <= 0:
        missing = [idx[local_id] for local_id in range(len(idx)) if local_id not in verdicts]
        if missing:
            return _judge_singles(pairs, judge_single, missing, results)
    return True


def _bisect(settings, instruction_block, pairs, render_pair, judge_single,
            idx, results, zero_usable_probes) -> bool:
    """Split the chunk in half and judge each side, propagating the abort signal."""
    mid = len(idx) // 2
    if not _judge_chunk(settings, instruction_block, pairs, render_pair,
                        judge_single, idx[:mid], results, zero_usable_probes):
        return False
    return _judge_chunk(settings, instruction_block, pairs, render_pair,
                        judge_single, idx[mid:], results, zero_usable_probes)

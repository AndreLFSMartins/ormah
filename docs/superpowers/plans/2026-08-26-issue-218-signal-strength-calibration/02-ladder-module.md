### Task 2: The ladder module

**Files:**
- Create: `src/ormah/signal_strength.py`
- Test: `tests/test_engine/test_signal_strength.py`

**Interfaces:**
- Consumes: nothing (leaf module — imports only `json` and `math`)
- Produces, relied on by Tasks 3–6:
  - `HEURISTIC_SOURCE: str`, `LLM_JUDGE_SOURCE: str`
  - `EXPLICIT`, `VERBATIM_NODE_ID`, `VERBATIM_TITLE`, `VERBATIM_SENTENCE`, `JUDGE_LO`, `JUDGE_HI`,
    `IMPLICIT`, `OVERLAP_GATE`, `OVERLAP_FLOOR`, `OVERLAP_SPAN`, `OVERLAP_K`, `UNKNOWN` — all `float`
  - `BANDS: tuple[tuple[str, float, float], ...]`
  - `token_overlap_strength(ratio: float) -> float`
  - `judge_strength(confidence: float, min_confidence: float, polarity: int) -> float`
  - `feedback_strength(source: str, signal: int) -> float`
  - `strength_from_evidence(source: str, polarity: int, evidence_json: str | None) -> float`

No caller changes in this task. The module ships with tests and nothing importing it yet.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_signal_strength.py`:

```python
"""Unit tests for the #218 ordinal evidence ladder."""

import json

import pytest

from ormah import signal_strength as ss


def test_bands_are_disjoint_and_ordered():
    """The ladder's central assertion: channel dominates within-channel confidence."""
    ordered = sorted(ss.BANDS, key=lambda band: -band[1])
    assert [band[0] for band in ordered] == [
        "explicit",
        "node_id",
        "title",
        "sentence",
        "auto_llm_judge",
        "implicit",
        "token_overlap",
    ]
    for (upper, upper_lo, _), (lower, _, lower_hi) in zip(ordered, ordered[1:]):
        assert lower_hi < upper_lo, f"{lower} band overlaps {upper}"


def test_token_overlap_starts_at_the_band_floor():
    assert ss.token_overlap_strength(ss.OVERLAP_GATE) == pytest.approx(ss.OVERLAP_FLOOR)


def test_token_overlap_separates_the_observed_domain():
    """0.5..7.583 is the range measured on a live store; no two ratios may tie."""
    values = [ss.token_overlap_strength(r) for r in (0.5, 0.55, 1.167, 1.5, 3.0, 7.583)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert values[-1] < ss.IMPLICIT


def test_token_overlap_fixes_the_defect_218_names():
    """Today min(0.85, 0.45 + ratio) returns exactly 0.85 for both of these."""
    assert ss.token_overlap_strength(0.5) != ss.token_overlap_strength(1.8)


def test_token_overlap_never_exceeds_its_band():
    """The supremum is strict in exact arithmetic, not in float64.

    float64 reaches it around ratio 37 — five times above the 7.583 maximum observed
    on a live store. That crossover is libm-dependent, so it is documented here and
    not asserted; what is asserted is that the band is never exceeded.
    """
    supremum = ss.OVERLAP_FLOOR + ss.OVERLAP_SPAN
    assert all(ss.token_overlap_strength(n / 10) <= supremum for n in range(5, 1000))
    assert supremum < ss.IMPLICIT


@pytest.mark.parametrize("min_confidence", [0.75, 0.80])
def test_judge_band_is_affine_over_the_callers_min_confidence(min_confidence):
    assert ss.judge_strength(min_confidence, min_confidence, 1) == pytest.approx(ss.JUDGE_LO)
    assert ss.judge_strength(1.0, min_confidence, 1) == pytest.approx(ss.JUDGE_HI)
    midpoint = (min_confidence + 1.0) / 2
    assert ss.judge_strength(midpoint, min_confidence, 1) == pytest.approx(
        (ss.JUDGE_LO + ss.JUDGE_HI) / 2
    )


def test_judge_zero_polarity_carries_no_strength():
    """An uncertain verdict asserts nothing. Its confidence survives in evidence."""
    assert ss.judge_strength(0.35, 0.75, 0) == 0.0
    assert ss.judge_strength(0.99, 0.75, 0) == 0.0


def test_judge_negative_polarity_uses_the_same_band():
    """A confident 'irrelevant' is strong evidence for its own polarity."""
    assert ss.judge_strength(1.0, 0.75, -1) == pytest.approx(ss.JUDGE_HI)


def test_judge_degenerate_min_confidence_does_not_divide_by_zero():
    assert ss.judge_strength(1.0, 1.0, 1) == ss.JUDGE_HI


def test_explicit_and_implicit_no_longer_share_a_strength():
    """Today submit_feedback hardcodes 1.0 for both."""
    assert ss.feedback_strength("explicit", 1) == ss.EXPLICIT
    assert ss.feedback_strength("implicit", 1) == ss.IMPLICIT
    assert ss.feedback_strength("explicit", 1) != ss.feedback_strength("implicit", 1)


def test_feedback_zero_signal_carries_no_strength():
    """Unreachable through the HTTP surface; reachable from a direct Python caller."""
    assert ss.feedback_strength("explicit", 0) == 0.0


def test_unknown_source_fails_closed_to_the_bottom_rung():
    assert ss.feedback_strength("something_new", 1) == ss.UNKNOWN
    assert ss.feedback_strength("auto_heuristic", -1) == ss.UNKNOWN


@pytest.mark.parametrize(
    "match,expected",
    [
        ("node_id", ss.VERBATIM_NODE_ID),
        ("title", ss.VERBATIM_TITLE),
        ("sentence", ss.VERBATIM_SENTENCE),
    ],
)
def test_recompute_reads_the_heuristic_match_kind(match, expected):
    evidence = json.dumps({"match": match})
    assert ss.strength_from_evidence(ss.HEURISTIC_SOURCE, 1, evidence) == expected


def test_recompute_reads_the_overlap_ratio():
    evidence = json.dumps({"match": "token_overlap", "overlap_ratio": 1.167})
    assert ss.strength_from_evidence(ss.HEURISTIC_SOURCE, 1, evidence) == pytest.approx(
        ss.token_overlap_strength(1.167)
    )


def test_recompute_uses_the_rows_own_min_confidence():
    """Not today's setting: the judge stamps min_confidence on every row it writes."""
    lenient = json.dumps({"confidence": 0.80, "min_confidence": 0.75})
    strict = json.dumps({"confidence": 0.80, "min_confidence": 0.80})
    assert ss.strength_from_evidence(
        ss.LLM_JUDGE_SOURCE, 1, lenient
    ) > ss.strength_from_evidence(ss.LLM_JUDGE_SOURCE, 1, strict)


def test_recompute_survives_malformed_evidence():
    assert ss.strength_from_evidence(ss.HEURISTIC_SOURCE, 1, "not json") == ss.UNKNOWN
    assert ss.strength_from_evidence(ss.HEURISTIC_SOURCE, 1, None) == ss.UNKNOWN
    assert ss.strength_from_evidence("implicit", 0, None) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_signal_strength.py -q > /tmp/218-t2-red.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t2-red.txt
tail -5 /tmp/218-t2-red.txt
```

Expected: collection error — `ModuleNotFoundError: No module named 'ormah.signal_strength'`.

- [ ] **Step 3: Write the module**

Create `src/ormah/signal_strength.py`:

```python
"""The ordinal evidence-strength ladder behind ``signals.strength`` (issue #218).

``strength`` is the strength of the evidence backing a signal row's polarity, on a
single ordinal scale, comparable in RANK across channels. It is NOT a calibrated
probability: 0.86 from the LLM judge and 0.86 from anywhere else mean "the same
rung", not "the same likelihood".

The load-bearing assertion is that the CHANNEL DOMINATES within-channel confidence.
A verbatim match outranks any LLM judgment however confident; an LLM judgment
outranks any agent self-report. Bands are therefore disjoint per channel, and native
confidence modulates only WITHIN a band.

    1.00         explicit ......... the user was actually asked
    0.98         node_id .......... the short id was printed verbatim
    0.94         title ............ the title was printed verbatim
    0.92         sentence ......... a content sentence was printed verbatim
    0.82 - 0.90  auto_llm_judge ... affine over [min_confidence, 1.0]
    0.80         implicit ......... the agent's own self-assessment
    0.40 - 0.78  token_overlap .... asymptotic in overlap_ratio
    0.00         polarity == 0 .... a row that asserts nothing has no evidence

A polarity-zero row asserts nothing, so it carries no evidence strength. Its native
confidence still survives in ``signals.evidence``; nothing is lost.
"""

from __future__ import annotations

import json
import math

# Detector source labels. Owned here because this module maps them onto the ladder;
# session_watcher imports them rather than repeating the literals.
HEURISTIC_SOURCE = "transcript_watcher_heuristic"
LLM_JUDGE_SOURCE = "transcript_watcher_llm_judge"

EXPLICIT = 1.00
VERBATIM_NODE_ID = 0.98
VERBATIM_TITLE = 0.94
VERBATIM_SENTENCE = 0.92
JUDGE_LO = 0.82
JUDGE_HI = 0.90
IMPLICIT = 0.80

# token_overlap: floored at the detector's own entry gate, asymptotic to FLOOR + SPAN.
OVERLAP_GATE = 0.5
OVERLAP_FLOOR = 0.40
OVERLAP_SPAN = 0.38
OVERLAP_K = 1.0

# Bottom of the ladder. Unknown provenance is the weakest evidence there is.
UNKNOWN = OVERLAP_FLOOR

# (channel, band_low, band_high). Disjointness is the executable form of the
# "channel dominates confidence" assertion; test_signal_strength.py pins it.
BANDS = (
    ("explicit", EXPLICIT, EXPLICIT),
    ("node_id", VERBATIM_NODE_ID, VERBATIM_NODE_ID),
    ("title", VERBATIM_TITLE, VERBATIM_TITLE),
    ("sentence", VERBATIM_SENTENCE, VERBATIM_SENTENCE),
    ("auto_llm_judge", JUDGE_LO, JUDGE_HI),
    ("implicit", IMPLICIT, IMPLICIT),
    ("token_overlap", OVERLAP_FLOOR, OVERLAP_FLOOR + OVERLAP_SPAN),
)

_FEEDBACK_LADDER = {
    "explicit": EXPLICIT,
    "implicit": IMPLICIT,
    # submit_feedback carries no confidence, so a judge-sourced row arriving through
    # it lands on the floor of the judge band rather than anywhere inside it.
    "auto_llm_judge": JUDGE_LO,
    "auto_heuristic": UNKNOWN,
}


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def token_overlap_strength(ratio: float) -> float:
    """Map ``overlap_ratio`` onto the token_overlap band.

    Asymptotic rather than clamped, because ``overlap_ratio`` is unbounded above --
    its denominator is ``min(len(candidate_tokens), 12)`` while its numerator is not
    capped. Any clamp ties every row above it, recreating the exact saturation defect
    #218 reports; a clamp at 1.50 would tie 38% of the rows observed on a live store.

    The supremum FLOOR + SPAN = 0.78 is strict in exact arithmetic but not in float64,
    which reaches it around ratio 37 -- five times the 7.583 maximum observed.
    """
    return OVERLAP_FLOOR + OVERLAP_SPAN * (
        1.0 - math.exp(-OVERLAP_K * max(ratio - OVERLAP_GATE, 0.0))
    )


def judge_strength(confidence: float, min_confidence: float, polarity: int) -> float:
    """Map the judge's confidence onto its band, affine over [min_confidence, 1.0].

    The domain is anchored on the caller's ``min_confidence`` rather than the literal
    0.75, so the band re-anchors if the setting moves. That domain is sound because
    the judge assigns a non-zero polarity only when ``confidence >= min_confidence``,
    so no scoring row can sit below the band floor.
    """
    if polarity == 0:
        return 0.0
    if min_confidence >= 1.0:
        return JUDGE_HI
    span = (confidence - min_confidence) / (1.0 - min_confidence)
    return JUDGE_LO + (JUDGE_HI - JUDGE_LO) * max(0.0, min(1.0, span))


def feedback_strength(source: str, signal: int) -> float:
    """Map a ``submit_feedback`` row onto the ladder.

    Fail-closed: a source the ladder does not know lands on ``UNKNOWN``, the bottom
    rung. ``submit_feedback`` validates ``signal`` only at its HTTP boundary
    (``FeedbackRequest``), so a direct Python caller can still arrive here with 0.
    """
    if signal == 0:
        return 0.0
    return _FEEDBACK_LADDER.get(source, UNKNOWN)


def strength_from_evidence(source: str, polarity: int, evidence_json: str | None) -> float:
    """Recompute a stored row's strength from the ``evidence`` it already carries.

    Used by the #218 backfill, and exact rather than estimated: each channel records
    what its own mapping needs, and the judge stamps the ``min_confidence`` in force
    when the row was written -- so the recompute uses that value, not today's.
    """
    if polarity == 0:
        return 0.0
    try:
        evidence = json.loads(evidence_json) if evidence_json else {}
    except (TypeError, ValueError):
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}

    if source == HEURISTIC_SOURCE:
        match = evidence.get("match")
        if match == "node_id":
            return VERBATIM_NODE_ID
        if match == "title":
            return VERBATIM_TITLE
        if match == "sentence":
            return VERBATIM_SENTENCE
        if match == "token_overlap":
            return token_overlap_strength(_as_float(evidence.get("overlap_ratio")))
        return UNKNOWN
    if source == LLM_JUDGE_SOURCE:
        return judge_strength(
            _as_float(evidence.get("confidence")),
            _as_float(evidence.get("min_confidence"), default=0.75),
            polarity,
        )
    return feedback_strength(source, polarity)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_signal_strength.py -q > /tmp/218-t2-green.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-t2-green.txt
tail -5 /tmp/218-t2-green.txt
```

Expected: `PYTEST_EXIT=0`, 19 passed.

- [ ] **Step 5: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
git add src/ormah/signal_strength.py tests/test_engine/test_signal_strength.py
git commit -m "feat(signals): add the ordinal evidence-strength ladder (#218)

signals.strength is a tier label stored as a float: submit_feedback hardcodes
1.0, three heuristic match kinds return constants, and token_overlap saturates
before its own entry gate can admit it.

This adds the ladder as a leaf module with no callers yet. strength becomes the
strength of the evidence backing a row's polarity, on one ordinal scale where
the channel dominates within-channel confidence, with disjoint per-channel bands.

token_overlap gets an asymptotic curve rather than a wider clamp: overlap_ratio
is unbounded above, so every clamp recreates the saturation defect.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

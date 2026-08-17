"""Unit tests for the centralized lifecycle math (#221)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from ormah import lifecycle

# The policy constants from #191. Kept literal here on purpose: these tests pin
# the curve itself, not whatever config happens to hold.
G = 0.5
W = 0.5
CAP = 2.0
MAX_S = 365.0
INITIAL_S = 1.0


def _reinforce(stability: float, days_since: float) -> float:
    return lifecycle.reinforced_stability(
        stability,
        days_since,
        growth_factor=G,
        growth_exponent=W,
        spacing_cap=CAP,
        max_stability=MAX_S,
        initial_stability=INITIAL_S,
    )


def test_retrievability_matches_the_exponential_curve():
    assert lifecycle.retrievability(0.0, 1.0) == pytest.approx(1.0)
    assert lifecycle.retrievability(1.0, 1.0) == pytest.approx(math.exp(-1.0))
    assert lifecycle.retrievability(7.0, 14.0) == pytest.approx(math.exp(-0.5))


def test_retrievability_never_exceeds_one():
    for days, stab in [(0.0, 1.0), (0.5, 100.0), (30.0, 365.0)]:
        assert lifecycle.retrievability(days, stab) <= 1.0


def test_retrievability_survives_zero_stability():
    """Node.stability is Field(ge=0.0), so 0 is representable and exp(-t/0) raises."""
    assert lifecycle.retrievability(5.0, 0.0, fallback_stability=2.0) == pytest.approx(
        math.exp(-2.5)
    )


def test_stability_one_reinforced_after_thirty_days_reaches_exactly_two():
    """AC1: the headline case from the issue. Unbounded, this jumped 1 -> 202.7."""
    assert _reinforce(1.0, 30.0) == 2.0


def test_spacing_stays_finite_for_an_extremely_old_node():
    """AC2: R underflows to 0.0 past t/S ~745 and 0.0 ** -0.2 raises ZeroDivisionError."""
    assert lifecycle.retrievability(10_000.0, 0.5) == 0.0  # the underflow is real
    assert lifecycle.spacing_factor(10_000.0, 0.5, CAP) == CAP
    assert _reinforce(0.5, 10_000.0) == pytest.approx(1.21)


def test_spacing_is_capped_and_monotonic():
    assert lifecycle.spacing_factor(0.0, 1.0, CAP) == pytest.approx(1.0)
    assert lifecycle.spacing_factor(1.0, 1.0, CAP) == pytest.approx(math.exp(0.2))
    assert lifecycle.spacing_factor(100.0, 1.0, CAP) == CAP


def test_growth_diminishes_as_stability_rises():
    """AC3: exactly 74 closely spaced updates from S=1 to the 365 cap.

    "Diminishing" means the *relative* step S'/S, not the absolute increment:
    the increment is ``g * sqrt(S) * spacing``, which grows with S. The ratio
    ``1 + g * S^-w * spacing`` is what falls, from 1.61 toward 1.0.
    """
    stability = 1.0
    ratios = []
    steps = 0
    while stability < MAX_S and steps < 1000:
        new_stability = _reinforce(stability, 1.0)
        ratios.append(new_stability / stability)
        stability = new_stability
        steps += 1

    assert steps == 74
    assert stability == MAX_S
    assert ratios[0] == pytest.approx(1.61)
    for earlier, later in zip(ratios, ratios[1:]):
        assert later < earlier


def test_reinforced_stability_never_exceeds_the_cap():
    assert _reinforce(364.9, 30.0) == MAX_S


def test_reinforced_stability_falls_back_when_stability_is_zero():
    assert _reinforce(0.0, 0.0) == pytest.approx(1.5)


def test_reinforcement_is_due_when_a_node_was_never_reviewed():
    now = datetime.now(timezone.utc)
    assert lifecycle.reinforcement_due(None, now, 1.0) is True


def test_reinforcement_is_not_due_inside_the_cooldown_window():
    now = datetime.now(timezone.utc)
    assert lifecycle.reinforcement_due(now - timedelta(hours=6), now, 1.0) is False


def test_reinforcement_is_due_once_the_cooldown_elapses():
    now = datetime.now(timezone.utc)
    assert lifecycle.reinforcement_due(now - timedelta(days=1), now, 1.0) is True


def test_a_zero_cooldown_always_allows_reinforcement():
    now = datetime.now(timezone.utc)
    assert lifecycle.reinforcement_due(now, now, 0.0) is True

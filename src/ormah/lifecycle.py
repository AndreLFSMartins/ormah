"""The single definition of Ormah's memory-lifecycle math.

Every numeric rule about retrievability, spacing, and reinforcement lives here,
so the engine and the background jobs share one curve rather than each carrying
a copy that can drift. Changing how memory decays or strengthens means editing
this module and nothing else.

Pure functions only: no I/O, no settings object, no database. Callers own the
state and pass the knobs in, which keeps the curve independently testable and
free of any caller's lifecycle.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

# Shape of the spacing curve, fixed by #191. Deliberately not configurable — the
# knobs are the bounds around it (spacing cap, growth factor/exponent).
_SPACING_EXPONENT = 0.2


def retrievability(
    days_since: float, stability: float, *, fallback_stability: float = 1.0
) -> float:
    """``R = exp(-t / S)`` — the probability the memory is still retrievable.

    ``Node.stability`` is ``Field(ge=0.0)``, so ``S = 0`` is a representable value
    that would make the exponent infinite; it falls back to *fallback_stability*.
    """
    effective_stability = stability if stability else fallback_stability
    return math.exp(-max(days_since, 0.0) / effective_stability)


def spacing_factor(
    days_since: float, stability: float, cap: float, *, fallback_stability: float = 1.0
) -> float:
    """``min(R^-0.2, cap)``, computed without ever materializing ``R``.

    ``R`` underflows to ``0.0`` once ``t / S`` passes ~745, and ``0.0 ** -0.2``
    raises ``ZeroDivisionError``. Since ``R^-0.2 == exp(0.2 * t / S)``, working on
    the exponent keeps the result finite at any age, and returning the cap as soon
    as the exponent reaches ``log(cap)`` keeps ``exp`` away from its own overflow.
    """
    effective_stability = stability if stability else fallback_stability
    exponent = _SPACING_EXPONENT * max(days_since, 0.0) / effective_stability
    if exponent >= math.log(cap):
        return cap
    return min(math.exp(exponent), cap)


def reinforced_stability(
    stability: float,
    days_since: float,
    *,
    growth_factor: float,
    growth_exponent: float,
    spacing_cap: float,
    max_stability: float,
    initial_stability: float,
) -> float:
    """``S' = min(S * (1 + g * S^-w * spacing), max_stability)``.

    Bounded and diminishing: the ``S^-w`` term shrinks each step as stability
    rises, and the capped spacing factor stops a single very old node from
    reaching the ceiling in one use.
    """
    effective_stability = stability if stability else initial_stability
    spacing = spacing_factor(
        days_since,
        effective_stability,
        spacing_cap,
        fallback_stability=initial_stability,
    )
    grown = effective_stability * (
        1 + growth_factor * effective_stability**-growth_exponent * spacing
    )
    return round(min(grown, max_stability), 2)


def reinforcement_due(
    last_review: datetime | None, now: datetime, cooldown_days: float
) -> bool:
    """True when a node's numeric stability update is off cooldown.

    ``last_review`` tracks the last numeric update, which is distinct from
    ``last_accessed``: use advances the decay anchor on every event, while the
    stability number moves at most once per cooldown window.
    """
    if last_review is None:
        return True
    return (now - last_review) >= timedelta(days=cooldown_days)


def promotion_floor(stability: float, initial_stability: float) -> float:
    """``max(S, initial)`` — the lease a promoted node restarts from.

    ``max``, never a sum: a node promoted twice in one cooldown window must end
    at one initial lease, not two, and a node whose stability already exceeds the
    initial value must not be pulled down to it.
    """
    return max(stability, initial_stability)

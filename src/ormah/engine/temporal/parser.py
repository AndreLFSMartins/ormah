"""The language-agnostic temporal parser.

Owns every rule that is not language-specific — leftmost match selection, window
arithmetic, the canonical unit->days map, the rolling previous-period rule and
the default window — and asks the enabled packs what a phrase means instead of
holding the phrases itself.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from ormah.engine.temporal.locale import StaticPhrase, TemporalLocale

_UNIT_TO_DAYS: dict[str, float] = {"hour": 1 / 24, "day": 1, "week": 7, "month": 30}

_DEFAULT_TEMPORAL_DAYS = 3


class TemporalParser:
    """Resolves a prompt into a recall window and a topical residue."""

    def __init__(self, locales: Sequence[TemporalLocale]) -> None:
        self._locales = tuple(locales)

    def has_temporal_phrases(self, prompt: str) -> bool:
        """Whether *prompt* carries an explicit time reference.

        Derived from the windowed entries plus the numeric patterns only, never
        from the strip list: a strip-only phrase is removed from the query and
        stays invisible here, so it never starts date-filtering a recall.
        """
        return self._leftmost(prompt) is not None

    def extract_time_params(self, prompt: str) -> dict:
        """Return the ``created_after``/``created_before`` window for *prompt*."""
        now = datetime.now(timezone.utc)

        found = self._leftmost(prompt)
        if found is None:
            return _window(now, _DEFAULT_TEMPORAL_DAYS, 0)

        locale, match, phrase = found
        if phrase is not None:
            days_start, days_end = phrase.window
            return _window(now, days_start, days_end or 0)

        count = int(match.group(1))
        # Lowercase before dropping the plural so an uppercased unit still
        # normalises ("DIAS" -> "dias" -> "dia"), then fold the pack's unit
        # word onto the canonical English key this map is written in.
        unit = match.group(2).lower().rstrip("s")
        unit = locale.unit_aliases.get(unit, unit)
        days = count * _UNIT_TO_DAYS.get(unit, 1)

        # Rolling previous-period for weeks/months with N > 1: "last 2
        # weeks" is 4 weeks ago -> 2 weeks ago. Days and hours extend to now.
        if unit in ("week", "month") and count > 1:
            return _window(now, days * 2, days)
        return _window(now, days, 0)

    def _leftmost(
        self, prompt: str
    ) -> tuple[TemporalLocale, re.Match, StaticPhrase | None] | None:
        """The windowed or numeric match that starts earliest in *prompt*.

        A tie at the same offset goes to the longest match, then to pack order,
        then to declaration order — the order of this scan, kept by the strict
        ``<``. The phrase is ``None`` for a numeric match.
        """
        best = None
        best_key = None
        for locale in self._locales:
            candidates = [(p.pattern, p) for p in locale.windowed_phrases]
            if locale.numeric_pattern is not None:
                candidates.append((locale.numeric_pattern, None))
            for pattern, phrase in candidates:
                match = pattern.search(prompt)
                if match is None:
                    continue
                key = (match.start(), match.start() - match.end())
                if best_key is None or key < best_key:
                    best, best_key = (locale, match, phrase), key
        return best

    def strip_temporal_phrases(self, prompt: str) -> str:
        """Remove every enabled pack's temporal phrases, returning the topical residue.

        Each pattern runs over the residue the previous one left, in pack and
        declaration order, so overlapping phrases ("nesta semana passada",
        "semana passada", "esta semana") never cut into each other's text.
        """
        residue = prompt
        for locale in self._locales:
            for pattern in locale.strip_patterns:
                residue = pattern.sub("", residue)
        return re.sub(r"\s{2,}", " ", residue).strip()


def _window(now: datetime, days_start: float, days_end: float) -> dict:
    return {
        "created_after": (now - timedelta(days=days_start)).isoformat(),
        "created_before": (now - timedelta(days=days_end)).isoformat(),
    }

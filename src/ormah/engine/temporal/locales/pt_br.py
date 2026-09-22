"""The built-in Brazilian Portuguese temporal locale pack."""

from __future__ import annotations

import re

from ormah.engine.temporal.locale import StaticPhrase, TemporalLocale

# The leading contraction a phrase removes along with itself: "na semana
# passada", "dos últimos 3 meses". Optional, so the bare phrase still matches.
_PREP = r"(?:\b(?:na|no|nos|nas|da|do|dos|das|em)\s+)?"


def _phrase(body: str) -> re.Pattern:
    return re.compile(f"{_PREP}(?:{body})", re.IGNORECASE)


def _bare(body: str) -> re.Pattern:
    return re.compile(body, re.IGNORECASE)


LOCALE = TemporalLocale(
    code="pt-BR",
    static_phrases=(
        StaticPhrase(pattern=_bare(r"\bhoje\b"), window=(1, None)),  # 24h atrás -> agora
        StaticPhrase(pattern=_bare(r"\bontem\b"), window=(2, 1)),  # 48h atrás -> 24h atrás
        # "esta/nesta semana passada" means last week. Declared before the two
        # phrases it overlaps, so the strip removes it whole; the longest-match
        # tie-break makes it beat "esta/nesta semana" for the window.
        StaticPhrase(
            pattern=_bare(r"\b(?:esta|essa|nesta|nessa)\s+semana\s+passada\b"), window=(14, 7)
        ),
        StaticPhrase(pattern=_phrase(r"\bsemana\s+passada\b"), window=(14, 7)),
        StaticPhrase(pattern=_bare(r"\b(?:esta|essa|nesta|nessa)\s+semana\b"), window=(7, None)),
        StaticPhrase(pattern=_phrase(r"\bm[êe]s\s+passado\b"), window=(60, 30)),
        StaticPhrase(pattern=_bare(r"\brecentemente\b|\bultimamente\b"), window=(3, None)),
    ),
    # Only this language's determiner and units: a pattern shared with the en
    # pack would make both packs claim every numeric match. "meses" is listed
    # before "m[êe]s" so the plural matches whole.
    numeric_pattern=_phrase(
        r"\b(?:[úu]ltim[oa]s?)\s+(\d+)\s+(horas?|dias?|semanas?|meses|m[êe]s)\b"
    ),
    # Applied by the parser after lowercasing and dropping the plural "s".
    # Without these the canonical unit->days map falls back to 1 day, so
    # "últimas 2 semanas" would mean 2 days and the rolling-window branch
    # (which tests for "week"/"month") would never fire.
    unit_aliases={
        "hora": "hour",
        "dia": "day",
        "semana": "week",
        "mese": "month",  # "meses" -> "mese"
        "mê": "month",  # "mês" -> "mê"
        "me": "month",  # "mes" -> "me"
    },
)

"""The built-in English temporal locale pack."""

from __future__ import annotations

import re

from ormah.engine.temporal.locale import StaticPhrase, TemporalLocale

# The leading preposition a phrase removes along with itself: "in the last 3
# days", "from yesterday". Optional, so the bare phrase still matches.
_PREP = r"(?:\b(?:in|during|from|over|for)\s+(?:the\s+)?)?"


def _phrase(body: str) -> re.Pattern:
    return re.compile(f"{_PREP}(?:{body})", re.IGNORECASE)


LOCALE = TemporalLocale(
    code="en",
    static_phrases=(
        StaticPhrase(pattern=_phrase(r"\btoday\b"), window=(1, None)),  # 24h ago -> now
        StaticPhrase(pattern=_phrase(r"\byesterday\b"), window=(2, 1)),  # 48h ago -> 24h ago
        StaticPhrase(pattern=_phrase(r"\blast\s+week\b"), window=(14, 7)),  # 14d ago -> 7d ago
        StaticPhrase(pattern=_phrase(r"\bthis\s+week\b"), window=(7, None)),  # 7d ago -> now
        StaticPhrase(pattern=_phrase(r"\blast\s+month\b"), window=(60, 30)),  # 60d -> 30d ago
        StaticPhrase(pattern=_phrase(r"\brecently\b|\blately\b"), window=(3, None)),  # 3d -> now
        # Strip-only: removed from the query, but never selects a window and
        # never makes temporal detection true. It keeps its preposition, since
        # "in the recent logs" is not a time reference.
        StaticPhrase(pattern=re.compile(r"\brecent\b", re.IGNORECASE)),
    ),
    numeric_pattern=_phrase(r"\b(?:last|past)\s+(\d+)\s+(hours?|days?|weeks?|months?)\b"),
    # English units are already the canonical keys.
    unit_aliases={},
)

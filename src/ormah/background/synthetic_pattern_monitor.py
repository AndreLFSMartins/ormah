"""Detect synthetic-prompt patterns that stopped matching (#143).

The #134 filter's pattern list rots two ways: Claude Code renames a marker, or
the operator's tooling changes. Neither leaves a trace — the filter keeps
running and simply matches nothing. This module turns that silence into a
signal by asking, per pattern, when it last fired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from ormah.engine.prompt_classifier import _SYNTHETIC_PATTERNS

BUILTIN = "builtin"
OPERATOR = "operator"


@dataclass(frozen=True)
class RottedPattern:
    """A live pattern that matched before and has now gone quiet."""

    pattern: str
    origin: str  # BUILTIN | OPERATOR — decides the proposal text, not the mechanics
    last_seen: str  # ISO-8601, from whisper_decisions.logged_at


def live_patterns(settings) -> list[tuple[str, str]]:
    """(pattern_source, origin) for every pattern the filter would apply today.

    Sourced from the live config, never from history: a pattern the user already
    removed from .env is not actionable and must not be proposed.

    Deduplicated by pattern string, OPERATOR winning: an operator who copies a
    builtin regex into .env would otherwise yield two entries for one regex, two
    different proposal texts, and therefore two proposals the dedup cannot
    collapse (council I1). OPERATOR wins because that is the copy the user can
    actually act on.
    """
    merged: dict[str, str] = {compiled.pattern: BUILTIN for compiled in _SYNTHETIC_PATTERNS}
    for raw in settings.whisper_synthetic_prompt_patterns or ():
        merged[raw] = OPERATOR
    return list(merged.items())


def find_rotted_patterns(
    conn: sqlite3.Connection,
    settings,
    now: datetime,
) -> list[RottedPattern]:
    """Live patterns whose last match predates the rot window. Pure read.

    Rot is "matched before and stopped" — not "matches zero". A pattern that
    never matched is irrelevant to this install (no scheduled tasks, say), and
    proposing its removal would be noise the user learns to ignore.
    """
    # With the filter off, NOTHING writes silent_synthetic, so every last_seen
    # freezes while ordinary human traffic keeps the vacation guard satisfied —
    # every pattern would age into a false proposal claiming an upstream rename
    # that never happened, and the user might delete a still-valid filter
    # (council C1). No filter, no signal, no opinion.
    if not settings.whisper_synthetic_filter_enabled:
        return []

    cutoff = (now - timedelta(days=settings.whisper_pattern_rot_days)).isoformat()

    # Vacation guard: with no traffic at all, every pattern looks rotted.
    if conn.execute(
        "SELECT 1 FROM whisper_decisions WHERE logged_at > ? LIMIT 1", (cutoff,)
    ).fetchone() is None:
        return []

    history = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT matched_pattern, MAX(logged_at), COUNT(*) FROM whisper_decisions "
            "WHERE outcome = 'silent_synthetic' AND matched_pattern IS NOT NULL "
            "GROUP BY matched_pattern"
        ).fetchall()
    }

    rotted = []
    for pattern, origin in live_patterns(settings):
        entry = history.get(pattern)
        if entry is None:
            continue  # never matched — irrelevant to this install, not rot
        seen, hits = entry
        if seen > cutoff:
            continue  # still firing
        if hits < settings.whisper_pattern_rot_min_matches:
            continue  # fired once in passing; not evidence of a live workflow
        rotted.append(RottedPattern(pattern=pattern, origin=origin, last_seen=seen))
    return rotted

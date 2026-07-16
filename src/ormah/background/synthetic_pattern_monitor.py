"""Detect synthetic-prompt patterns that stopped matching (#143).

The #134 filter's pattern list rots two ways: Claude Code renames a marker, or
the operator's tooling changes. Neither leaves a trace — the filter keeps
running and simply matches nothing. This module turns that silence into a
signal by asking, per pattern, when it last fired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import sqlite3
import uuid

from ormah.engine.prompt_classifier import _SYNTHETIC_PATTERNS
from ormah.models.proposals import ProposalType

logger = logging.getLogger(__name__)

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


_MANUAL = "MANUAL ACTION REQUIRED — "


def _proposed_action(rotted: RottedPattern) -> str:
    """Stable text derived ONLY from the pattern — this string is the dedup key.

    Never interpolate a count or a date here. It would change every run, the
    dedup in run_synthetic_pattern_monitor would never hit, and the job would
    file one proposal per day forever. Variable evidence belongs in `reason`.

    The MANUAL ACTION REQUIRED prefix is load-bearing: approving a proposal of
    this type executes nothing (auto-applying config is deliberately out of
    scope), yet the shared proposals surface still reports success and drops the
    item from the queue. Without this prefix a user can approve and reasonably
    believe the repair happened (council I3).
    """
    if rotted.origin == OPERATOR:
        return (
            f"{_MANUAL}remove this entry from ORMAH_WHISPER_SYNTHETIC_PROMPT_PATTERNS "
            f"in your .env: {rotted.pattern}"
        )
    return (
        f"{_MANUAL}Claude Code marker {rotted.pattern} stopped appearing; it was "
        "likely renamed upstream. Report it — this is a built-in default and is "
        "not in your .env, so there is nothing for you to edit."
    )


def run_synthetic_pattern_monitor(
    engine,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Propose corrections for synthetic patterns that went quiet (#143).

    Proposes, never applies: a wrongly-silenced prompt fails invisibly, so the
    human stays in the loop. Approving does nothing by design — the user copies
    the rendered line into their own .env.
    """
    now = now or datetime.now(timezone.utc)
    settings = engine.settings
    rotted = find_rotted_patterns(engine.db.conn, settings, now)

    created = 0
    for entry in rotted:
        action = _proposed_action(entry)
        # Any status, not just pending: a rejected proposal must stay dead, and a
        # rotted pattern the user already saw must not be re-filed every night.
        #
        # `created > last_seen` is what keeps that from being permanent (council
        # I2): a proposal filed BEFORE the pattern's last match is about an
        # episode that has since ended, so it no longer blocks. A pattern that
        # rots, gets repaired, resumes matching and rots again therefore gets a
        # fresh proposal, while the ordinary "still dead" case stays deduped.
        existing = engine.db.conn.execute(
            "SELECT 1 FROM proposals WHERE type = ? AND proposed_action = ? "
            "AND created > ? LIMIT 1",
            (ProposalType.pattern.value, action, entry.last_seen),
        ).fetchone()
        if existing is not None:
            continue
        reason = (
            f"Last matched {entry.last_seen}, more than "
            f"{settings.whisper_pattern_rot_days} days ago, while whisper traffic "
            f"continued. Origin: {entry.origin}."
        )
        with engine.db.transaction() as conn:
            conn.execute(
                "INSERT INTO proposals (id, type, status, source_nodes, "
                "proposed_action, reason, created) "
                "VALUES (?, ?, 'pending', '[]', ?, ?, ?)",
                (str(uuid.uuid4()), ProposalType.pattern.value, action, reason,
                 now.isoformat()),
            )
        created += 1

    if created:
        logger.info("synthetic_pattern_monitor: filed %d pattern proposal(s)", created)
    return {"rotted": len(rotted), "proposals_created": created}

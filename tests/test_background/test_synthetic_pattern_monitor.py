"""Rot detection for the synthetic-prompt pattern list (#143)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ormah.background.synthetic_pattern_monitor import (
    BUILTIN,
    OPERATOR,
    find_rotted_patterns,
    live_patterns,
)

NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
TASK_NOTIFICATION = r"<task-notification>"


def _decision(engine, *, outcome, matched_pattern, logged_at):
    """Insert one whisper_decisions row directly — this is the job's only input."""
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO whisper_decisions (session_id, space, prompt_hash, intent, "
            "outcome, logged_at, matched_pattern) VALUES (?, NULL, 'h', NULL, ?, ?, ?)",
            ("s", outcome, logged_at.isoformat(), matched_pattern),
        )


def test_live_patterns_includes_builtins_and_operator_entries(engine):
    engine.settings.whisper_synthetic_prompt_patterns = [r"BATCH JOB"]
    live = live_patterns(engine.settings)

    assert (TASK_NOTIFICATION, BUILTIN) in live
    assert (r"BATCH JOB", OPERATOR) in live


def test_live_patterns_dedups_an_operator_copy_of_a_builtin(engine):
    """One regex must yield one entry, or it yields two proposals (council I1)."""
    engine.settings.whisper_synthetic_prompt_patterns = [TASK_NOTIFICATION]

    live = live_patterns(engine.settings)

    assert [p for p, _ in live].count(TASK_NOTIFICATION) == 1
    assert (TASK_NOTIFICATION, OPERATOR) in live  # operator wins: it is what the user can remove


def test_pattern_that_never_matched_is_not_rot(engine):
    """Irrelevance, not rot: <scheduled-task> matching zero means this install
    never runs scheduled tasks. Proposing removal would be noise."""
    engine.settings.whisper_pattern_rot_days = 30
    _decision(engine, outcome="injected", matched_pattern=None, logged_at=NOW)

    assert find_rotted_patterns(engine.db.conn, engine.settings, NOW) == []


def test_pattern_still_firing_is_not_rot(engine):
    engine.settings.whisper_pattern_rot_days = 30
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=NOW - timedelta(days=2))

    assert find_rotted_patterns(engine.db.conn, engine.settings, NOW) == []


def _rotted_history(engine, pattern, *, hits=2, age_days=60):
    """`hits` past matches for `pattern`, plus recent human traffic.

    hits defaults to 2 because whisper_pattern_rot_min_matches defaults to 2 — a
    single historical match is deliberately not rot (council I4).
    """
    for i in range(hits):
        _decision(engine, outcome="silent_synthetic", matched_pattern=pattern,
                  logged_at=NOW - timedelta(days=age_days + i))
    _decision(engine, outcome="injected", matched_pattern=None, logged_at=NOW)


def test_pattern_that_matched_before_and_stopped_is_rot(engine):
    engine.settings.whisper_pattern_rot_days = 30
    _rotted_history(engine, TASK_NOTIFICATION)

    rotted = find_rotted_patterns(engine.db.conn, engine.settings, NOW)

    assert len(rotted) == 1
    assert rotted[0].pattern == TASK_NOTIFICATION
    assert rotted[0].origin == BUILTIN


def test_operator_pattern_rot_carries_the_operator_origin(engine):
    engine.settings.whisper_pattern_rot_days = 30
    engine.settings.whisper_synthetic_prompt_patterns = [r"BATCH JOB"]
    _rotted_history(engine, r"BATCH JOB")

    rotted = find_rotted_patterns(engine.db.conn, engine.settings, NOW)

    assert [(r.pattern, r.origin) for r in rotted] == [(r"BATCH JOB", OPERATOR)]


def test_filter_disabled_proposes_nothing(engine):
    """council C1. With the filter off nothing writes silent_synthetic, so every
    last_seen freezes while human traffic keeps the vacation guard happy — the
    whole pattern list would age into false proposals claiming an upstream rename
    that never happened, and the user might delete a still-valid filter."""
    engine.settings.whisper_pattern_rot_days = 30
    engine.settings.whisper_synthetic_filter_enabled = False
    _rotted_history(engine, TASK_NOTIFICATION)

    assert find_rotted_patterns(engine.db.conn, engine.settings, NOW) == []


def test_single_historical_match_is_not_rot(engine):
    """council I4. One match months ago is not evidence of a live workflow."""
    engine.settings.whisper_pattern_rot_days = 30
    engine.settings.whisper_pattern_rot_min_matches = 2
    _rotted_history(engine, TASK_NOTIFICATION, hits=1)

    assert find_rotted_patterns(engine.db.conn, engine.settings, NOW) == []


def test_no_traffic_at_all_proposes_nothing(engine):
    """The vacation guard. Two weeks away must not rot every pattern at once."""
    engine.settings.whisper_pattern_rot_days = 30
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=NOW - timedelta(days=60))
    # No row inside the window at all.

    assert find_rotted_patterns(engine.db.conn, engine.settings, NOW) == []


def test_pattern_removed_from_config_is_ignored(engine):
    """History for a pattern the user already deleted is not actionable."""
    engine.settings.whisper_pattern_rot_days = 30
    engine.settings.whisper_synthetic_prompt_patterns = []
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=r"GONE FROM ENV", logged_at=NOW - timedelta(days=60))
    _decision(engine, outcome="injected", matched_pattern=None, logged_at=NOW)

    rotted = find_rotted_patterns(engine.db.conn, engine.settings, NOW)

    assert all(r.pattern != r"GONE FROM ENV" for r in rotted)


def test_find_rotted_patterns_writes_nothing(engine):
    """Detection is a pure read; only task 4's job writes."""
    engine.settings.whisper_pattern_rot_days = 30
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=NOW - timedelta(days=60))
    _decision(engine, outcome="injected", matched_pattern=None, logged_at=NOW)

    find_rotted_patterns(engine.db.conn, engine.settings, NOW)

    count = engine.db.conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert count == 0

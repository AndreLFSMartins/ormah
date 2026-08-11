# Task 3: settings, `ProposalType.pattern`, and `find_rotted_patterns`

**Files:**
- Modify: `src/ormah/config.py:267-268`
- Modify: `src/ormah/models/proposals.py:12-15`
- Modify: `ui/src/types.ts:84`
- Create: `src/ormah/background/synthetic_pattern_monitor.py`
- Create: `tests/test_background/test_synthetic_pattern_monitor.py`

**Interfaces:**
- Consumes: `whisper_decisions.matched_pattern` (task 2); `_SYNTHETIC_PATTERNS` from `ormah.engine.prompt_classifier`.
- Produces, in `ormah.background.synthetic_pattern_monitor`:
  - `BUILTIN = "builtin"`, `OPERATOR = "operator"`
  - `RottedPattern` — frozen dataclass with `pattern: str`, `origin: str`, `last_seen: str`
  - `live_patterns(settings) -> list[tuple[str, str]]` — `(pattern_source, origin)`, deduped by pattern
  - `find_rotted_patterns(conn, settings, now: datetime) -> list[RottedPattern]` — **pure read, no writes**
  - `ProposalType.pattern` in `ormah.models.proposals`
  - Settings `whisper_pattern_rot_days`, `whisper_pattern_monitor_interval_minutes`,
    `whisper_pattern_rot_min_matches`

  Task 4 wraps `find_rotted_patterns` in the job that files proposals.

**Why detection is split from proposing:** this half is a pure function over the DB. It can be tested exhaustively by injecting `now` — no clock, no waiting 30 days, no side effects to unwind. Task 4 adds the writes.

---

- [ ] **Step 1: Add the settings**

In `src/ormah/config.py`, after `whisper_synthetic_prompt_patterns` (L268), add:

```python
    # Rot detection for the list above (#143). A pattern that matched before and
    # stopped is stale; a pattern that never matched is merely irrelevant to this
    # install and stays silent. rot_days is also the traffic-guard window: no
    # whisper traffic at all in it means the user was away, not that the patterns
    # died — so nothing is proposed.
    whisper_pattern_rot_days: int = 30
    whisper_pattern_monitor_interval_minutes: int = 1440
    # A pattern that fired once, months ago, is not evidence of a live workflow.
    # Proposing its removal is noise, and noise teaches the user to ignore the
    # alert — which defeats the feature. Require a real history before calling
    # anything rotted (council I4).
    whisper_pattern_rot_min_matches: int = 2
```

- [ ] **Step 2: Add the proposal type**

In `src/ormah/models/proposals.py`, L12-15:

```python
class ProposalType(str, Enum):
    merge = "merge"
    conflict = "conflict"
    decay = "decay"
    pattern = "pattern"  # synthetic-prompt pattern correction (#143)
```

Mirror it in the hand-maintained union at `ui/src/types.ts:84`:

```ts
export type ProposalType = "merge" | "conflict" | "decay" | "pattern";
```

**Never reuse `decay` for this.** `decay_manager.py:20-24` runs `DELETE FROM proposals WHERE type='decay' AND status='pending'` on every single run, unguarded, despite its "one-time cleanup" comment. A `decay`-typed proposal is deleted nightly.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_background/test_synthetic_pattern_monitor.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_synthetic_pattern_monitor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.background.synthetic_pattern_monitor'`

- [ ] **Step 5: Implement the detection**

Create `src/ormah/background/synthetic_pattern_monitor.py`:

```python
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
```

Note on the ISO string comparison (`seen > cutoff`): every writer uses
`datetime.now(timezone.utc).isoformat()`, so all timestamps share one format and one
timezone, making lexicographic order match chronological order. This is the same
comparison `whisper_log_cleanup.py:36-43` already relies on.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_synthetic_pattern_monitor.py -v`
Expected: PASS (11 passed)

- [ ] **Step 7: Lint and commit**

```bash
make lint
git add src/ormah/config.py src/ormah/models/proposals.py ui/src/types.ts \
        src/ormah/background/synthetic_pattern_monitor.py \
        tests/test_background/test_synthetic_pattern_monitor.py
git commit -m "feat(whisper): detect synthetic patterns that stopped matching (#143)"
```

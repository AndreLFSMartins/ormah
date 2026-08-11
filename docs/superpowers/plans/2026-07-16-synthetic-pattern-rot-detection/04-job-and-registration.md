# Task 4: the job — file deduped proposals, and register it

**Files:**
- Modify: `src/ormah/background/synthetic_pattern_monitor.py` (append the job)
- Modify: `src/ormah/background/scheduler.py` (register, near the `whisper_log_cleanup` block at L166-174)
- Modify: `src/ormah/api/routes_admin.py:24-38` (`_TASK_RUNNERS`), `:40-55` (`_TASK_DESCRIPTIONS`)
- Test: `tests/test_background/test_synthetic_pattern_monitor.py` (append)
- Test: `tests/test_background/test_scheduler.py` (append)

**Interfaces:**
- Consumes: `find_rotted_patterns`, `RottedPattern`, `BUILTIN`, `OPERATOR` (task 3); `ProposalType.pattern` (task 3); `whisper_decisions.matched_pattern` (task 2).
- Produces: `run_synthetic_pattern_monitor(engine, *, now: datetime | None = None) -> dict[str, int]` returning `{"rotted": N, "proposals_created": M}`. The `now` keyword mirrors `run_whisper_log_cleanup` (`whisper_log_cleanup.py:13-17`) and is what makes rot testable without waiting 30 days.

**Registration decision (deviates from the spec — see `00-overview.md`):** `scheduler.py` + `_TASK_RUNNERS` + `_TASK_DESCRIPTIONS`, but **not** `_SLEEP_CYCLE_ORDER` and **not** `_stagger_factor`.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_synthetic_pattern_monitor.py` (the imports and helpers from task 3 are already there; add `run_synthetic_pattern_monitor` to the import list):

```python
def _rot_one_builtin(engine):
    """A rotted <task-notification> plus live traffic — the standard setup.

    Reuses _rotted_history from task 3, so the 2-match minimum stays in one place.
    """
    engine.settings.whisper_pattern_rot_days = 30
    _rotted_history(engine, TASK_NOTIFICATION)


def test_rotted_pattern_creates_one_pending_proposal(engine):
    _rot_one_builtin(engine)

    result = run_synthetic_pattern_monitor(engine, now=NOW)

    assert result == {"rotted": 1, "proposals_created": 1}
    row = engine.db.conn.execute(
        "SELECT type, status, source_nodes, proposed_action, reason FROM proposals"
    ).fetchone()
    assert row["type"] == "pattern"
    assert row["status"] == "pending"
    assert row["source_nodes"] == "[]"
    assert TASK_NOTIFICATION in row["proposed_action"]


def test_running_twice_does_not_duplicate(engine):
    """The job runs daily and the pattern stays rotted daily."""
    _rot_one_builtin(engine)

    run_synthetic_pattern_monitor(engine, now=NOW)
    second = run_synthetic_pattern_monitor(engine, now=NOW + timedelta(days=1))

    assert second["proposals_created"] == 0
    count = engine.db.conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert count == 1


def test_proposed_action_is_stable_across_days(engine):
    """proposed_action IS the dedup key: a date or count in it would change every
    run, the dedup would never hit, and this would file one proposal per day."""
    _rot_one_builtin(engine)

    run_synthetic_pattern_monitor(engine, now=NOW)
    first = engine.db.conn.execute("SELECT proposed_action FROM proposals").fetchone()[0]
    engine.db.conn.execute("DELETE FROM proposals")
    run_synthetic_pattern_monitor(engine, now=NOW + timedelta(days=9))
    later = engine.db.conn.execute("SELECT proposed_action FROM proposals").fetchone()[0]

    assert first == later


def test_rejected_proposal_is_not_re_proposed(engine):
    """Rejecting means "I know, leave it" — it must not come back tomorrow."""
    _rot_one_builtin(engine)
    run_synthetic_pattern_monitor(engine, now=NOW)
    engine.db.conn.execute("UPDATE proposals SET status = 'rejected'")
    engine.db.conn.commit()

    result = run_synthetic_pattern_monitor(engine, now=NOW + timedelta(days=1))

    assert result["proposals_created"] == 0


def test_builtin_and_operator_get_different_actions(engine):
    """Telling the user to remove from .env a pattern that is not in their .env
    is an instruction impossible to follow."""
    engine.settings.whisper_pattern_rot_days = 30
    engine.settings.whisper_synthetic_prompt_patterns = [r"BATCH JOB"]
    _rotted_history(engine, TASK_NOTIFICATION)
    _rotted_history(engine, r"BATCH JOB")

    run_synthetic_pattern_monitor(engine, now=NOW)

    actions = {
        r["proposed_action"]
        for r in engine.db.conn.execute("SELECT proposed_action FROM proposals").fetchall()
    }
    operator_action = next(a for a in actions if r"BATCH JOB" in a)
    builtin_action = next(a for a in actions if TASK_NOTIFICATION in a)
    assert "ORMAH_WHISPER_SYNTHETIC_PROMPT_PATTERNS" in operator_action
    assert "ORMAH_WHISPER_SYNTHETIC_PROMPT_PATTERNS" not in builtin_action


def test_reason_carries_the_variable_evidence(engine):
    _rot_one_builtin(engine)

    run_synthetic_pattern_monitor(engine, now=NOW)

    reason = engine.db.conn.execute("SELECT reason FROM proposals").fetchone()[0]
    assert (NOW - timedelta(days=60)).isoformat() in reason


def test_a_second_rot_episode_gets_a_fresh_proposal(engine):
    """council I2. Pattern rots, is repaired, resumes matching, rots AGAIN.

    Without `created > last_seen` in the dedup, the historical row would block
    the new episode forever and the second regression would go unreported.
    """
    _rot_one_builtin(engine)
    run_synthetic_pattern_monitor(engine, now=NOW)
    engine.db.conn.execute("UPDATE proposals SET status = 'approved'")
    engine.db.conn.commit()

    # The marker comes back (repaired), fires twice, then goes quiet again.
    later = NOW + timedelta(days=100)
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=later)
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=later + timedelta(days=1))
    much_later = later + timedelta(days=60)
    _decision(engine, outcome="injected", matched_pattern=None, logged_at=much_later)

    result = run_synthetic_pattern_monitor(engine, now=much_later)

    assert result["proposals_created"] == 1
    count = engine.db.conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert count == 2


def test_proposed_action_says_the_action_is_manual(engine):
    """council I3. Approving executes nothing, yet the shared proposals surface
    reports success and drops the item — the text must not let the user believe
    the repair happened."""
    _rot_one_builtin(engine)

    run_synthetic_pattern_monitor(engine, now=NOW)

    action = engine.db.conn.execute("SELECT proposed_action FROM proposals").fetchone()[0]
    assert action.startswith("MANUAL ACTION REQUIRED")


def test_no_rot_creates_nothing(engine):
    engine.settings.whisper_pattern_rot_days = 30
    _decision(engine, outcome="silent_synthetic",
              matched_pattern=TASK_NOTIFICATION, logged_at=NOW - timedelta(days=1))

    assert run_synthetic_pattern_monitor(engine, now=NOW) == {
        "rotted": 0, "proposals_created": 0,
    }


def test_decay_manager_does_not_eat_pattern_proposals(engine):
    """decay_manager.py:20-24 deletes type='decay' proposals on EVERY run,
    unguarded. This pins that 'pattern' is not caught by that DELETE."""
    from ormah.background.decay_manager import run_decay

    _rot_one_builtin(engine)
    run_synthetic_pattern_monitor(engine, now=NOW)

    run_decay(engine)

    count = engine.db.conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE type = 'pattern'"
    ).fetchone()[0]
    assert count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_background/test_synthetic_pattern_monitor.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_synthetic_pattern_monitor'`

- [ ] **Step 3: Implement the job**

Append to `src/ormah/background/synthetic_pattern_monitor.py`. Task 3 already wrote `from datetime import datetime, timedelta` — **add `timezone` to that existing line rather than writing a second import**:

```python
from datetime import datetime, timedelta, timezone
```

Then add these alongside the imports already there:

```python
import logging
import uuid

from ormah.models.proposals import ProposalType

logger = logging.getLogger(__name__)
```

Then append:

```python
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
```

`source_nodes='[]'` is honest — there are no nodes. Verified safe: `GET /agent/proposals` does `json.loads(r["source_nodes"])` → `[]`, so the enrich loop at `routes_agent.py:341-348` never runs and yields `nodes: []`; and an action without `"\n---\n"` takes the `else` at `:357-359`, so `action_summary` is the text and `merged_preview` is `None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_background/test_synthetic_pattern_monitor.py -v`
Expected: PASS (21 passed — 11 from task 3, 10 here)

- [ ] **Step 5: Register in the scheduler**

In `src/ormah/background/scheduler.py`, after the `whisper_log_cleanup` block (L166-174), following that block's exact shape (local import, `tracked`, no `next_run_time=_staggered(...)` — that is for LLM jobs only):

```python
    from ormah.background.synthetic_pattern_monitor import run_synthetic_pattern_monitor

    scheduler.add_job(
        tracked(tracker, "synthetic_pattern_monitor", run_synthetic_pattern_monitor, engine),
        "interval",
        minutes=s.whisper_pattern_monitor_interval_minutes,
        id="synthetic_pattern_monitor",
        name="Synthetic pattern monitor",
        misfire_grace_time=_MISFIRE_GRACE,
    )
```

**Read L160-180 before editing** to confirm the surrounding style and that `s` is the settings local in scope.

- [ ] **Step 6: Register the manual trigger**

In `src/ormah/api/routes_admin.py`, add to `_TASK_RUNNERS` (L24-38):

```python
    "synthetic_pattern_monitor": (
        "ormah.background.synthetic_pattern_monitor", "run_synthetic_pattern_monitor",
    ),
```

and to `_TASK_DESCRIPTIONS` (L40-55):

```python
    "synthetic_pattern_monitor": "Detects synthetic-prompt patterns that stopped matching and proposes removing or repairing them. Proposes only — never edits your config (#143).",
```

Do **not** add it to `_SLEEP_CYCLE_ORDER` (L58-70): that pass is memory consolidation, and `whisper_log_cleanup` sets the precedent that whisper maintenance stays out of it.

- [ ] **Step 7: Test the registration**

Append to `tests/test_background/test_scheduler.py`, mirroring `test_forgetting_job_is_registered`:

```python
def test_synthetic_pattern_monitor_is_registered(engine):
    scheduler, _tracker = start_scheduler(engine)
    try:
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "synthetic_pattern_monitor" in job_ids
    finally:
        scheduler.shutdown(wait=False)
```

Run: `python -m pytest tests/test_background/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 8: Full suite and lint**

Run: `make test && make lint`
Expected: both green. Cite the counts.

- [ ] **Step 9: Commit**

```bash
git add src/ormah/background/synthetic_pattern_monitor.py \
        src/ormah/background/scheduler.py src/ormah/api/routes_admin.py tests/
git commit -m "feat(maintenance): propose corrections for rotted synthetic patterns (#143)"
```

- [ ] **Step 10: Run the manual verification from `00-overview.md`**

Steps 2-5 there are behavioural and cannot be replaced by the test suite: the migration on a real pre-change DB, the live `/agent/whisper` round-trip, forcing rot with `ORMAH_WHISPER_PATTERN_ROT_DAYS=0` via `/admin`, and confirming `run_decay` leaves the `pattern` proposals alone. Cite the output of each.

# Task 1: The boot backfill stamps the real event time

Read `00-overview.md` first — it carries the island rules, the test command, and the baseline.

**Problem:** `_claim_confirmed_use` stamps `claimed_at = datetime('now')` unconditionally, so the
boot backfill records uses that happened 2–13 days ago as happening at startup, and
`_record_confirmed_use` pushes that unearned recency into `last_accessed` (the decay anchor),
`last_review` and FSRS.

**Files:**
- Modify: `/Users/andre/Documents/GitHub/Tools/ormah-wt-272/src/ormah/engine/memory_engine.py`
  (`_claim_confirmed_use` INSERT ~`:3010-3025`; backfill call site ~`:362-370`)
- Test: `/Users/andre/Documents/GitHub/Tools/ormah-wt-272/tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: existing test helpers in that file — `_make_nodes(engine, count=1)`,
  `_seed_whisper_log(engine, node_id)`, `_seed_heuristic_signal(engine, node_id, whisper_log_id,
  strength=0.98)`, `_take_claim(engine, log_id, node_id)`, `_claim_row(engine, log_id, node_id)`.
  The file already imports `datetime, timedelta, timezone`.
- Produces: `_claim_confirmed_use(..., historical: bool = False)` — Task 2 does not depend on it.

**Format facts (measured, do not re-derive):** `whisper_log.logged_at` is Python isoformat
(`'2026-08-28T17:36:44.454369+00:00'`); `datetime('now')` yields `'2026-08-28 17:36:44'`.
SQLite's `datetime()` normalizes the former to the latter shape (offsets converted to UTC,
malformed input → NULL). Mixed shapes would break the sweeper's lexicographic SQL
(`reinforcement_retry.py:52-54`), so every stored `claimed_at` must stay space-format UTC.

- [ ] **Step 1: Write the two failing tests** — append to
  `tests/test_engine/test_confirmed_use_contract.py`, after
  `test_backfill_isolates_one_nodes_failure`:

```python
def test_backfill_does_not_advance_last_accessed_to_boot_time(engine):
    """Council #272 finding 1: a historical use must not be recorded as use now.

    last_accessed sits BETWEEN the signal's logged_at and boot time, so with the
    truthful clock max(claimed_at, last_accessed) keeps it; with the buggy boot
    clock the claim wins and drags it to now — which is exactly the RED.
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)
    event_time = datetime.now(timezone.utc) - timedelta(days=10)
    anchor_time = datetime.now(timezone.utc) - timedelta(days=2)
    engine.db.conn.execute(
        "UPDATE whisper_log SET logged_at = ? WHERE id = ?",
        (event_time.isoformat(), log_id),
    )
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ? WHERE id = ?",
        (anchor_time.isoformat(), target),
    )
    engine.db.conn.commit()

    engine._migrate_heuristic_confirmed_use()

    row = engine.db.conn.execute(
        "SELECT last_accessed FROM nodes WHERE id = ?", (target,)
    ).fetchone()
    assert datetime.fromisoformat(row["last_accessed"]) == anchor_time, (
        "backfilling a 10-day-old signal moved last_accessed to boot time — "
        "the claim must carry the event's clock, not the wall clock"
    )


def test_backfill_claim_carries_the_events_time_normalized(engine):
    """Council #272 finding 1: claimed_at = logged_at, in datetime('now') shape.

    The space-format assertion is the sweeper's contract: reinforcement_retry
    compares claimed_at lexicographically against datetime('now', ...), where
    'T' (0x54) sorts above ' ' (0x20).
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)
    engine.db.conn.execute(
        "UPDATE whisper_log SET logged_at = '2026-08-15T12:00:00.123456+00:00' "
        "WHERE id = ?",
        (log_id,),
    )
    engine.db.conn.commit()

    engine._migrate_heuristic_confirmed_use()

    row = _claim_row(engine, log_id, target)
    assert row is not None, "the backfill claimed nothing"
    assert row["claimed_at"] == "2026-08-15 12:00:00", (
        f"claimed_at is {row['claimed_at']!r}: the backfill must stamp the "
        "event's logged_at, normalized to SQLite's space-format UTC"
    )
```

- [ ] **Step 2: Run them, verify both FAIL for the right reason**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
HOME="$H" .venv/bin/python -m pytest \
  "tests/test_engine/test_confirmed_use_contract.py::test_backfill_does_not_advance_last_accessed_to_boot_time" \
  "tests/test_engine/test_confirmed_use_contract.py::test_backfill_claim_carries_the_events_time_normalized" -v
```

Expected: both FAIL with `AssertionError` — the first because `last_accessed` moved to ~now,
the second because `claimed_at` is today's timestamp. Any other failure (fixture error,
`sqlite3` error) means the test is wrong — stop and fix the test, not the code.

- [ ] **Step 3: Implement.** In `_claim_confirmed_use`
  (`src/ormah/engine/memory_engine.py`, def at ~`:2956`):

  (a) add the keyword parameter after `strength: float,`:

```python
        strength: float,
        historical: bool = False,
```

  (b) replace the INSERT block (currently `SELECT wl.id, ?, datetime('now'), 'pending'` with
  params `(node_id, whisper_log_id)`) with:

```python
        # Issue #272 (council finding 1): a backfilled claim carries the EVENT's
        # clock, not the boot's — claimed_at drives last_accessed, last_review and
        # FSRS in _record_confirmed_use, so stamping datetime('now') would credit
        # 2-13 day old uses with recency they never earned. The truthful timestamp
        # comes from the very whisper_log row this INSERT already reads, and SQLite's
        # datetime() normalizes its Python-isoformat shape ('...T...+00:00') to the
        # same space-format UTC datetime('now') writes — the sweeper compares
        # claimed_at lexicographically (reinforcement_retry.py), so mixed shapes
        # would misorder. COALESCE: a malformed logged_at (datetime() -> NULL) falls
        # back to the boot clock rather than aborting the whole backfill transaction
        # (claimed_at is NOT NULL) or orphaning the signal forever (the cutoff
        # advances regardless). Live claims keep datetime('now'): their skew is
        # minutes, and their sources' semantics are not this fix's scope.
        conn.execute(
            """
            INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at, state)
            SELECT wl.id, ?,
                   CASE WHEN ? THEN COALESCE(datetime(wl.logged_at), datetime('now'))
                        ELSE datetime('now') END,
                   'pending'
            FROM whisper_log wl
            WHERE wl.id = ? AND wl.was_injected = 1
            ON CONFLICT DO NOTHING
            """,
            (node_id, 1 if historical else 0, whisper_log_id),
        )
```

  (c) at the backfill call site (~`:362`), add the keyword:

```python
                if eligible and self._claim_confirmed_use(
                    conn,
                    row["whisper_log_id"],
                    row["node_id"],
                    signal=1,
                    source="auto_heuristic",
                    strength=strength,
                    historical=True,
                ):
```

  The other three call sites (`:978`, `:3105`, and any in tests) stay untouched — the default
  `False` preserves their behavior.

- [ ] **Step 4: Run the two tests again** (same command as Step 2). Expected: both PASS.

- [ ] **Step 5: Add the two guard tests** (append after the Step 1 tests). Both are GREEN
  before and after the fix — they pin the COALESCE fallback and the live path against future
  regression, and their docstrings say so honestly:

```python
def test_backfill_survives_a_malformed_logged_at(engine):
    """Guard, not RED: a malformed logged_at falls back to the boot clock.

    datetime('not-a-timestamp') is NULL and claimed_at is NOT NULL — without the
    COALESCE the INSERT raises IntegrityError and the whole backfill transaction
    dies at boot. Falling back keeps today's behavior for that one row instead of
    losing the signal forever (the cutoff advances regardless).
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _seed_heuristic_signal(engine, target, log_id, strength=0.98)
    engine.db.conn.execute(
        "UPDATE whisper_log SET logged_at = 'not-a-timestamp' WHERE id = ?",
        (log_id,),
    )
    engine.db.conn.commit()

    engine._migrate_heuristic_confirmed_use()

    row = _claim_row(engine, log_id, target)
    assert row is not None, "a malformed logged_at must not cost the claim"
    assert "T" not in row["claimed_at"]
    stamped = datetime.fromisoformat(row["claimed_at"]).replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamped).total_seconds()) < 60


def test_live_claim_still_stamps_now(engine):
    """Guard, not RED: the historical clock is backfill-only (decision 2026-08-28).

    A live claim's skew from its event is minutes; its sources' semantics
    (explicit/implicit/judge) are out of this fix's scope.
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    engine.db.conn.execute(
        "UPDATE whisper_log SET logged_at = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=10)).isoformat(), log_id),
    )
    engine.db.conn.commit()

    _take_claim(engine, log_id, target)

    row = _claim_row(engine, log_id, target)
    assert "T" not in row["claimed_at"]
    stamped = datetime.fromisoformat(row["claimed_at"]).replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamped).total_seconds()) < 60, (
        "a live claim must keep the wall clock even when its event is old"
    )
```

- [ ] **Step 6: Run the whole contract file**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
HOME="$H" .venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py -q
```

Expected: all pass, 0 failed.

- [ ] **Step 7: Full suite + ruff** (commands and baseline in `00-overview.md`). Expected:
  `3 failed, 2054 passed` (2050 baseline + the 4 new tests) — only the `TestConfigureCodexMcp`
  trio fails; ruff clean.

- [ ] **Step 8: Commit** (island, exact paths):

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-272
git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py
git commit -m "fix(feedback): the boot backfill stamps the event's time, not the boot's (#272)"
git show --stat HEAD
```

Expected: exactly the two files in the stat.

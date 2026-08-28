# Task 5: Durable Reinforcement After the Claim (#220 debt)

**Depends on:** Tasks 2, 3 and 4 — it adjusts every call site of `_record_confirmed_use`, including
the two that Tasks 2 and 4 create. **Read `00-overview.md` first — its Global Constraints apply,
with the one documented exception below.**

**Files:**
- Modify: `src/ormah/index/schema.sql` (`:243-248`, the `confirmed_use_claims` table)
- Modify: `src/ormah/index/db.py` (`_migrate`, after the `idx_nodes_seq` block)
- Modify: `src/ormah/engine/memory_engine.py` (`:2121` the mutator, `:855` `recall_node`, `:2805`
  `submit_feedback`, plus the backfill call site Task 4 creates)
- Modify: `src/ormah/background/session_watcher.py` (`:573`, `:610`, `:623` — the judge block, plus
  the heuristic block Task 2 creates)
- Create: `src/ormah/background/reinforcement_retry.py`
- Modify: `src/ormah/config.py` (setting near `:64`, validator list at `:376-380`)
- Modify: `src/ormah/background/scheduler.py` (new `add_job` before `scheduler.start()`)
- Modify: `src/ormah/api/routes_admin.py` (`_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`,
  `_SLEEP_CYCLE_ORDER`)
- Test: `tests/test_engine/test_confirmed_use_contract.py`
- Test: `tests/test_background/test_reinforcement_retry.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–4 by signature. It changes the mutator every one of them calls.
- Produces: `_record_confirmed_use(self, node_id: str, *, whisper_log_id: int) -> None` and
  `ormah.background.reinforcement_retry.run_reinforcement_retry(engine) -> None`.

## Background

`_claim_confirmed_use` takes the at-most-once latch **inside** the caller's transaction; that
transaction commits; only afterwards does `_record_confirmed_use` run, and every call site wraps it
in a bare `except` that logs and swallows. The claim is a monotonic latch with no undo, so nothing
retries. One transient filesystem failure defeats the reinforcement permanently for that node.

The defect predates #272 — it arrived with the #220 lifecycle family (`6222e74`, `2a69cd5`,
`522aa92`, `a24a5c8`, `759f209`). `759f209` already answered the #220 council on this surface by
isolating the exception *better*, not by making the promise durable. #272 raises the stakes: Task 4's
boot backfill runs a whole batch through this path at once.

Second half of the same defect: `_record_confirmed_use` is not atomic with itself. It does
`file_store.save(node)` (disk) and only then opens `db.transaction()` for the `UPDATE nodes`. Save
succeeds, UPDATE fails, markdown and database diverge — and a naive retry re-increments a markdown
that already moved.

Spec: `docs/superpowers/specs/2026-08-28-durable-reinforcement-after-claim-design.md`.

## Why this task may reorder the mutator, and Tasks 1–4 may not

`00-overview.md` carries the full reasoning under Global Constraints; the short form is that
`FileStore` is built with the engine's own `_memory_operation_lock` (`memory_engine.py:109`,
`:1424`), an `RLock` that `@_serialized_memory_operation` (`:94-99`) already holds when the body
runs, so a `file_store` call from inside the method's own transaction re-enters rather than
acquiring `db_lock` first. `Database.transaction` (`index/db.py:68-82`) is reentrant per thread and
rolls back only at depth 1, so the rollback this task relies on is real.

Nothing about the callers changes: they still call the mutator outside their own transaction.
`04-backfill.md`'s rule 2 stands untouched.

## This is convergence, not atomicity — do not describe it as atomic

An earlier draft called this atomic. **Council round 1 refuted that** (run
`98918652-c2f6a005-fc06a07a`, Codex, HIGH, confidence 0.99) and was right: `os.replace` is
irreversible and `Database.transaction` issues its `COMMIT` *after* the body returns, so a `COMMIT`
that fails — disk full, `SQLITE_BUSY`, I/O error, not merely a crash — leaves the markdown advanced
while the `nodes` row and the claim roll back. No ordering can enrol a filesystem in a SQLite
transaction.

What makes it safe is **where the new values come from**: the mutator computes them from the `nodes`
row, never by incrementing the markdown it loaded, so a retry recomputes the *same* target and
overwrites the phantom instead of compounding it. The markdown is a projection of lifecycle state,
which is already how `decay_manager` and `importance_scorer` treat it.

What remains is a window in which a reader of the *file* sees a value one step ahead of the row.
Nothing reads the file for lifecycle, and the next run closes it. Step 1's
`test_failed_commit_does_not_inflate_the_counter` is the proof of this property, not optional
coverage.

---

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_engine/test_confirmed_use_contract.py`:

```python
def _claim_row(engine, log_id, node_id):
    return engine.db.conn.execute(
        "SELECT claimed_at, state, reinforced_at FROM confirmed_use_claims "
        "WHERE whisper_log_id = ? AND node_id = ?",
        (log_id, node_id),
    ).fetchone()


def _take_claim(engine, log_id, node_id):
    with engine.db.transaction() as conn:
        engine._claim_confirmed_use(
            conn, log_id, node_id, signal=1, source="explicit", strength=1.0,
        )


def test_mutator_failure_leaves_no_residue(engine, monkeypatch):
    """#272 D5-1: a failed save rolls back the claim state AND the nodes row."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _take_claim(engine, log_id, target)

    before = _snapshot(engine, target)

    def boom(node):
        raise OSError("disk full")

    monkeypatch.setattr(engine.file_store, "save", boom)
    with pytest.raises(OSError):
        engine._record_confirmed_use(target, whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, "the failed mutator left a partial write"
    assert _claim_row(engine, log_id, target)["state"] == "pending", (
        "the claim left 'pending' even though nothing was applied"
    )


def test_failed_commit_does_not_inflate_the_counter(engine, monkeypatch):
    """#272 D5-2: the convergence claim, tested at the one place it can break.

    os.replace cannot be rolled back and COMMIT runs after the transaction body, so a
    failing COMMIT leaves the markdown one step ahead of the nodes row. Because the new
    values are computed FROM the nodes row, the retry recomputes the same target and
    overwrites the phantom — it must not add a second increment on top of it.
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _take_claim(engine, log_id, target)

    baseline = engine.db.conn.execute(
        "SELECT access_count FROM nodes WHERE id = ?", (target,)
    ).fetchone()["access_count"]

    real_execute = engine.db.conn.execute

    def commit_fails(sql, *args, **kwargs):
        if sql.strip().upper().startswith("COMMIT"):
            raise sqlite3.OperationalError("disk I/O error")
        return real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(engine.db.conn, "execute", commit_fails)
    with pytest.raises(sqlite3.OperationalError):
        engine._record_confirmed_use(target, whisper_log_id=log_id)
    monkeypatch.undo()

    # The markdown ran ahead; the row and the claim did not.
    assert engine.file_store.load(target).access_count == baseline + 1
    assert engine.db.conn.execute(
        "SELECT access_count FROM nodes WHERE id = ?", (target,)
    ).fetchone()["access_count"] == baseline
    assert _claim_row(engine, log_id, target)["state"] == "pending"

    engine._record_confirmed_use(target, whisper_log_id=log_id)

    after = _snapshot(engine, target)
    assert after["file"] == after["db"], "the stores did not converge"
    assert engine.db.conn.execute(
        "SELECT access_count FROM nodes WHERE id = ?", (target,)
    ).fetchone()["access_count"] == baseline + 1, (
        "one event produced more than one increment"
    )


def test_happy_path_agrees_across_claim_row_and_markdown(engine):
    """#272 D5-9: on success all three carry the same values."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _take_claim(engine, log_id, target)

    before = _snapshot(engine, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)
    after = _snapshot(engine, target)

    assert after != before, "nothing was reinforced"
    assert after["file"] == after["db"], "markdown and database disagree"
    row = _claim_row(engine, log_id, target)
    assert row["state"] == "applied"
    assert row["reinforced_at"] is not None


def test_mutator_is_at_most_once_on_an_applied_claim(engine):
    """#272 D5-4: a second call on an applied claim is a no-op."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    _take_claim(engine, log_id, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)

    after_first = _snapshot(engine, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, "the second call reinforced again"


def test_missing_node_ends_orphaned_not_applied(engine):
    """#272 D5-7: a deleted node is terminal, and is not recorded as a success.

    The claim is inserted directly for a node_id that has no markdown file. Only
    whisper_log_id carries a foreign key (PRAGMA foreign_keys=ON), so a claim can
    legitimately outlive its node — which is exactly the state being tested.

    'applied' would be a lie of the same kind the legacy migration refuses to write,
    so the assertion pins the distinction, not merely "it stopped being pending".
    """
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at) "
            "VALUES (?, 'ghost-node', datetime('now'))",
            (log_id,),
        )

    engine._record_confirmed_use("ghost-node", whisper_log_id=log_id)

    row = _claim_row(engine, log_id, "ghost-node")
    assert row["state"] == "orphaned", (
        "a claim for a deleted node must be orphaned, never pending (retried forever) "
        "nor applied (a reinforcement that never happened)"
    )
    assert row["reinforced_at"] is None
```

`sqlite3` must be imported at the top of the file if it is not already.

Create `tests/test_background/test_reinforcement_retry.py`:

```python
"""#272 D5: the sleep-cycle sweeper that makes the confirmed-use claim durable."""

from datetime import datetime, timedelta, timezone

from ormah.background.reinforcement_retry import run_reinforcement_retry


def _stale_claim(engine, log_id, node_id, minutes_ago=30):
    """Insert a claim that was taken but never applied, old enough to be swept."""
    claimed_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at) "
            "VALUES (?, ?, ?)",
            (log_id, node_id, claimed_at),
        )


def test_sweeper_reinforces_a_pending_claim(engine, seeded_claim):
    """#272 D5-3: a claim the mutator never applied is repaired."""
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, node_id)

    run_reinforcement_retry(engine)

    row = engine.db.conn.execute(
        "SELECT state, reinforced_at FROM confirmed_use_claims WHERE whisper_log_id = ?",
        (log_id,),
    ).fetchone()
    assert row["state"] == "applied", "the sweeper did not apply the claim"
    assert row["reinforced_at"] is not None
    assert _snapshot(engine, node_id) != before, "the sweeper marked but did not reinforce"


def test_sweeper_never_touches_terminal_claims(engine, seeded_claim):
    """#272 D5-8a: legacy_unknown and orphaned are terminal, not work items."""
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, node_id)
    with engine.db.transaction() as conn:
        conn.execute(
            "UPDATE confirmed_use_claims SET state = 'legacy_unknown' "
            "WHERE whisper_log_id = ? AND node_id = ?",
            (log_id, node_id),
        )

    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) == before, "the sweeper re-reinforced a legacy claim"
    assert _claim_row(engine, log_id, node_id)["state"] == "legacy_unknown"


def test_sweeper_is_at_most_once_across_runs(engine, seeded_claim):
    """#272 D5-4: running the sweeper twice reinforces once."""
    log_id, node_id, _ = seeded_claim
    _stale_claim(engine, log_id, node_id)

    run_reinforcement_retry(engine)
    after_first = _snapshot(engine, node_id)
    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) == after_first, "the second sweep reinforced again"


def test_sweeper_skips_claims_inside_the_grace_margin(engine, seeded_claim):
    """#272 D5-5: a claim taken seconds ago may still be in flight — do not race it."""
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, node_id, minutes_ago=0)

    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) == before, "the sweeper raced an in-flight claim"


def test_sweeper_isolates_one_bad_node_from_the_batch(engine, seeded_claim, monkeypatch):
    """#272 D5-6: one RAISING node must not abandon the rest of the batch.

    The failure has to be injected. A claim for a node that merely does not exist
    returns cleanly through the terminal-claim path and would prove nothing about
    isolation. Both claims hang off the same whisper_log row: the primary key is
    (whisper_log_id, node_id) and only whisper_log_id carries a foreign key, so
    this is a legal pair. The bad one is older so ORDER BY claimed_at runs it first.
    """
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, "ghost-node", minutes_ago=60)
    _stale_claim(engine, log_id, node_id, minutes_ago=30)

    real = engine._record_confirmed_use

    def flaky(target, *, whisper_log_id):
        if target == "ghost-node":
            raise OSError("disk full")
        return real(target, whisper_log_id=whisper_log_id)

    monkeypatch.setattr(engine, "_record_confirmed_use", flaky)

    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) != before, "a sibling failure abandoned the batch"
```

Add the fixture this file needs, at the top of `tests/test_background/test_reinforcement_retry.py`,
importing the helpers the contract file already defines:

```python
import pytest

from tests.test_engine.test_confirmed_use_contract import (  # noqa: E402
    _claim_row,
    _make_nodes,
    _seed_whisper_log,
    _snapshot,
)


@pytest.fixture
def seeded_claim(engine):
    """A node and a whisper_log row, with the node's pre-reinforcement snapshot."""
    node_id = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, node_id)
    return log_id, node_id, _snapshot(engine, node_id)
```

Add to `tests/test_engine/test_confirmed_use_contract.py` (the migration test — it builds its own
`Database`, so it does not use the `engine` fixture):

```python
def test_migration_marks_preexisting_claims_legacy_unknown(tmp_path):
    """#272 D5-8b: pre-#272 claims are neither swept nor recorded as successes.

    Council round 1 (Codex, HIGH) killed the first draft, which stamped them
    reinforced. The premise of this task is that SOME of those claims lost their
    reinforcement; the old schema cannot tell which, so calling them applied would
    hide exactly the data loss the task exists to repair. 'pending' is equally wrong
    — the majority did apply, and re-running them is mass over-reinforcement of an
    at-most-once latch. The assertion pins the third state, not "not pending".
    """
    from ormah.index.db import Database

    db = Database(tmp_path / "m.db")
    db.init_schema()
    db.conn.executescript(
        """
        DROP TABLE confirmed_use_claims;
        CREATE TABLE confirmed_use_claims (
            whisper_log_id INTEGER NOT NULL,
            node_id        TEXT NOT NULL,
            claimed_at     TEXT NOT NULL,
            PRIMARY KEY (whisper_log_id, node_id)
        );
        INSERT INTO confirmed_use_claims VALUES (1, 'n1', '2026-01-01 00:00:00');
        """
    )

    db._migrate()

    row = db.conn.execute(
        "SELECT state, reinforced_at FROM confirmed_use_claims"
    ).fetchone()
    assert row["state"] == "legacy_unknown", (
        "a pre-existing claim was classified, but its outcome is not knowable"
    )
    assert row["reinforced_at"] is None, (
        "reinforced_at asserts a reinforcement happened — it did not, or is unknown"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_engine/test_confirmed_use_contract.py \
  -k "residue or failed_commit or happy_path_agrees or at_most_once_on_an_applied or ends_orphaned or legacy_unknown" -v
python -m pytest tests/test_background/test_reinforcement_retry.py -v
```

Expected: FAIL. The contract tests fail with
`TypeError: _record_confirmed_use() got an unexpected keyword argument 'whisper_log_id'` and
`OperationalError: no such column: state`; the sweeper file fails at import with
`ModuleNotFoundError: No module named 'ormah.background.reinforcement_retry'`.

- [ ] **Step 3: Add the column, in the schema and in the migration**

In `src/ormah/index/schema.sql`, replace the `confirmed_use_claims` table at `:243-248`:

```sql
CREATE TABLE IF NOT EXISTS confirmed_use_claims (
    whisper_log_id INTEGER NOT NULL REFERENCES whisper_log(id) ON DELETE CASCADE,
    node_id        TEXT NOT NULL,
    claimed_at     TEXT NOT NULL,
    -- Issue #272: the claim's outcome, which the latch alone could not express.
    --   pending        the reinforcement has not landed yet — the sweeper retries these
    --   applied        it landed; reinforced_at carries when
    --   legacy_unknown written before this column existed; outcome unknowable
    --   orphaned       the node is gone, so there is nothing left to reinforce
    state          TEXT NOT NULL DEFAULT 'pending'
                   CHECK (state IN ('pending', 'applied', 'legacy_unknown', 'orphaned')),
    reinforced_at  TEXT,
    PRIMARY KEY (whisper_log_id, node_id)
);
```

In `src/ormah/index/db.py`, inside `_migrate`, immediately after the
`CREATE INDEX IF NOT EXISTS idx_nodes_seq` line:

```python
            # Issue #272: confirmed_use_claims gains an outcome. Rows written before
            # this column existed become 'legacy_unknown', NOT 'applied'.
            #
            # Stamping them as successes was this plan's first draft, and the council
            # (Codex, HIGH) refuted it: the premise of this task is that some claims
            # committed and then lost their reinforcement, those rows are exactly the
            # ones the defect produced, and the old schema cannot tell them apart from
            # the successes. Calling them applied would hide the data loss forever.
            # Calling them pending is no better — the overwhelming majority DID apply,
            # and re-running them would be mass over-reinforcement of an at-most-once
            # latch. 'legacy_unknown' is terminal for the sweeper and honest about why.
            claim_cols = [
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(confirmed_use_claims)"
                ).fetchall()
            ]
            if claim_cols and "reinforced_at" not in claim_cols:
                conn.execute(
                    "ALTER TABLE confirmed_use_claims ADD COLUMN reinforced_at TEXT"
                )
            if claim_cols and "state" not in claim_cols:
                # The column lands plain: ADD COLUMN cannot carry the CHECK. Fresh
                # databases get the constraint from schema.sql; migrated ones rely on
                # the writers, which only ever set the four listed values.
                conn.execute(
                    "ALTER TABLE confirmed_use_claims "
                    "ADD COLUMN state TEXT NOT NULL DEFAULT 'pending'"
                )
                legacy = conn.execute(
                    "UPDATE confirmed_use_claims SET state = 'legacy_unknown'"
                ).rowcount
                # Measured, not guessed: the size of the historical gap is logged so it
                # can be reasoned about instead of assumed away.
                logger.info(
                    "confirmed_use_claims: %d pre-#272 claim(s) marked legacy_unknown "
                    "(outcome not recoverable from the old schema)",
                    legacy,
                )

            # Partial index: the sweeper only ever selects the pending rows, which are a
            # vanishing fraction of the table.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_pending "
                "ON confirmed_use_claims(claimed_at) WHERE state = 'pending'"
            )
```

`claim_cols` is checked for truthiness first: on a database old enough not to have the table at all,
`PRAGMA table_info` returns an empty list and the `ALTER` must not run — `schema.sql` creates it
below, already carrying both columns and the `CHECK`.

`db.py` needs a module logger if it has none; check for `logger = logging.getLogger(__name__)` at
the top and add it with the `import logging` if absent.

- [ ] **Step 4: Make the mutator's writes converge**

In `src/ormah/engine/memory_engine.py`, replace `_record_confirmed_use`'s signature and the tail of
its body (`:2121`, and `:2170-2184` for the write block):

```python
    def _record_confirmed_use(self, node_id: str, *, whisper_log_id: int) -> None:
```

`whisper_log_id` is keyword-only and **required, with no default**, for the same reason the overview
gives for `strength` on `_claim_confirmed_use`: a default would let a future caller omit it and lose
durability in silence. Every reinforcement descends from a claim, and `_claim_confirmed_use` returns
`False` when `whisper_log_id is None`, so no call site can reach here without one.

Replace the whole body from `node = self.file_store.load(node_id)` to the end of the method. The
lifecycle arithmetic is unchanged — what changes is that its **inputs come from the `nodes` row**,
read inside the transaction, instead of from the markdown that was loaded:

```python
        node = self.file_store.load(node_id)

        # Issue #272: one transaction covers the claim's outcome, the nodes row and the
        # markdown write. Calling file_store inside db.transaction() is safe HERE and
        # nowhere else: @_serialized_memory_operation already holds
        # _memory_operation_lock and FileStore shares that RLock (:109), so this
        # re-enters rather than taking db_lock before memory_lock.
        #
        # NOT atomic across the two stores: os.replace is irreversible and COMMIT runs
        # after this body, so a failed COMMIT can leave the markdown one step ahead.
        # What makes that safe is computing the new values FROM the nodes row, so a
        # retry recomputes the same target and overwrites the phantom instead of
        # compounding it — one event, one increment.
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE confirmed_use_claims SET state = 'applied', "
                "reinforced_at = datetime('now') "
                "WHERE whisper_log_id = ? AND node_id = ? AND state = 'pending'",
                (whisper_log_id, node_id),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                # Already applied, terminal, or claimed by another runner. At-most-once,
                # the same shape _claim_confirmed_use uses. Nothing may sit between the
                # UPDATE and this read.
                return

            row = conn.execute(
                "SELECT access_count, last_accessed, stability, last_review "
                "FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if node is None or row is None:
                # Terminal, and honest about which terminal. Marking it 'applied' would
                # record a reinforcement that never happened — the same falsehood the
                # legacy migration above refuses to write.
                conn.execute(
                    "UPDATE confirmed_use_claims SET state = 'orphaned', "
                    "reinforced_at = NULL "
                    "WHERE whisper_log_id = ? AND node_id = ?",
                    (whisper_log_id, node_id),
                )
                return

            now = datetime.now(timezone.utc)
            stability = row["stability"]
            last_review = (
                datetime.fromisoformat(row["last_review"]) if row["last_review"] else None
            )
            last_accessed = (
                datetime.fromisoformat(row["last_accessed"])
                if row["last_accessed"]
                else None
            )

            # One numeric stability update per node per cooldown window (#221): the
            # old formula let ten same-session touches compound to ~57x.
            if lifecycle.reinforcement_due(
                last_review, now, self.settings.fsrs_reinforcement_cooldown_days
            ):
                # reinforcement cooldown can leave last_review a full window behind a
                # use that already landed inside it (PR #239 review comment):
                # last_accessed is the actual spacing signal, last_review only gates.
                anchor = last_accessed or last_review
                days_since = max((now - anchor).total_seconds() / 86400, 0.0)
                stability = lifecycle.reinforced_stability(
                    stability,
                    days_since,
                    growth_factor=self.settings.fsrs_growth_factor,
                    growth_exponent=self.settings.fsrs_growth_exponent,
                    spacing_cap=self.settings.fsrs_spacing_cap,
                    max_stability=self.settings.fsrs_max_stability,
                    initial_stability=self.settings.fsrs_initial_stability,
                )
                last_review = now

            access_count = row["access_count"] + 1

            conn.execute(
                "UPDATE nodes SET access_count = ?, last_accessed = ?, stability = ?, "
                "last_review = ? WHERE id = ?",
                (
                    access_count,
                    now.isoformat(),
                    stability,
                    last_review.isoformat() if last_review else None,
                    node_id,
                ),
            )

            # The markdown is the projection: it is set to the computed values, never
            # incremented from whatever it happened to hold.
            node.access_count = access_count
            node.last_accessed = now
            node.stability = stability
            node.last_review = last_review
            self.file_store.save(node)
```

The `anchor` expression keeps the base's exact shape (`last_accessed or last_review`, no `None`
guard) so the semantics are unchanged; only the source of the two values moves from the file to the
row. If they ever disagree, the row wins — which is the point.

Append to the method's docstring, after the existing lock-order paragraph:

```
        Issue #272: the claim's outcome commits with this write, so a reinforcement
        that never landed stays visible as state = 'pending' and
        run_reinforcement_retry repairs it. The new values are computed from the
        nodes row rather than from the loaded markdown, which makes the retry
        idempotent: os.replace cannot be rolled back and COMMIT runs after this
        body, so a failed COMMIT can leave the file one step ahead — recomputing
        from the row overwrites that phantom instead of compounding it. The
        markdown is a projection of the lifecycle state, not a second source of it.
```

- [ ] **Step 5: Update every call site**

```bash
grep -rn "_record_confirmed_use" src/ tests/
```

Five sites exist after Tasks 2 and 4. Each already has the claim's `whisper_log_id` in scope:

| Site | Change |
|---|---|
| `memory_engine.py:855` — `recall_node` | `self._record_confirmed_use(resolved_node_id, whisper_log_id=target_log_id)` |
| `memory_engine.py:2805` — `submit_feedback` | `self._record_confirmed_use(resolved_node_id, whisper_log_id=whisper_log_id)` |
| `session_watcher.py:623` — judge block | see below |
| `session_watcher.py` — heuristic block (Task 2) | same shape as the judge block |
| `memory_engine.py` — boot backfill (Task 4) | pass the `whisper_log_id` of the `signals` row it claimed |

`submit_feedback` needs one extra change first. Its own `whisper_log_id` parameter may be `None` on
the legacy fallback path, while the claim was taken on the id `_submit_feedback_locked` resolved
internally (`whisper_log_id = row["id"]`, just above its transaction). Re-resolving in the wrapper
could pick a *different* event than the claim did, so the resolved id is returned instead.

Widen `_submit_feedback_locked`'s return type (`:2814`):

```python
    ) -> tuple[str | None, bool, int | None, str]:
```

Its error return at `:2831`:

```python
            return None, False, None, error
```

And its success return at `:2917-2921`:

```python
        return (
            resolved_node_id,
            became_confirmed,
            whisper_log_id,
            f"Feedback recorded for node {resolved_node_id[:8]}...",
        )
```

Then in `submit_feedback` (`:2793`), unpack the fourth value and pass it through:

```python
        with self.db.transaction():
            resolved_node_id, became_confirmed, claimed_log_id, message = (
                self._submit_feedback_locked(
                    node_id=node_id,
                    signal=signal,
                    source=source,
                    whisper_log_id=whisper_log_id,
                )
            )
```

```python
        if became_confirmed:
            try:
                self._record_confirmed_use(
                    resolved_node_id, whisper_log_id=claimed_log_id
                )
            except Exception:
                logger.exception(
                    "confirmed-use reinforcement failed for node %s", resolved_node_id
                )
```

`claimed_log_id` cannot be `None` when `became_confirmed` is `True`: `_claim_confirmed_use` returns
`False` for a `None` id.

The session watcher's list at `session_watcher.py:573` currently loses the id. Change it to carry
the pair:

```python
    confirmed_claims: list[tuple[int, str]] = []
```

At `:610`, inside the `if engine._claim_confirmed_use(...)` block:

```python
                confirmed_claims.append((row["id"], row["node_id"]))
```

And the loop at `:623`:

```python
    for whisper_log_id, node_id in confirmed_claims:
        try:
            engine._record_confirmed_use(node_id, whisper_log_id=whisper_log_id)
        except Exception:
            logger.exception("confirmed-use reinforcement failed for node %s", node_id)
```

`row["id"]` is the `whisper_log` row id — the same value passed to `_claim_confirmed_use` on the
line above it.

- [ ] **Step 6: Write the sweeper**

Create `src/ormah/background/reinforcement_retry.py`:

```python
"""Retry confirmed-use reinforcements whose claim committed but never landed (#272).

_claim_confirmed_use takes a monotonic latch inside the caller's transaction, and
_record_confirmed_use runs after that transaction commits with its exception isolated.
Before #272 a transient failure there was permanent: the claim was taken, so nothing
retried. The claim now carries a state, and this job sweeps the rows still 'pending'.

'legacy_unknown' (written before the state column existed) and 'orphaned' (the node is
gone) are terminal and never swept.

Not LLM-gated, so it keeps working under ORMAH_LLM_PROVIDER=none.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# A claim taken seconds ago may still have its reinforcement in flight — the mutator
# runs after the claiming transaction commits. Matches the interval
# session_watcher_reconcile_interval_minutes uses for the equivalent reason.
_GRACE_MINUTES = 5

# Deliberately smaller than whisper_log_cleanup_batch_size (1000): every row here does
# file I/O under the memory lock, while that job is pure SQL.
_BATCH_SIZE = 200


def run_reinforcement_retry(engine) -> None:
    """Re-apply reinforcements for claims left unapplied."""
    try:
        rows = engine.db.conn.execute(
            """
            SELECT whisper_log_id, node_id
            FROM confirmed_use_claims
            WHERE state = 'pending'
              AND claimed_at < datetime('now', ?)
            ORDER BY claimed_at ASC
            LIMIT ?
            """,
            (f"-{_GRACE_MINUTES} minutes", _BATCH_SIZE),
        ).fetchall()

        if not rows:
            return

        repaired = 0
        for row in rows:
            # Isolated per row: one unreadable node must not abandon the rest of the
            # batch, exactly as the call sites isolate their own reinforcement.
            try:
                engine._record_confirmed_use(
                    row["node_id"], whisper_log_id=row["whisper_log_id"]
                )
                repaired += 1
            except Exception:
                logger.exception(
                    "reinforcement retry failed for node %s (whisper_log %s)",
                    row["node_id"],
                    row["whisper_log_id"],
                )

        logger.info(
            "Reinforcement retry: %d/%d claims repaired", repaired, len(rows)
        )
    except Exception:
        logger.exception("Reinforcement retry job failed")
```

- [ ] **Step 7: Register the job**

In `src/ormah/config.py`, add the setting next to the other intervals (after
`decay_interval_hours` at `:63`):

```python
    reinforcement_retry_interval_minutes: int = 60
```

and add it to the validator list at `:376-380`:

```python
    @field_validator(
        "auto_link_interval_minutes",
        "conflict_check_interval_minutes",
        "duplicate_check_interval_minutes",
        "auto_cluster_interval_minutes",
        "reinforcement_retry_interval_minutes",
    )
```

In `src/ormah/background/scheduler.py`, before `scheduler.start()`:

```python
    from ormah.background.reinforcement_retry import run_reinforcement_retry

    scheduler.add_job(
        tracked(tracker, "reinforcement_retry", run_reinforcement_retry, engine),
        "interval",
        minutes=s.reinforcement_retry_interval_minutes,
        id="reinforcement_retry",
        name="Reinforcement retry",
        misfire_grace_time=_MISFIRE_GRACE,
    )
```

In `src/ormah/api/routes_admin.py`, add one entry to each of the three structures:

```python
    "reinforcement_retry": ("ormah.background.reinforcement_retry", "run_reinforcement_retry"),
```

```python
    "reinforcement_retry": "Re-applies confirmed-use reinforcements whose claim committed but whose write never landed.",
```

and in `_SLEEP_CYCLE_ORDER`, immediately after `"decay_manager"`:

```python
    "reinforcement_retry",
```

It goes after `decay_manager` because a repaired reinforcement should be visible to the *next*
cycle's decay pass, not race the current one.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
python -m pytest tests/test_engine/test_confirmed_use_contract.py tests/test_background/test_reinforcement_retry.py -v
```

Expected: PASS, including every contract test Tasks 1–4 left green. A failure in contracts 9 or
10a–10f means the mutator change broke an existing guarantee — stop and report it.

- [ ] **Step 9: Full suite, lint, commit**

```bash
python -m pytest tests/ -q > /tmp/ormah-272-run.txt 2>&1; RC=$?
tail -20 /tmp/ormah-272-run.txt
echo "pytest exit=$RC"   # 0, or only Task 0 baseline IDs failed
make lint
```

```bash
git add src/ormah/index/schema.sql src/ormah/index/db.py \
        src/ormah/engine/memory_engine.py src/ormah/background/session_watcher.py \
        src/ormah/background/reinforcement_retry.py src/ormah/background/scheduler.py \
        src/ormah/config.py src/ormah/api/routes_admin.py \
        tests/test_engine/test_confirmed_use_contract.py \
        tests/test_background/test_reinforcement_retry.py
git commit -m "fix(lifecycle): the confirmed-use claim's promise becomes durable (#220 debt)

The claim committed inside the caller's transaction while the reinforcement ran
after it, exception isolated. The latch is monotonic, so one transient failure
lost the reinforcement permanently — and the mutator was not atomic with itself,
so a half-applied write left markdown and database diverged.

confirmed_use_claims gains a state: pending, applied, legacy_unknown, orphaned.
The mutator now computes the new lifecycle values FROM the nodes row rather than
by incrementing the markdown it loaded, which makes the write idempotent: a
failed COMMIT after os.replace leaves the file one step ahead, and the retry
recomputes the same target and overwrites it instead of compounding it. This is
convergence, not atomicity — os.replace cannot join a SQLite transaction.

Pre-existing claims become legacy_unknown, never applied. The premise of this fix
is that some claims lost their reinforcement; the old schema cannot tell those
from the successes, so recording them as applied would hide the very data loss
being repaired. The migration logs how many it found.

Calling file_store inside db.transaction() is safe in this method only: the
serialized decorator already holds _memory_operation_lock and FileStore shares
that RLock, so the call re-enters rather than inverting the memory->db order.

reinforcement_retry sweeps the pending claims past a 5-minute grace margin. It is
not LLM-gated, so it survives ORMAH_LLM_PROVIDER=none."
```

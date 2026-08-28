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

The overview's global constraint says never call `_record_confirmed_use` inside an open transaction,
because that would take `db_lock` before `memory_lock` and invert every serialized writer's order
(#220 §4.3). **That rule is correct for callers, and larger than necessary for the mutator's own
body.** Verified on the base:

- `FileStore` is constructed with the engine's **own** lock —
  `FileStore(settings.nodes_dir, self._memory_operation_lock)` at `memory_engine.py:109` and again
  at `:1424` — and `_memory_operation_lock` is a `threading.RLock` (`:108`).
- `@_serialized_memory_operation` (`:94-99`) acquires that lock before the body runs, so inside
  `_record_confirmed_use` the thread **already holds it**. A `file_store` call made from within
  `db.transaction()` therefore re-enters a lock it owns; it acquires nothing new and the memory→db
  order is unchanged.
- `Database.transaction` (`index/db.py:68-82`) is reentrant per thread and issues `ROLLBACK` only at
  depth 1, so the rollback this task relies on is real.

Nothing about the callers changes: they still call the mutator outside their own transaction.
`04-backfill.md`'s rule 2 stands untouched.

## The known limitation, stated so a reviewer does not have to find it

A process crash between `FileStore.save`'s successful `os.replace` and the transaction's `COMMIT`
leaves the markdown ahead of both the database and the claim. The sweeper then re-runs the mutator,
which reloads the already-incremented node and increments again: one event, two increments. This is
irreducible without two-phase commit, and is strictly better than today's outcome — permanent loss
plus permanent divergence. Do not "fix" it by adding a compensating read; that reintroduces deriving
state from the node, which `_claim_confirmed_use`'s docstring exists to prevent.

---

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_engine/test_confirmed_use_contract.py`:

```python
def _claim_row(engine, log_id, node_id):
    return engine.db.conn.execute(
        "SELECT claimed_at, reinforced_at FROM confirmed_use_claims "
        "WHERE whisper_log_id = ? AND node_id = ?",
        (log_id, node_id),
    ).fetchone()


def test_mutator_failure_leaves_no_residue(engine, monkeypatch):
    """#272 D5a: a failed save rolls back the claim mark AND the nodes row."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    with engine.db.transaction() as conn:
        engine._claim_confirmed_use(
            conn, log_id, target, signal=1, source="explicit", strength=1.0,
        )

    before = _snapshot(engine, target)

    def boom(node):
        raise OSError("disk full")

    monkeypatch.setattr(engine.file_store, "save", boom)
    with pytest.raises(OSError):
        engine._record_confirmed_use(target, whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, "the failed mutator left a partial write"
    assert _claim_row(engine, log_id, target)["reinforced_at"] is None, (
        "the claim was marked applied even though nothing was applied"
    )


def test_happy_path_commits_claim_row_and_markdown_together(engine):
    """#272 D5f: on success all three move."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    with engine.db.transaction() as conn:
        engine._claim_confirmed_use(
            conn, log_id, target, signal=1, source="explicit", strength=1.0,
        )

    before = _snapshot(engine, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)
    after = _snapshot(engine, target)

    assert after != before, "nothing was reinforced"
    assert after["file"] == after["db"], "markdown and database disagree"
    assert _claim_row(engine, log_id, target)["reinforced_at"] is not None


def test_mutator_is_at_most_once_on_a_marked_claim(engine):
    """#272 D5c: a second call on an applied claim is a no-op."""
    target = _make_nodes(engine, count=1)[0]
    log_id = _seed_whisper_log(engine, target)
    with engine.db.transaction() as conn:
        engine._claim_confirmed_use(
            conn, log_id, target, signal=1, source="explicit", strength=1.0,
        )
    engine._record_confirmed_use(target, whisper_log_id=log_id)

    after_first = _snapshot(engine, target)
    engine._record_confirmed_use(target, whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, "the second call reinforced again"


def test_missing_node_terminates_the_claim(engine):
    """#272 D5d: a deleted node must not leave the sweeper retrying forever.

    The claim is inserted directly for a node_id that has no markdown file. Only
    whisper_log_id carries a foreign key (PRAGMA foreign_keys=ON), so a claim can
    legitimately outlive its node — which is exactly the state being tested.
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

    assert _claim_row(engine, log_id, "ghost-node")["reinforced_at"] is not None, (
        "a claim for a deleted node stayed unapplied — the sweeper will retry it forever"
    )
```

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


def test_sweeper_reinforces_an_orphaned_claim(engine, seeded_claim):
    """#272 D5b: a claim the mutator never applied is repaired."""
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, node_id)

    run_reinforcement_retry(engine)

    row = engine.db.conn.execute(
        "SELECT reinforced_at FROM confirmed_use_claims WHERE whisper_log_id = ?",
        (log_id,),
    ).fetchone()
    assert row["reinforced_at"] is not None, "the sweeper did not mark the claim"
    assert _snapshot(engine, node_id) != before, "the sweeper marked but did not reinforce"


def test_sweeper_is_at_most_once_across_runs(engine, seeded_claim):
    """#272 D5c: running the sweeper twice reinforces once."""
    log_id, node_id, _ = seeded_claim
    _stale_claim(engine, log_id, node_id)

    run_reinforcement_retry(engine)
    after_first = _snapshot(engine, node_id)
    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) == after_first, "the second sweep reinforced again"


def test_sweeper_skips_claims_inside_the_grace_margin(engine, seeded_claim):
    """#272 D5b: a claim taken seconds ago may still be in flight — do not race it."""
    log_id, node_id, before = seeded_claim
    _stale_claim(engine, log_id, node_id, minutes_ago=0)

    run_reinforcement_retry(engine)

    assert _snapshot(engine, node_id) == before, "the sweeper raced an in-flight claim"


def test_sweeper_isolates_one_bad_node_from_the_batch(engine, seeded_claim, monkeypatch):
    """#272 D5b: one RAISING node must not abandon the rest of the batch.

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
def test_migration_stamps_preexisting_claims_as_reinforced(tmp_path):
    """#272 D5e: claims written before this task were ALREADY reinforced.

    Leaving them NULL would make the first sweep re-reinforce the whole history.
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
        "SELECT claimed_at, reinforced_at FROM confirmed_use_claims"
    ).fetchone()
    assert row["reinforced_at"] == row["claimed_at"], (
        "a pre-existing claim was left unmarked and will be re-reinforced"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_engine/test_confirmed_use_contract.py -k "residue or commits_claim_row or at_most_once_on_a_marked or terminates_the_claim or stamps_preexisting" -v
python -m pytest tests/test_background/test_reinforcement_retry.py -v
```

Expected: FAIL. The contract tests fail with
`TypeError: _record_confirmed_use() got an unexpected keyword argument 'whisper_log_id'` and
`OperationalError: no such column: reinforced_at`; the sweeper file fails at import with
`ModuleNotFoundError: No module named 'ormah.background.reinforcement_retry'`.

- [ ] **Step 3: Add the column, in the schema and in the migration**

In `src/ormah/index/schema.sql`, replace the `confirmed_use_claims` table at `:243-248`:

```sql
CREATE TABLE IF NOT EXISTS confirmed_use_claims (
    whisper_log_id INTEGER NOT NULL REFERENCES whisper_log(id) ON DELETE CASCADE,
    node_id        TEXT NOT NULL,
    claimed_at     TEXT NOT NULL,
    -- Issue #272: NULL means the claim was taken but the reinforcement it promised
    -- has not landed yet. The sweeper retries exactly these rows.
    reinforced_at  TEXT,
    PRIMARY KEY (whisper_log_id, node_id)
);
```

In `src/ormah/index/db.py`, inside `_migrate`, immediately after the
`CREATE INDEX IF NOT EXISTS idx_nodes_seq` line:

```python
            # Issue #272: confirmed_use_claims gains a completion state. Every claim
            # written before this migration was already reinforced by the old code
            # path, so they are stamped in the same transaction as the ALTER —
            # leaving them NULL would make the first sweep re-reinforce the entire
            # history of the store.
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
                conn.execute(
                    "UPDATE confirmed_use_claims SET reinforced_at = claimed_at"
                )

            # Partial index: the sweeper only ever selects the unapplied rows, which
            # are a vanishing fraction of the table.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_unreinforced "
                "ON confirmed_use_claims(claimed_at) WHERE reinforced_at IS NULL"
            )
```

`claim_cols` is checked for truthiness first: on a database old enough not to have the table at all,
`PRAGMA table_info` returns an empty list and the `ALTER` must not run — `schema.sql` creates it
below, already carrying the column.

- [ ] **Step 4: Make the mutator atomic**

In `src/ormah/engine/memory_engine.py`, replace `_record_confirmed_use`'s signature and the tail of
its body (`:2121`, and `:2170-2184` for the write block):

```python
    def _record_confirmed_use(self, node_id: str, *, whisper_log_id: int) -> None:
```

`whisper_log_id` is keyword-only and **required, with no default**, for the same reason the overview
gives for `strength` on `_claim_confirmed_use`: a default would let a future caller omit it and lose
durability in silence. Every reinforcement descends from a claim, and `_claim_confirmed_use` returns
`False` when `whisper_log_id is None`, so no call site can reach here without one.

Replace the early return for a missing node:

```python
        node = self.file_store.load(node_id)
        if node is None:
            # Issue #272: terminal, not silent. Without marking, the claim would stay
            # unapplied forever and the sweeper would retry a node that cannot come
            # back, every cycle. There is nothing to reinforce, so the promise is
            # discharged.
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE confirmed_use_claims SET reinforced_at = datetime('now') "
                    "WHERE whisper_log_id = ? AND node_id = ? AND reinforced_at IS NULL",
                    (whisper_log_id, node_id),
                )
            return
```

Replace the write block (`file_store.save` followed by the transaction) with a single transaction:

```python
        # Issue #272: the claim mark, the row update and the markdown write are one
        # act. If the save raises, the rollback undoes both updates and the sweeper
        # retries; if an update raises, the save never happens.
        #
        # Calling file_store inside db.transaction() is safe HERE and nowhere else:
        # @_serialized_memory_operation already holds _memory_operation_lock, and
        # FileStore was constructed with that same RLock (:109), so this re-enters a
        # lock this thread owns rather than acquiring db_lock before memory_lock.
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE confirmed_use_claims SET reinforced_at = datetime('now') "
                "WHERE whisper_log_id = ? AND node_id = ? AND reinforced_at IS NULL",
                (whisper_log_id, node_id),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                # Another runner applied this claim first. At-most-once, the same
                # shape _claim_confirmed_use uses. Nothing may sit between the UPDATE
                # and this read.
                return
            conn.execute(
                "UPDATE nodes SET access_count = ?, last_accessed = ?, stability = ?, "
                "last_review = ? WHERE id = ?",
                (
                    node.access_count,
                    node.last_accessed.isoformat(),
                    node.stability,
                    node.last_review.isoformat() if node.last_review else None,
                    node_id,
                ),
            )
            self.file_store.save(node)
```

Append to the method's docstring, after the existing lock-order paragraph:

```
        Issue #272: the claim's completion mark commits with this write, so a claim
        whose reinforcement never landed stays visible as reinforced_at IS NULL and
        run_reinforcement_retry repairs it. The one window that remains is a process
        crash between os.replace and COMMIT: the markdown is then ahead, and the
        retry produces a second increment for one event. Irreducible without 2PC.
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
retried. The claim now carries reinforced_at, and this job sweeps the rows where it is
still NULL.

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
            WHERE reinforced_at IS NULL
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

confirmed_use_claims gains reinforced_at, marked inside the mutator's own
transaction alongside the nodes UPDATE and the markdown save, so the three commit
or roll back together. Pre-existing claims are stamped by the migration: they were
already reinforced, and leaving them NULL would re-reinforce the whole store.

Calling file_store inside db.transaction() is safe in this method only: the
serialized decorator already holds _memory_operation_lock and FileStore shares
that RLock, so the call re-enters rather than inverting the memory->db order.

reinforcement_retry sweeps the claims left NULL past a 5-minute grace margin. It
is not LLM-gated, so it survives ORMAH_LLM_PROVIDER=none."
```

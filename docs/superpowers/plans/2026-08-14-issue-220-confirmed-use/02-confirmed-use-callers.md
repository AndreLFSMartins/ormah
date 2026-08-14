# Task 2: Qualified positive feedback records confirmed use

**Files:**
- Modify: `src/ormah/index/schema.sql` (one new table, `confirmed_use_claims`)
- Modify: `tests/test_engine/test_confirmed_use_contract.py` (append the confirmed-use cases)
- Modify: `src/ormah/engine/memory_engine.py` (`submit_feedback`, `_submit_feedback_locked`, one new module constant, one new helper `_claim_confirmed_use`)
- Modify: `src/ormah/background/session_watcher.py` (`_record_whisper_usage_signals`, the `auto_llm_judge` block only)
- Modify: `tests/test_background/test_session_watcher.py` (one helper plus six cases)

**Interfaces:**
- Consumes: `MemoryEngine._record_confirmed_use(self, node_id: str) -> None` from Task 1. Nothing else.
- Produces: `MemoryEngine._claim_confirmed_use(self, conn, whisper_log_id, node_id, *, signal, source) -> bool` — the single confirmed-use gate, shared by `submit_feedback` and the watcher.
- Produces: `MemoryEngine._submit_feedback_locked(...) -> tuple[str | None, bool, str]` — now returns `(resolved_node_id, became_confirmed, message)` instead of just the message. `resolved_node_id` is `None` and `became_confirmed` is `False` on the error paths. Its only caller is `submit_feedback`.

All line numbers are from `upstream/main` (`a28837b`) **before Task 1's edits**, which shift them. Locate code by the quoted snippet.

---

## Why this task was rewritten — read before Step 1

The second council round (2026-08-14) **refuted the gate the first round introduced**. The
first version computed `became_confirmed` by reading `affinity` twice around the writes.
Both peers, independently, showed that cannot work, and the code confirms it.

**Measured on `upstream/main`:**

- `affinity` unique is `(node_id, whisper_log_id) WHERE whisper_log_id IS NOT NULL`
  (`db.py:389`, created by migration code — not in `schema.sql`).
- `submit_feedback` does `INSERT INTO affinity ... ON CONFLICT DO NOTHING`
  (`memory_engine.py:2547`), then `UPDATE affinity SET signal = ?, source = ?`
  **only when `source == "explicit"`** (`:2569`).
- The watcher's `_insert_affinity` is `ON CONFLICT DO NOTHING` with no update
  (`session_watcher.py:385`).

Two opposite failures follow:

| Failure | Sequence | Result |
| --- | --- | --- |
| **False negative** | watcher writes `auto_heuristic` affinity, then `submit_feedback(+1, implicit)` | INSERT is a no-op, no UPDATE (source is not `explicit`), so the row keeps `source = auto_heuristic`. The gate stays false and a legitimate reinforcement is **lost silently**. |
| **False positive** | explicit `+1` → `-1` → `+1` | The `UPDATE` rewrites the single row each time, so the gate goes false→true **twice**. One event reinforces twice. |

**`signals` is not the alternative.** Its unique key is
`(whisper_log_id, signal_type, source)` (`schema.sql:189`) — `polarity` is absent — and the
row is inserted `ON CONFLICT DO NOTHING` and **never updated** (`:2575`). So explicit `-1`
followed by explicit `+1` collides, the stored polarity stays `-1`, and a real confirmation
would never fire. `affinity` fails as a false positive; `signals` fails as a permanent
false negative. Both peers confirmed this.

**The fix is a dedicated latch.** One row per `(whisper event, node)` pair, taken by
whichever qualified positive arrives first, and never deleted. Monotonic by construction:
negatives cannot clear it, a polarity cycle cannot re-arm it, and it is indifferent to
whatever `affinity` and `signals` do with their keys.

**The contract is at-most-once, not exactly-once.** This is a decision, not an oversight.
`_record_confirmed_use` writes markdown to disk and then updates SQLite; the file write
cannot join the transaction and cannot be rolled back. Both peers agreed no ordering of
claim-versus-mutator delivers exactly-once, and the alternative — a durable
pending/applied protocol with a reconciliation loop — was rejected twice. The reason is
`#220` itself: this issue exists to stop Ormah manufacturing retention, so **reinforcing
twice is worse than losing a reinforcement**. A recovery loop would invert the issue's
purpose. Misses are logged and accepted.

That is also why the claim goes **inside** the transaction and the mutator runs **after**
COMMIT. The reverse order — mutator first, claim after — lets two concurrent confirmations
both pass the check and both reinforce. `@_serialized_memory_operation` serializes the
read-modify-write (so `access_count` stays correct) but does not enforce once-per-event.

And the claim is **never deleted on failure**: `_record_confirmed_use` calls
`file_store.save` *before* the SQLite `UPDATE`, so a delete-and-retry would increment the
markdown file a second time.

---

- [ ] **Step 1: Add the latch table to the schema**

In `src/ormah/index/schema.sql`, next to the other feedback tables:

```sql
-- Issue #220: at-most-once latch for confirmed use. One row per (whisper event,
-- node) pair, taken by whichever qualified positive signal arrives first, and
-- never deleted. This is deliberately NOT derived from affinity or signals:
-- affinity is mutable (explicit feedback UPDATEs the single row per event, so a
-- +1/-1/+1 cycle would confirm twice) and the signals unique key omits polarity
-- (so -1 followed by +1 collides and a real confirmation would never fire).
--
-- whisper_log_id is NOT NULL because SQLite permits repeated NULLs in a PRIMARY
-- KEY, which would defeat the latch entirely.
--
-- ON DELETE CASCADE, not SET NULL: the other whisper_log_id foreign keys use
-- SET NULL because their columns are nullable. On a NOT NULL column SET NULL
-- would make whisper_log_cleanup's DELETE fail with a constraint violation.
-- CASCADE also keeps this table bounded by whisper_log's own retention.
--
-- node_id deliberately carries NO foreign key. It would buy nothing: the only
-- writer is _claim_confirmed_use, which receives a node id submit_feedback has
-- already resolved against the store, so the constraint would guard against a
-- bug the code cannot commit. It would cost real scope, though — several
-- existing feedback tests fabricate node ids that were never inserted into
-- nodes, which is a legitimate pattern here, and a reference would force them
-- all to change. A claim outliving its node is harmless: the latch only ever
-- prevents a second reinforcement, and the whisper_log CASCADE above already
-- bounds the table.
CREATE TABLE IF NOT EXISTS confirmed_use_claims (
    whisper_log_id INTEGER NOT NULL REFERENCES whisper_log(id) ON DELETE CASCADE,
    node_id        TEXT NOT NULL,
    claimed_at     TEXT NOT NULL,
    PRIMARY KEY (whisper_log_id, node_id)
);
```

**No foreign key on `node_id` — measured, not assumed.** An earlier draft of this plan gave it
`REFERENCES nodes(id) ON DELETE CASCADE` for symmetry. That broke 16 pre-existing tests in
`tests/test_engine/test_submit_feedback.py` and `tests/test_whisper_health.py`, which fabricate
node ids that never reach the `nodes` table — a legitimate pattern for exercising the feedback
path without creating nodes. Rather than change fixtures in two files this issue has no business
touching, the reference was dropped. It protected nothing the code could get wrong.

**Why `schema.sql` and not a migration.** `Database.init_schema` (`db.py:84-89`) runs
`executescript(schema.sql)` followed by `_migrate()`, and `MemoryEngine.__init__` calls it
on every startup (`memory_engine.py:96`). A brand-new table needs only
`CREATE TABLE IF NOT EXISTS` there — it reaches existing databases on their next start.
This is **not** the trap the `affinity` migration documents: that one needed `_migrate`
because it changed an *existing* table's unique constraint, which `IF NOT EXISTS` silently
skips.

`PRAGMA foreign_keys=ON` is set on every connection (`db.py:36`), so the CASCADE is live,
and `whisper_log_cleanup` deletes from `whisper_log` by id (`whisper_log_cleanup.py:60`).
`whisper_log.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so ids are never reused and a
cascaded delete cannot resurrect a claimable event.

Verify the table lands on an existing database:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -c "
from ormah.config import Settings
from ormah.index.db import Database
import tempfile, pathlib
d = pathlib.Path(tempfile.mkdtemp())
db = Database(d / 'x.db'); db.init_schema()
db2 = Database(d / 'x.db'); db2.init_schema()   # second init on an existing file
print(db2.conn.execute(
    \"SELECT sql FROM sqlite_master WHERE name='confirmed_use_claims'\"
).fetchone()[0])
" )
```

Expected: the `CREATE TABLE` statement printed, no error on the second `init_schema`.

- [ ] **Step 2: Write the failing confirmed-use tests for feedback**

Append to `tests/test_engine/test_confirmed_use_contract.py`:

```python
# --- Confirmed-use contracts ----------------------------------------------

def _seed_whisper_log(engine, node_id, prompt="what about caching?"):
    """Insert a whisper_log row so submit_feedback can resolve one.

    submit_feedback attaches feedback to a whisper/recall event; without a row
    it returns an error string instead of recording anything.
    """
    engine.recall_search(prompt, limit=10)
    row = engine.db.conn.execute(
        "SELECT id FROM whisper_log WHERE node_id = ? ORDER BY id DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    assert row is not None, "no whisper_log row was created — check the surface used"
    return row["id"]


def test_recall_node_confirms_only_the_requested_node(engine):
    """Contract 7: recall_node confirms the node asked for, never its neighbours."""
    from ormah.models.node import CreateNodeRequest

    target, _ = engine.remember(CreateNodeRequest(
        content="caching architecture target node", title="Target", type="fact", tier="working",
    ))
    neighbour, _ = engine.remember(CreateNodeRequest(
        content="caching architecture neighbour node", title="Neighbour", type="fact",
        tier="working",
    ))
    # GraphIndex exposes no add_edge — only .conn plus read methods. This is the
    # same raw-SQL idiom tests/test_engine/test_whisper_context.py already uses.
    engine.graph.conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, weight, created) "
        "VALUES (?, ?, 'related_to', 1.0, '2026-01-01T00:00:00Z')",
        (target, neighbour),
    )

    before_target = _snapshot(engine, target)
    before_neighbour = _snapshot(engine, neighbour)

    engine.recall_node(target)

    assert _snapshot(engine, target) != before_target, "recall_node did not confirm its node"
    assert _snapshot(engine, neighbour) == before_neighbour, (
        "recall_node confirmed a neighbour — only the requested node counts"
    )


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge"])
def test_qualified_positive_feedback_confirms_use(engine, source):
    """Contract 8: the three allowlisted sources confirm, with signal == 1."""
    ids = _make_nodes(engine, count=2)
    target, other = ids[0], ids[1]
    log_id = _seed_whisper_log(engine, target)

    before_target = _snapshot(engine, target)
    before_other = _snapshot(engine, other)

    engine.submit_feedback(target, signal=1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) != before_target, (
        f"positive {source} feedback did not confirm use"
    )
    assert _snapshot(engine, other) == before_other, "an unrelated node was confirmed"


def test_auto_heuristic_positive_does_not_confirm(engine):
    """Contract 9: auto_heuristic is excluded pending #218 — fail-closed."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=1, source="auto_heuristic", whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, "auto_heuristic must not confirm use"


@pytest.mark.parametrize("source", ["explicit", "implicit", "auto_llm_judge", "auto_heuristic"])
def test_negative_feedback_never_confirms(engine, source):
    """Contract 10: -1 is evidence about the prompt/node pair, never a confirmed use."""
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)
    engine.submit_feedback(target, signal=-1, source=source, whisper_log_id=log_id)

    assert _snapshot(engine, target) == before, (
        f"negative {source} feedback changed lifecycle fields"
    )


# --- Idempotency contracts (second council round: the latch, not affinity) ---

def test_replaying_the_same_positive_feedback_confirms_once(engine):
    """Contract 10a: one confirmed-use event reinforces at most once.

    affinity and signals both use ON CONFLICT DO NOTHING, so a replayed request
    records no new evidence yet still returns success. Reinforcing on every call
    would let a retried tool call or a double-click manufacture retention.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "replaying the same positive feedback reinforced twice"
    )


def test_negative_then_positive_feedback_confirms(engine):
    """Contract 10b: a first-time positive confirms even after a negative.

    The negative claims nothing (it does not qualify), so the later positive is
    still the event's first confirmation. This is the case a naive 'did the
    signals INSERT add a row?' gate gets wrong: the unique key is
    (whisper_log_id, signal_type, source) with no polarity, so the second call
    hits ON CONFLICT DO NOTHING even though it is a genuine first confirmation.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=-1, source="explicit", whisper_log_id=log_id)
    after_negative = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) != after_negative, (
        "the event's first qualified positive did not confirm use"
    )


def test_second_source_on_an_already_confirmed_event_does_not_reconfirm(engine):
    """Contract 10c: the event is confirmed once, not once per source.

    This is the mirror failure: source is part of the signals unique key, so an
    implicit-positive followed by an explicit-positive DOES insert a second
    signals row. The event was already claimed; it must not reinforce again.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=log_id)
    after_first = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first, (
        "a second positive source reconfirmed an already-confirmed event"
    )


def test_polarity_cycle_confirms_once(engine):
    """Contract 10d: +1 / -1 / +1 reinforces at most once — not twice.

    This is the false positive that killed the affinity-derived gate. affinity
    has one row per (node_id, whisper_log_id) and explicit feedback UPDATEs its
    signal in place, so reading affinity would see false->true twice and
    reinforce twice. The claim latch is never deleted, so the third call takes
    nothing.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)
    after_first_positive = _snapshot(engine, target)

    engine.submit_feedback(target, signal=-1, source="explicit", whisper_log_id=log_id)
    engine.submit_feedback(target, signal=1, source="explicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) == after_first_positive, (
        "a polarity cycle reinforced the same event twice"
    )


def test_unqualified_affinity_does_not_block_a_later_qualified_positive(engine):
    """Contract 10e: a pre-existing auto_heuristic row must not swallow a real use.

    This is the false negative that killed the affinity-derived gate. The
    affinity unique key is (node_id, whisper_log_id) and only explicit feedback
    UPDATEs the row, so an auto_heuristic positive makes a later implicit
    positive a no-op INSERT that leaves source = auto_heuristic. Reading
    affinity would keep the gate false forever and lose the reinforcement in
    silence. The claim latch does not consult affinity at all.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    engine.submit_feedback(target, signal=1, source="auto_heuristic", whisper_log_id=log_id)
    after_heuristic = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=log_id)

    assert _snapshot(engine, target) != after_heuristic, (
        "a prior auto_heuristic affinity row blocked a genuine confirmed use"
    )


def test_reinforcement_failure_does_not_fail_the_feedback_call(engine):
    """Contract 10f: a raising mutator is logged, not propagated.

    The route returns submit_feedback's value directly, so an exception after
    COMMIT would 500 a call whose affinity and signals rows are already durably
    written. ZeroDivisionError is the realistic case, not a contrived one:
    stability is Field(default=1.0, ge=0.0), so zero is legal, and the mutator
    divides by it. Under the at-most-once contract this reinforcement is lost —
    that is the accepted cost, but it must be a logged miss, not an API error.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    log_id = _seed_whisper_log(engine, target)

    before = _snapshot(engine, target)

    with patch.object(
        engine, "_record_confirmed_use", side_effect=ZeroDivisionError("float division by zero")
    ):
        message = engine.submit_feedback(
            target, signal=1, source="explicit", whisper_log_id=log_id
        )

    assert "Feedback recorded" in message, "a failed reinforcement broke the feedback contract"
    assert _snapshot(engine, target) == before, "lifecycle advanced despite the failure"

    # The evidence itself is committed — this is about lifecycle, not observability.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ? AND node_id = ?",
        (log_id, target),
    ).fetchone()
    assert affinity is not None, "the feedback evidence was rolled back"
```

`test_reinforcement_failure_does_not_fail_the_feedback_call` needs
`from unittest.mock import patch` — check whether the module already imports it before
adding the line.

**Walk the contracts against the latch, one row at a time.** `_claim_confirmed_use`
returns `True` only for the caller whose `INSERT ... ON CONFLICT DO NOTHING` actually
inserts:

| Case | claim exists before? | qualifies? | INSERT result | reinforces? |
| --- | --- | --- | --- | --- |
| 8 — first qualified `+1` | no | yes | inserted | **yes** |
| 9 — `auto_heuristic +1` | no | no (source) | not attempted | no |
| 10 — any `-1` | no | no (signal) | not attempted | no |
| 10a — `+1` replayed | yes | yes | conflict, 0 rows | no |
| 10b — `-1` then `+1` | no (the `-1` claimed nothing) | yes | inserted | **yes** |
| 10c — implicit `+1` then explicit `+1` | yes | yes | conflict, 0 rows | no |
| 10d — `+1 / -1 / +1` | yes (from the first `+1`) | yes | conflict, 0 rows | no |
| 10e — `auto_heuristic +1` then implicit `+1` | no (heuristic claimed nothing) | yes | inserted | **yes** |

Every row is decided by the claim table alone. Nothing reads `affinity` or `signals`, so
neither their unique keys nor their mutability can move the outcome — which is the whole
point of the rewrite.

- [ ] **Step 3: Run them and confirm which fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected: contract 7 **PASSES** (`recall_node` already confirmed its node; this is a
regression pin). Contract 8 **FAILS** for all three sources — feedback records affinity and
signals but never reinforces. Contracts 10b and 10e **FAIL** for the same reason (nothing
confirms, so nothing changes). Contracts 9, 10, 10a, 10c, 10d and 10f **PASS** vacuously,
because nothing confirms yet; they become discriminating once Steps 4 and 5 land, which is
exactly why they are written now. 10f is vacuous for its own reason: before Step 5,
`submit_feedback` never calls `_record_confirmed_use`, so patching it with a `side_effect`
patches a method nothing invokes and every assertion already holds.

Record the exact pass/fail split you observe. If 10a, 10c or 10d fails at this point,
something already reinforces and the premise of Task 1 is wrong — stop and investigate
rather than proceeding.

- [ ] **Step 4: Add the allowlist and the claim helper**

In `src/ormah/engine/memory_engine.py`, add the constant near the other module-level
constants at the top of the file:

```python
# Issue #220: the only feedback sources that count as confirmed use. Fail-closed —
# anything not listed here, and every negative signal, does not reinforce.
# auto_heuristic is excluded pending #218 signal calibration.
_CONFIRMED_USE_SOURCES = frozenset({"explicit", "implicit", "auto_llm_judge"})
```

Add the helper as a method on `MemoryEngine`, next to the feedback helpers:

```python
    def _claim_confirmed_use(
        self,
        conn,
        whisper_log_id: int | None,
        node_id: str,
        *,
        signal: int,
        source: str,
    ) -> bool:
        """Take the at-most-once confirmed-use claim for one (event, node) pair.

        Returns True only for the caller that actually inserts the claim, so a
        whisper event reinforces at most once no matter how many qualified
        positives arrive, from how many sources, in what order.

        The claim is a durable monotonic latch, deliberately independent of
        affinity and signals. affinity is mutable — explicit feedback UPDATEs the
        single row per (node_id, whisper_log_id) — so deriving confirmation from
        it makes a +1/-1/+1 cycle confirm twice, and makes a pre-existing
        auto_heuristic row swallow a later qualified positive. The signals unique
        key omits polarity and is never updated, so deriving it from there makes
        -1 followed by +1 never confirm at all.

        Fail-closed: an unqualified signal, a source outside the allowlist, or a
        missing whisper_log_id claims nothing.

        MUST be called inside the caller's transaction. Claiming after the
        mutator instead would let two concurrent confirmations both pass and
        both reinforce; @_serialized_memory_operation keeps the read-modify-write
        correct but cannot enforce once-per-event.
        """
        if whisper_log_id is None or signal != 1 or source not in _CONFIRMED_USE_SOURCES:
            return False
        conn.execute(
            """
            INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT DO NOTHING
            """,
            (whisper_log_id, node_id),
        )
        return conn.execute("SELECT changes()").fetchone()[0] == 1
```

**`SELECT changes()` is the codebase's own idiom, not a guess.** `_insert_usage_signal`
(`session_watcher.py:371`) ends with exactly
`return conn.execute("SELECT changes()").fetchone()[0]` for the same
`ON CONFLICT DO NOTHING` question. It reads the last DML statement's row count, so nothing
may run between the `INSERT` and the read — here they are adjacent.

- [ ] **Step 5: Gate `submit_feedback` on the claim, reinforce after the transaction**

Replace `submit_feedback` (`:2498-2512`):

```python
    def submit_feedback(
        self,
        node_id: str,
        signal: int,
        source: str = "explicit",
        whisper_log_id: int | None = None,
    ) -> str:
        """Record feedback while preventing retention from deleting its event."""
        with self.db.transaction():
            resolved_node_id, became_confirmed, message = self._submit_feedback_locked(
                node_id=node_id,
                signal=signal,
                source=source,
                whisper_log_id=whisper_log_id,
            )
        # Reinforcement runs after the transaction commits: db.transaction() holds a
        # process-level lock for its whole body, and _record_confirmed_use does file
        # I/O. Calling it inside would also take db_lock before memory_lock, inverting
        # the order every serialized writer uses.
        #
        # Isolated, and never propagated. The affinity and signals rows are already
        # durably committed and the route returns this value straight to the caller,
        # so raising here would report a failure for evidence that was recorded. The
        # contract is at-most-once (see 00-overview.md): the claim stays taken and
        # this reinforcement is simply lost, as a logged miss.
        if became_confirmed:
            try:
                self._record_confirmed_use(resolved_node_id)
            except Exception:
                logger.exception(
                    "confirmed-use reinforcement failed for node %s", resolved_node_id
                )
        return message
```

`logger` is already bound at `memory_engine.py:47` — no new import.

In `_submit_feedback_locked`, change the return type annotation and both return statements.
The signature (`:2514-2520`) becomes:

```python
    def _submit_feedback_locked(
        self,
        node_id: str,
        signal: int,
        source: str = "explicit",
        whisper_log_id: int | None = None,
    ) -> tuple[str | None, bool, str]:
```

The early error return (`:2532-2533`) becomes:

```python
        if error is not None:
            return None, False, error
```

Inside the existing `with self.db.transaction() as conn:` block (`:2544`), take the claim.
Put it **first**, above the affinity `INSERT`, so it is decided before any mutable row is
touched:

```python
        with self.db.transaction() as conn:
            became_confirmed = self._claim_confirmed_use(
                conn,
                whisper_log_id,
                resolved_node_id,
                signal=signal,
                source=source,
            )
```

The final return (`:2612`) becomes:

```python
        return (
            resolved_node_id,
            became_confirmed,
            f"Feedback recorded for node {resolved_node_id[:8]}...",
        )
```

`_submit_feedback_locked` has exactly one caller (`submit_feedback`), so no other site needs
updating. Verify:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "_submit_feedback_locked" src/ tests/ )
```

- [ ] **Step 6: Run the feedback contracts — all must pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected: all pass, including 9, 10, 10a, 10c and 10d, which now genuinely discriminate.
If 10d or 10e still fails, the gate is reading affinity somewhere — re-read Step 5.

- [ ] **Step 7: Write the failing session-watcher tests**

Append to `tests/test_background/test_session_watcher.py`, modelled on the existing
`test_llm_judge_promotes_used_verdict`.

First the shared helper — these tests must honour the same dual-store contract as Task 1's,
reading all four lifecycle fields from the markdown file **and** the SQLite row. Reading
only `file_store` (as the first draft did) would pass while a DB-only or file-only write
rotted the other store:

```python
_LIFECYCLE_FIELDS = ("access_count", "last_accessed", "stability", "last_review")


def _lifecycle(engine, node_id):
    """The four lifecycle fields, from the markdown file and the SQLite row."""
    node = engine.file_store.load(node_id)
    row = engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    return {
        "file": tuple(getattr(node, f) for f in _LIFECYCLE_FIELDS),
        "db": tuple(row[f] for f in _LIFECYCLE_FIELDS),
    }
```

```python
def test_llm_judge_used_verdict_records_confirmed_use(engine, tmp_path):
    """Issue #220: a positive auto_llm_judge verdict confirms use for its node."""
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-confirms-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-confirms-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    after = _lifecycle(engine, node_id)
    assert after != before, "the judged-used node was not confirmed"
    assert after["file"][0] == before["file"][0] + 1, "access_count did not advance by one"
    assert after["db"][0] == after["file"][0], "file and DB disagree on access_count"

    # The signal and affinity rows must still be written — confirmed use is
    # additional behaviour, not a replacement for observability.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert affinity is not None
    assert affinity["source"] == "auto_llm_judge"


def test_llm_judge_unused_verdict_does_not_record_confirmed_use(engine, tmp_path):
    """A negative verdict is affinity evidence only — it never reinforces."""
    prompt = "What deployment marker should we use?"
    response = "Ignore that; we are switching to a completely different scheme."
    transcript_path = tmp_path / "judge-unused-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-unused-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "unused",
            "confidence": 0.9,
            "reason": "The answer rejects the injected guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    assert _lifecycle(engine, node_id) == before, "an unused verdict changed lifecycle fields"
```

And contract 12 — the heuristic path produces a **positive** polarity that must still not
confirm. Modelled on the existing `test_record_whisper_usage_signal_promotes_clear_reference`,
which exercises that path with the judge off:

```python
def test_heuristic_positive_does_not_record_confirmed_use(engine, tmp_path):
    """Issue #220: auto_heuristic yields polarity 1 but never confirms use.

    The heuristic path is excluded pending #218 signal calibration. This is the
    case that matters: it is positive, so only the source keeps it out.
    """
    prompt = "How should we solve feedback collection?"
    response = "The right fix is the transcript watcher mines feedback usage approach."
    transcript_path = tmp_path / "heuristic-no-confirm-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="The transcript watcher mines feedback usage from completed transcripts.",
        type="fact",
        title="Transcript watcher mines feedback usage",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="heuristic-no-confirm-session", prompt=prompt,
    )

    before = _lifecycle(engine, node_id)

    recorded = _record_whisper_usage_signals(engine, transcript)

    # The heuristic signal is still recorded — this is about lifecycle, not observability.
    assert recorded == 1
    signal = engine.db.conn.execute(
        "SELECT * FROM signals WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert signal["polarity"] == 1

    assert _lifecycle(engine, node_id) == before, "auto_heuristic confirmed use — it must not"

    # And it claimed nothing, so a later qualified positive can still confirm.
    claim = engine.db.conn.execute(
        "SELECT 1 FROM confirmed_use_claims WHERE whisper_log_id = ?", (whisper_log_id,)
    ).fetchone()
    assert claim is None, "the heuristic path took a confirmed-use claim"
```

This test must pass both before and after Step 9 — it pins that the change to the judge
block did not leak into the heuristic block. The two paths use separate transactions
(`:498` and `:561`), so the isolation is structural, but structure is an argument and this
is a measurement.

Three more, all from council findings:

```python
def test_replaying_the_judge_does_not_reconfirm(engine, tmp_path):
    """Issue #220: a second pass over the same transcript reinforces nothing.

    has_llm_judge already excludes an event that was judged before, so the
    replay should not even reach the confirm loop — and the claim latch stops it
    a second time if it does. Two independent guards, deliberately.
    """
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-replay-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-replay-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)
    after_first = _lifecycle(engine, node_id)

    with patch(_LLM_PATCH, return_value=llm_response):
        _record_whisper_usage_signals(engine, transcript)

    assert _lifecycle(engine, node_id) == after_first, (
        "replaying the judge reinforced the same event twice"
    )


def test_feedback_claim_makes_the_judge_a_noop(engine, tmp_path):
    """Issue #220 cross-caller contract: one event, one reinforcement, two callers.

    This is the case has_llm_judge cannot cover: it only looks at signals whose
    source is transcript_watcher_llm_judge, so it is blind to feedback submitted
    through MCP. Before the claim latch, an implicit +1 followed by a positive
    judge verdict on the same whisper event reinforced it twice.
    """
    prompt = "What deployment marker should we use?"
    response = "That guidance is the right one for the rollout."
    transcript_path = tmp_path / "judge-cross-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact",
        title="Blue deployment rollback marker",
    ))
    whisper_log_id = _insert_injected_whisper_log(
        engine, node_id=node_id, session_id="judge-cross-session", prompt=prompt,
    )
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    engine.submit_feedback(node_id, signal=1, source="implicit", whisper_log_id=whisper_log_id)
    after_feedback = _lifecycle(engine, node_id)

    llm_response = json.dumps({
        "verdicts": [{
            "whisper_log_id": whisper_log_id,
            "verdict": "used",
            "confidence": 0.88,
            "reason": "The answer endorses the injected deployment guidance.",
        }]
    })
    with patch(_LLM_PATCH, return_value=llm_response):
        recorded = _record_whisper_usage_signals(engine, transcript)

    # The judge's own signal and affinity rows are still written — observability
    # is not what the claim gates.
    assert recorded >= 1, "the judge signal was not recorded"
    assert _lifecycle(engine, node_id) == after_feedback, (
        "the judge reinforced an event already confirmed through submit_feedback"
    )


def test_one_failing_node_does_not_skip_the_rest_of_the_batch(engine, tmp_path):
    """Issue #220: reinforcement is isolated per node, for any exception.

    The judge signals and the claims are already committed when this loop runs,
    so an escaping exception would abort the slice and — because has_llm_judge is
    now set and the claims are taken — the retry would never reinforce these
    events. The later nodes would lose their only chance at confirmation.

    ZeroDivisionError is the realistic case, not a contrived one: stability is
    Field(default=1.0, ge=0.0), so zero is legal, and the mutator divides by it.
    """
    prompt = "What deployment marker should we use?"
    response = "Both of those notes are exactly right."
    transcript_path = tmp_path / "judge-batch-session.jsonl"
    _write_turn_jsonl(transcript_path, prompt, response)
    transcript = parse_transcript(transcript_path)

    first_id, _ = engine.remember(CreateNodeRequest(
        content="Use blue deployment markers when rollback plans need quick visual checks.",
        type="fact", title="Blue deployment rollback marker",
    ))
    second_id, _ = engine.remember(CreateNodeRequest(
        content="Roll back within one minute when the marker check fails.",
        type="fact", title="Rollback timing",
    ))
    log_ids = [
        _insert_injected_whisper_log(
            engine, node_id=node_id, session_id="judge-batch-session", prompt=prompt,
        )
        for node_id in (first_id, second_id)
    ]
    engine.settings.llm_provider = "ollama"
    engine.settings.feedback_llm_judge_enabled = True

    before_second = _lifecycle(engine, second_id)

    real_mutator = engine._record_confirmed_use

    def failing_for_first(node_id):
        if node_id == first_id:
            raise ZeroDivisionError("float division by zero")
        return real_mutator(node_id)

    llm_response = json.dumps({
        "verdicts": [
            {"whisper_log_id": log_id, "verdict": "used", "confidence": 0.9,
             "reason": "endorsed"}
            for log_id in log_ids
        ]
    })
    with patch(_LLM_PATCH, return_value=llm_response), \
         patch.object(engine, "_record_confirmed_use", side_effect=failing_for_first):
        recorded = _record_whisper_usage_signals(engine, transcript)

    # Both nodes go through the heuristic pass unreferenced (the response text
    # matches neither node's id/title/content), then both go to the judge pass:
    # 2 heuristic signals + 2 judge signals.
    assert recorded == 4, "the signals themselves must still be recorded"
    assert _lifecycle(engine, second_id) != before_second, (
        "the first node's failure skipped the second node's reinforcement"
    )
```

The batch test only discriminates if `first_id` is reinforced **before** `second_id`.
`confirmed_node_ids` is appended in `judge_records` order, which follows the query's row
order — if that turns out not to put `first_id` first, make the ordering explicit in the
implementation rather than weakening the assertion.

- [ ] **Step 8: Run them and watch the positive cases fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v \
    -k "confirmed_use or noop or replaying_the_judge or one_failing_node" )
```

Expected: `test_llm_judge_used_verdict_records_confirmed_use` **FAILS** (`access_count`
unchanged — nothing confirms yet) and `test_one_failing_node_does_not_skip_the_rest_of_the_batch`
**FAILS** too (the second node is never reinforced, because nothing reinforces).
`test_feedback_claim_makes_the_judge_a_noop` **PASSES** vacuously at this point — after
Step 5 the feedback side already reinforces and the judge side does not, so the assertion
holds for the wrong reason; it becomes discriminating after Step 9. The unused-verdict,
heuristic and replay tests **PASS**, also vacuously.

- [ ] **Step 9: Gate the watcher on the same claim, reinforce after the block**

In `src/ormah/background/session_watcher.py`, `_record_whisper_usage_signals`, the
`auto_llm_judge` block at `:561`. Replace:

```python
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )

    return recorded
```

with:

```python
    confirmed_node_ids: list[str] = []
    with engine.db.transaction() as conn:
        for record in judge_records:
            row = record["row"]
            recorded += _insert_usage_signal(
                conn,
                row,
                transcript,
                signal_type=record["signal_type"],
                polarity=record["polarity"],
                strength=record["strength"],
                source=_LLM_JUDGE_SOURCE,
                evidence=record["evidence"],
                created=now_iso,
            )
            if record["polarity"] in (1, -1):
                _insert_affinity(
                    conn,
                    row,
                    signal=record["polarity"],
                    source=_LLM_JUDGE_AFFINITY_SOURCE,
                    confirmed_at=now_iso,
                )
            # Issue #220: the same at-most-once claim submit_feedback takes, not a
            # parallel polarity check. has_llm_judge only sees this watcher's own
            # signal source, so it is blind to feedback submitted through MCP — the
            # claim is what makes one whisper event reinforce once across both
            # callers. Note _insert_affinity must run first: it reads changes()
            # nowhere, but the claim helper does, so nothing may sit between its
            # INSERT and its read.
            if engine._claim_confirmed_use(
                conn,
                row["id"],
                row["node_id"],
                signal=record["polarity"],
                source=_LLM_JUDGE_AFFINITY_SOURCE,
            ):
                confirmed_node_ids.append(row["node_id"])

    # Issue #220: reinforcement runs after the transaction commits. db.transaction()
    # holds a process-level lock for its whole body and _record_confirmed_use writes
    # markdown to disk, so doing this inside would stall every writer in the process
    # for the length of N file saves — and would take db_lock before memory_lock,
    # inverting the order every serialized writer uses.
    #
    # Each node is isolated: the signals and claims above are already committed, so
    # letting one node's failure escape would abort the ingest slice, skip every later
    # node, and leave both has_llm_judge set and the claims taken — nothing would ever
    # retry them. Failures here are logged, never raised. This is the at-most-once
    # contract, stated in 00-overview.md.
    for node_id in confirmed_node_ids:
        try:
            engine._record_confirmed_use(node_id)
        except Exception:
            logger.exception("confirmed-use reinforcement failed for node %s", node_id)

    return recorded
```

`row["id"]` is the whisper_log id — `_insert_usage_signal` passes exactly that into the
`whisper_log_id` column (`:357`).

The `auto_heuristic` block at `:498` is **not** modified. The two paths do not share a
transaction, and `_claim_confirmed_use` would reject `auto_heuristic` anyway — the source
is outside the allowlist. Two independent reasons; the test in Step 7 measures both.

**`except Exception`, not `except OSError`** (first council round). `OSError` alone does not
cover what this mutator can raise. **Verified on `upstream/main`:** `MemoryNode.stability`
is `Field(default=1.0, ge=0.0)` (`models/node.py:59`), so zero is a legal value, and the
mutator computes `math.exp(-days_since / node.stability)` (`memory_engine.py:1946`) — a
real `ZeroDivisionError` on any node whose stability has reached zero. Add `sqlite3.Error`
from the DB update and validation errors from markdown parsing, and a narrow catch would
still let one bad node take out the rest of the batch. Confirm the module already binds
`logger`; `session_watcher.py` does, so no new import is needed beyond that check.

**What this does not fix, stated honestly.** The contract is **at-most-once**. A hard
process kill, or any exception, between the `COMMIT` and the reinforcement loses that
event's reinforcement permanently — the claim is taken, `has_llm_judge` is set, and nothing
retries. A DB failure after `file_store.save` can also leave the markdown file and the
SQLite row disagreeing on the lifecycle fields until the next successful write to that node.

The earlier claim that "the next confirmed use restores it" was **wrong**, and the first
council round quantified the cost: with `S = 1` and `growth = 1.5`, uses on day 1 and day 2,
dropping the day-1 update yields about **2.24** stability instead of **3.07**. The node
stays permanently below its true trajectory.

This is accepted, not overlooked. Exactly-once would need a durable pending/applied
protocol with a reconciliation loop, rejected in both council rounds for the same reason:
`#220` exists to stop Ormah manufacturing retention, so a double reinforcement is worse
than a missed one, and a recovery loop would invert the issue's purpose.

- [ ] **Step 10: Run the watcher tests — all must pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_background/test_session_watcher.py -v )
```

Expected: the six new tests pass and every pre-existing watcher test still passes — in
particular `test_llm_judge_promotes_used_verdict`, whose `recorded == 2` assertion must be
unaffected, since neither the claim nor the reinforcement changes the returned count.

- [ ] **Step 11: Full suite against the baseline, then lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort ) \
  > /private/tmp/claude-501/220-task2.txt
diff /private/tmp/claude-501/220-baseline-ids.txt /private/tmp/claude-501/220-task2.txt
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && make lint )
```

Expected: no output from `diff`, clean lint.

- [ ] **Step 12: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add -A && \
  git commit -m "fix(lifecycle): record confirmed use from qualified positive feedback

recall_node was the only caller reinforcing a memory. Positive feedback wrote
affinity and signal rows but never advanced the lifecycle, so deliberate
confirmation counted for nothing.

submit_feedback and the session watcher's auto_llm_judge path now reinforce
through one shared gate: a claim on the new confirmed_use_claims table, keyed
(whisper_log_id, node_id) and taken with INSERT ... ON CONFLICT DO NOTHING
inside the caller's transaction. Only the caller that inserts the row
reinforces, so a whisper event reinforces at most once across both callers, any
number of sources and any order of arrival. The allowlist is fail-closed:
signal == 1 with a source in explicit, implicit or auto_llm_judge, which leaves
out auto_heuristic (pending #218) and every negative signal.

The claim is a dedicated latch rather than a state read of existing rows,
because neither candidate works. affinity is mutable — its unique key is
(node_id, whisper_log_id) and explicit feedback UPDATEs that single row — so
deriving confirmation from it makes a +1/-1/+1 cycle reinforce twice and lets a
pre-existing auto_heuristic row swallow a later qualified positive. The signals
unique key omits polarity and its rows are never updated, so deriving it from
there makes an explicit -1 followed by +1 never confirm at all. The claim is
monotonic and consults neither.

Reinforcement runs after the enclosing transaction commits rather than inside
it: db.transaction() holds a process-level lock for its whole body, the mutator
writes markdown to disk, and calling it inside would take db_lock before
memory_lock. Both callers isolate it with except Exception and log the failure
instead of raising — the evidence rows are already committed, and the route
returns submit_feedback's value directly.

The delivery contract is at-most-once, deliberately. The mutator's markdown
write cannot join the SQLite transaction, so no ordering of claim and mutator
yields exactly-once. A crash or exception after COMMIT loses that event's
reinforcement permanently and the node's stability stays below its true
trajectory. Exactly-once would require a durable pending/applied protocol and a
reconciliation loop; that is rejected, because #220 exists to stop manufacturing
retention and reinforcing twice is worse than missing once.

Refs #220" )
```

- [ ] **Step 13: Report, and do not open the PR**

Push the branch to your fork:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && git push fork fix/220-confirmed-use )
```

**Stop there.** The PR must not be opened while draft PR [#229](https://github.com/r-spade/ormah/pull/229)
still declares `Closes #220–#223`. Report the branch as ready and state that the PR is
blocked on #229 being closed as superseded.

When it is unblocked, the PR body must mention two things so a reviewer does not read
either as an oversight:

- `FileStore.touch_access` (`src/ormah/store/file_store.py:145`) is a namesake left
  untouched on purpose.
- The delivery contract is at-most-once, and why exactly-once was rejected.

# Durable Reinforcement After the Confirmed-Use Claim — Design

**Date:** 2026-08-28
**Base:** `fix/218-signal-strength-ladder` (`40d8ff0`) — never `local-main`
**Lands as:** Task 5 of the #272 plan (`docs/superpowers/plans/2026-08-27-issue-272-heuristic-confirmed-use/`)
**Origin:** debt inherited from #220, surfaced as finding 🟡-3 of the final-plan council run
`5e788498-2670a15c-f7431e74`

## The defect

`_claim_confirmed_use` takes an at-most-once latch **inside the caller's transaction**. That
transaction commits. Only afterwards does `_record_confirmed_use` run, outside the transaction, and
every call site wraps it in a bare `except` that logs and swallows:

| Call site | Address on the base |
|---|---|
| `recall_node` | `src/ormah/engine/memory_engine.py:855` |
| `submit_feedback` | `src/ormah/engine/memory_engine.py:2805` |
| session watcher, judge block | `src/ormah/background/session_watcher.py:625` |
| session watcher, heuristic block | new, created by Task 2 of #272 |
| boot backfill | new, created by Task 4 of #272 |

The claim is a durable monotonic latch with no undo. Nothing retries it. **One transient filesystem
failure defeats the reinforcement permanently, for that node.** Commit `759f209`
(`fix(lifecycle): reinforcement survives zero stability and mutator failure`) already answered
the #220 council on this surface by isolating the exception better — not by making the promise
durable. This design closes it.

The defect has two halves, and both are in scope:

- **(a) Total loss** — the mutator raises before writing anything. The claim says "reinforced", the
  node was never touched.
- **(b) Half-applied** — inside `_record_confirmed_use`, `file_store.save(node)` writes the markdown
  and only *then* does `db.transaction()` open for the `UPDATE nodes`. If the save succeeds and the
  UPDATE fails, markdown and database diverge, and a naive retry re-increments `access_count` in the
  markdown on top of an increment that already landed.

## What already holds, and was verified rather than assumed

- `FileStore` is constructed with the engine's **own** `_memory_operation_lock`
  (`memory_engine.py:109`, `:1424`), and that lock is a `threading.RLock`. Inside
  `_record_confirmed_use` the decorator already holds it, so a `file_store` call made from within
  `db.transaction()` re-enters a lock the thread already owns — it acquires nothing new and cannot
  invert the memory→db order.
- `Database.transaction` (`src/ormah/index/db.py:68-82`) is reentrant per thread and issues
  `ROLLBACK` only at depth 1.
- `FileStore.save` is atomic on disk: `mkstemp` → `os.write` → `os.fsync` → `os.replace`, with the
  temp file unlinked on any `BaseException`. The markdown is never left partial.
- `confirmed_use_claims` is `(whisper_log_id, node_id, claimed_at)` with a composite primary key
  and `ON DELETE CASCADE` on `whisper_log_id` (`src/ormah/index/schema.sql:243-248`). **On the base
  it carries no state column** — which is exactly why "claimed" and "applied" are today the same
  fact, and why the legacy rows cannot be classified after the event.
- `whisper_log_cleanup` deletes only rows with `was_injected = 0`, while `_claim_confirmed_use`
  inserts only for `was_injected = 1`. The two sets are disjoint, so the `ON DELETE CASCADE` cannot
  silently eat a pending claim. This was checked because it would otherwise have been a hole in the
  retry.

## Architecture

### Half (b): the database becomes authoritative, and the retry becomes idempotent

**This is not atomicity, and the plan must not call it that.** `FileStore.save` performs an
irreversible `os.replace`, and `Database.transaction` issues its `COMMIT` *after* the body returns
(`index/db.py:68-82`). No ordering inside that body can enrol the filesystem in the transaction: a
`COMMIT` that fails — disk full, `SQLITE_BUSY`, I/O error — leaves the markdown advanced while the
`nodes` row and the claim roll back. Codex raised this in round 1 of the plan council
(run `98918652-c2f6a005-fc06a07a`, HIGH, confidence 0.99) and it is correct.

What closes it is **convergence, not atomicity**: the mutator computes the new lifecycle values from
the `nodes` row, inside the transaction, instead of from the markdown it loaded.

```python
with self.db.transaction() as conn:
    conn.execute(
        "UPDATE confirmed_use_claims SET state = 'applied', reinforced_at = datetime('now') "
        "WHERE whisper_log_id = ? AND node_id = ? AND state = 'pending'",
        (whisper_log_id, node_id),
    )
    if conn.execute("SELECT changes()").fetchone()[0] != 1:
        return
    row = conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    # ... compute the reinforced values from `row`, never from the loaded node ...
    conn.execute("UPDATE nodes SET ... WHERE id = ?", ...)
    node.access_count, node.last_accessed, node.stability, node.last_review = computed
    self.file_store.save(node)
```

Why this converges. Say the database holds `access_count = v`. A run saves the markdown at `v+1`,
then its `COMMIT` fails: markdown `v+1`, database `v`, claim back to `pending`. The retry reads the
database — still `v` — computes `v+1`, and writes **both** to `v+1`. The phantom markdown increment
is overwritten rather than compounded. One event produces exactly one increment, however many times
the write is retried.

The markdown is a projection of the lifecycle state, not a second source of it. This is already true
in practice: `decay_manager` and `importance_scorer` read the `nodes` row, never the file.

- If `save` raises, the rollback undoes both updates — the claim returns to `pending` and is retried.
- If either update raises, the save never happens.
- The `changes() != 1` guard makes the mutator at-most-once against concurrent runners, in the same
  shape `_claim_confirmed_use` already uses.

**Signature.** `_record_confirmed_use(self, node_id, *, whisper_log_id: int)` — keyword-only and
**required, with no default**, for the reason the #272 overview gives for `strength` on
`_claim_confirmed_use`: a default would let a future caller omit it and lose durability in silence.
The type is `int`, not `int | None`: every reinforcement descends from a claim, and
`_claim_confirmed_use` returns `False` when the id is `None`, so no call site can arrive here
without one.

**A missing node is a terminal state, and says so.** Today `if node is None: return` returns without
raising. With the claim carrying state, that would leave it `pending` forever and the sweeper
retrying a node that cannot come back. The claim moves to `orphaned` — deliberately **not**
`applied`, because nothing was applied, and calling it applied is the same lie the migration finding
below is about.

**What remains, stated precisely.** The markdown can still be transiently ahead of the database
between a successful `os.replace` and a failed or interrupted `COMMIT`. That state is *recoverable*,
not permanent: the next run converges both stores. The residual exposure is a window in which a
reader of the markdown file — not of the `nodes` row — sees a lifecycle value one step ahead. No
subsystem reads the file for lifecycle, so nothing consumes it today.

### Half (a): the sweeper

New module `src/ormah/background/reinforcement_retry.py`, exposing
`run_reinforcement_retry(engine)`, following `run_decay`'s shape — an outer `try/except` so a
failure never escapes into the scheduler:

- Select claims where `state = 'pending'` and `claimed_at` is older than a **5-minute grace
  margin**, so the sweeper never races a reinforcement that is still in flight — the same interval
  `session_watcher_reconcile_interval_minutes` already uses for the equivalent reason.
  `legacy_unknown` and `orphaned` are terminal and never selected.
- **200 rows per run.** Deliberately smaller than `whisper_log_cleanup_batch_size` (1000), because
  every row here does file I/O under the memory lock while that job is pure SQL.
- For each row, call `_record_confirmed_use(node_id, whisper_log_id=...)` with the exception
  isolated per row, so one bad node does not abandon the rest of the batch.
- The job is **not LLM-gated**, so it survives `ORMAH_LLM_PROVIDER=none` — unlike the four
  sleep-cycle jobs that silently return `{"skipped": "llm_disabled"}`.

Registration follows the existing pattern exactly: `scheduler.add_job` with
`minutes=s.reinforcement_retry_interval_minutes`, an entry in `routes_admin._TASK_RUNNERS`,
`_TASK_DESCRIPTIONS` and `_SLEEP_CYCLE_ORDER`, and the setting added to `config.py` under the
`_interval_minutes_positive` validator (`>= 1`).

### Schema migration, and the legacy rows

`confirmed_use_claims` gains two columns: `reinforced_at TEXT`, and

```sql
state TEXT NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending', 'applied', 'legacy_unknown', 'orphaned'))
```

plus a partial index on `state = 'pending'`, which is the only set the sweeper selects.

**The pre-existing rows become `legacy_unknown`, never `applied`.** The first draft of this design
stamped them `reinforced_at = claimed_at` on the reasoning that "every claim in the store was
already reinforced". Codex refuted that in round 1 (HIGH, confidence 0.99) and was right: the
premise of this whole task is that some claims committed and then lost their reinforcement. Those
are precisely the rows the defect produced, they are indistinguishable from the successes under the
old schema, and stamping them `applied` would hide the data loss the task exists to repair —
permanently.

This is not hypothetical. `confirmed_use_claims` is present in `upstream/main` and the package has
published releases (PyPI, latest 0.14.11), so real stores carry legacy claims of unknown outcome.

`legacy_unknown` is terminal for the sweeper — it does not re-reinforce them, because the
overwhelming majority *were* applied and re-running them would be mass over-reinforcement of a latch
whose entire purpose is at-most-once. What changes is that the unknown stays **visible and
countable** instead of being overwritten with a false success. The migration logs how many rows it
marked, so the size of the historical gap is a measurement rather than a guess, and deciding what to
do about them is a separate question this task deliberately does not answer.

## Testing

Test-driven, each test observed failing before its implementation:

1. **Mutator failure leaves no residue** — patch `file_store.save` to raise; assert the claim is
   still `pending`, the `nodes` row is unchanged, and the markdown is unchanged.
2. **A failed COMMIT does not inflate the counter** — patch the connection so `COMMIT` raises after
   the save; the markdown ends ahead, the claim returns to `pending`, and the retry converges both
   stores to exactly one increment. This is the test the first draft was missing, and it is the one
   that proves the convergence claim.
3. **The sweeper reinforces a pending claim** — seed an old `pending` claim; after the job, the node
   is reinforced and the claim is `applied`.
4. **The sweeper is at-most-once** — running it twice changes nothing the second time.
5. **The sweeper skips the grace margin** — a claim taken seconds ago is not swept.
6. **One raising node does not abandon the batch** — an injected failure on the first row still
   leaves the second repaired.
7. **A missing node ends `orphaned`** — a claim for a deleted node is terminal and not picked up
   again, and its state is `orphaned`, not `applied`.
8. **The migration marks legacy rows `legacy_unknown`** — pre-existing claims are neither swept nor
   recorded as successes, and the count is logged.
9. **The happy path agrees** — claim `applied`, `nodes` row and markdown all carry the same values.

## Amendments to the #272 plan

Two edits to `00-overview.md`, both narrow:

1. The global constraint *"Never modify `_record_confirmed_use`'s body, and never call it inside an
   open transaction"* is rescoped to **Tasks 1–4**, with a note recording why Task 5 may reorder the
   body: the shared `RLock` makes the file-store call inside the transaction a re-entry, not an
   acquisition, so the memory→db order the constraint protects is preserved. The constraint remains
   correct and unchanged for every call site that does not already hold the memory lock.
2. The task order table gains Task 5, depending on Tasks 2, 3 and 4 — it adjusts every call site of
   `_record_confirmed_use`, including the two that Tasks 2 and 4 create.

Rule 2 of `04-backfill.md` (*"Reinforcement runs after the transaction commits"*) is untouched: the
backfill still calls the mutator outside its own transaction. What changes is what happens **inside**
the mutator.

## Out of scope

- Reopening how eligibility is decided. `_claim_confirmed_use`'s deliberate independence from
  `affinity` and `signals` stands; nothing here derives state from those tables.
- The `00-overview.md` line-count overrun — 121 lines before these amendments, 128 after, against a
  100-line rule. Pre-existing and made worse here; flagged, not fixed, since it is not what this
  task is for.
- What to do about the `legacy_unknown` rows. This design makes the historical gap visible and
  measurable; closing it needs evidence that does not exist yet, and belongs to its own issue.

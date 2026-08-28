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
  and `ON DELETE CASCADE` on `whisper_log_id` (`src/ormah/index/schema.sql:243-248`). **It carries
  no state column** — which is exactly why "claimed" and "applied" are today the same fact.
- `whisper_log_cleanup` deletes only rows with `was_injected = 0`, while `_claim_confirmed_use`
  inserts only for `was_injected = 1`. The two sets are disjoint, so the `ON DELETE CASCADE` cannot
  silently eat a pending claim. This was checked because it would otherwise have been a hole in the
  retry.

## Architecture

### Half (b): the mutator becomes atomic

`_record_confirmed_use` reorders its body so the claim mark, the row update and the markdown write
are one transactional act:

```python
with self.db.transaction() as conn:
    conn.execute(
        "UPDATE confirmed_use_claims SET reinforced_at = datetime('now') "
        "WHERE whisper_log_id = ? AND node_id = ? AND reinforced_at IS NULL",
        (whisper_log_id, node_id),
    )
    if conn.execute("SELECT changes()").fetchone()[0] != 1:
        return
    conn.execute("UPDATE nodes SET ... WHERE id = ?", ...)
    self.file_store.save(node)
```

- If `save` raises, the rollback undoes both updates — the claim stays unmarked and is retried.
- If either update raises, the save never happens.
- The `changes() != 1` guard makes the mutator itself at-most-once, in the same shape
  `_claim_confirmed_use` already uses. Two concurrent runners cannot both reinforce one claim.

**Signature.** `_record_confirmed_use(self, node_id, *, whisper_log_id: int | None)` — keyword-only
and **required, with no default**, for the reason the #272 overview gives for `strength` on
`_claim_confirmed_use`: a default would let a future caller omit it and lose durability in silence.

**A missing node is a terminal state.** Today `if node is None: return` returns without raising.
With the mark inside the transaction that would leave the claim `NULL` forever and the sweeper
retrying it every cycle. The method now marks the claim and returns: there is nothing to reinforce,
and a deleted node does not come back. This is what removes the need for an `attempts` column.

**Known limitation, irreducible without two-phase commit.** A process crash between the successful
`os.replace` and the `COMMIT` leaves the markdown ahead of both the database and the claim. The
sweeper then re-runs the mutator, which reloads the already-incremented node and increments again:
one event produces two increments. This is strictly better than today's outcome (permanent loss plus
permanent divergence), but it is over-reinforcement and is accepted knowingly, not overlooked.

### Half (a): the sweeper

New module `src/ormah/background/reinforcement_retry.py`, exposing
`run_reinforcement_retry(engine)`, following `run_decay`'s shape — an outer `try/except` so a
failure never escapes into the scheduler:

- Select claims where `reinforced_at IS NULL` and `claimed_at` is older than a **5-minute grace
  margin**, so the sweeper never races a reinforcement that is still in flight — the same interval
  `session_watcher_reconcile_interval_minutes` already uses for the equivalent reason.
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

### Schema migration

`ALTER TABLE confirmed_use_claims ADD COLUMN reinforced_at TEXT`, plus a partial index on
`reinforced_at IS NULL` so the sweeper's select stays cheap as the table grows.

**The migration must stamp the rows that already exist**
(`UPDATE confirmed_use_claims SET reinforced_at = claimed_at` for every pre-existing row, in the
same transaction as the `ALTER`). Every claim in the store today was already reinforced; leaving
them `NULL` would make the first sweep re-reinforce the entire history. This is the most dangerous
single line in the task.

## Testing

Test-driven, each test observed failing before its implementation:

1. **Mutator failure leaves no residue** — patch `file_store.save` to raise; assert the claim is
   still `reinforced_at IS NULL`, the `nodes` row is unchanged, and the markdown is unchanged.
2. **The sweeper reinforces an orphaned claim** — seed an old claim with `reinforced_at IS NULL`;
   after the job, the node is reinforced and the claim is marked.
3. **The sweeper is at-most-once** — running it twice changes nothing the second time.
4. **A missing node terminates the claim** — a claim for a deleted node ends marked, and is not
   picked up again.
5. **The migration does not re-reinforce history** — pre-existing claims are stamped by the `ALTER`
   and ignored by the first sweep.
6. **The happy path commits together** — claim mark, `nodes` row and markdown all agree.

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
- The `00-overview.md` line-count overrun (121 lines against the 100-line rule). Pre-existing, and
  these amendments will push it further; flagged, not fixed, since it is not what this task is for.

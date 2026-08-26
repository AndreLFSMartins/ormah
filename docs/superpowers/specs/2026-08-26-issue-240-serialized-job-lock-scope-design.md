# Issue #240 — scope `L_mem` to the apply step, not the whole run

**Date:** 2026-08-26
**Issue:** [#240](https://github.com/r-spade/ormah/issues/240) — `bug(concurrency): @serialized_memory_job holds L_mem for a whole run`
**Island:** `fix/240-serialized-job-lock-scope` @ `ormah-wt-240`, cut from `upstream/main`
**Status:** design approved, ready for planning

---

## 1. Problem

`@serialized_memory_job` holds `L_mem` (`MemoryEngine._memory_operation_lock`) for the entire
duration of a background job. The same `RLock` guards every foreground mutator and every
`FileStore` call, so one long maintenance run makes the whole write side unanswerable.

Measured on a single local install (2026-08-18, `llm_provider=ollama`):

| Observation | Value |
|---|---|
| Real `POST /agent/remember`, parked behind a 30 min 43 s `auto_linker` run | **1 503 509 ms** (25 min 3 s) |
| Synthetic `POST /agent/connect` probe | `http=000` after 600 s — no server response at all |
| `index_updater` (60 s interval) | **184 consecutive** `maximum number of running instances reached` |
| `index_updater` cold scan, 3 303 node files, `llm_provider=none` | **34 531,9 ms**; steady incremental **494,8 ms** every 60 s |

The last row matters most for shipped defaults: a default install carries a smaller version of the
same contention with no LLM involved at all, scaling with file count.

### Premise corrections made during design

Three claims inherited from the issue did not survive verification. They are recorded because two
of them changed the plan.

1. **`delete_node_guarded` does not exist.** The issue names "the `delete_node_guarded`-style
   in-transaction guard pattern" as existing precedent. `grep -rn "guarded" src/` returns zero
   matches in `src/`. The pattern is *proposed*, not established. **(verified)**
2. **#223 is no longer un-PR'd.** The issue (2026-08-18) argued urgency from "#223 is the only one
   of the four without a PR yet". PR **#257** is open, `MERGEABLE`, `REVIEW_REQUIRED`, and carries
   `tests/test_engine/test_recall_concurrency.py`, whose docstring names the global lock as its
   correctness proof. The coupling moved from a spec sentence into a test. **(verified)**
3. **`L_db` is also a global mutex.** `Database.transaction()` (`index/db.py:62-81`) holds a global
   `RLock` for the whole transaction, and nobody complains about it. Global exclusion is therefore
   not the disease. **Unbounded hold duration under exclusion is.** **(verified)**

---

## 2. The invariant, restated

`L_mem` protects exactly one thing, and its own docstring says which: *"Keep a background mutation
from overlapping a full graph restore."* The destructive window is four lines —
`backup.py:441-444`, `rmtree(target)` then `move(...)` per source dir. Outside it, `L_mem` guards
nothing the primitives underneath do not already guard.

**Verified:** all seven decorated jobs mutate exclusively through primitives that already lock at
the right granularity — `engine.remember/connect/update_node/execute_merge`
(`@_serialized_memory_operation`), `engine.file_store.load/save` (`@_serialized_store_operation`,
the *same* lock), and `engine.db.transaction()` (`L_db` + `BEGIN IMMEDIATE`).

So `@serialized_memory_job` contributes **no per-operation atomicity**. It contributes exactly one
thing — whole-run atomicity relative to a restore — and pays for it with unbounded write starvation.

That decomposes into two guarantees:

**(i) No mutation interleaves with the file swap itself.** Survives for free under this design: the
swap runs under exclusive `memory_operation()`, and every job `file_store.save()` takes `L_mem` per
call. A write lands wholly before or wholly after the swap.

**(ii) No stale result is applied.** A job that computed "link X to Y" against the pre-restore graph
must not apply it after the swap. *This* is what whole-run exclusion buys today, and what the epoch
replaces.

### The caveat that shapes the mechanism

Guarantee (i) is **not** entirely free. `engine.db.transaction()` takes `L_db`, **not** `L_mem`, so
a DB-only job write does not block during the swap. Worse, a write landing between the end of the
swap and `reload_restored_graph`'s `rebuild_index()` is **silently overwritten** by the rebuild —
not corrupted, lost. Whole-run exclusion prevents even that today.

Therefore the epoch check cannot be a loose `if` before the mutation. **The check and the mutation
must be atomic with respect to the restore.**

---

## 3. Mechanism

```python
class MemoryEngine:
    _restore_epoch: int                     # bumped in reload_restored_graph

    @contextmanager
    def memory_operation_at(self, epoch):   # replaces the job decorator
        with self._memory_operation_lock:   # same L_mem, now per apply step
            if self._restore_epoch != epoch:
                raise RestoredUnderfoot     # snapshot is stale: abort the run
            yield
```

Each job reads the epoch on entry and wraps **every apply step** — including DB-only ones — in
`memory_operation_at(epoch)`. Hold time drops from the run's duration to milliseconds.

**Acquisition order stays `L_mem → L_db`**, identical to every other path, consistent with #207's
fix and with the hierarchy #211 wants documented.

**On epoch change, abort the run — do not skip the item.** If the epoch moved, the job's entire
snapshot is stale, not one row of it. The job returns on its next interval.

**The epoch bump is atomic for free:** `reload_restored_graph` is already
`@_serialized_memory_operation`, so incrementing there happens under exclusive `L_mem`.

### Convention this completes

`importance_scorer._commit_updates_chunked` already carries this philosophy for `L_db`, and says so:
*"Apply updates in bounded write transactions so a full-store batch never holds the write lock long
enough to stall foreground writes."* That care is **entirely defeated** by the
`@serialized_memory_job` on line 44 of the same file. This design does not introduce a new
philosophy; it finishes one that is already here, half-applied.

---

## 4. Scope

### In

- The seven jobs lose `@serialized_memory_job` and gain per-apply-step epoch-guarded acquisition.
- `run_decay` revalidates tier inside its own apply step (debt this change itself creates — see §5).
- `ingest_conversation` splits extract (unlocked) from apply (short lock), with dedup revalidation.

### Out — each with a reason, not an omission

- **`index_updater` / the `FileStore` scan.** It is the highest-risk item: #207's fix deliberately
  hoisted that scan above the write transaction for lock-order reasons (`index/builder.py:79-81`).
  Touching it requires changing `FileStore` locking, which is shared with all eleven engine
  mutators, and reopens the lock-order question #207 closed. It deserves its own issue and its own
  lock-order review, not a ride on a job-semantics change. **Consequence, stated plainly: this PR
  does not fix the default-install baseline** (~495 ms every 60 s, 34,5 s cold). #240 stays
  partially open on that point.
- **Finding 2 — task pause does not survive restart.** Root cause is a missing APScheduler jobstore
  (`background/scheduler.py:26` uses the default `MemoryJobStore`; `routes_admin.py:199` derives
  `paused` from `job.next_run_time`). Different cause, own issue.
- **Finding 3 — `SIGTERM` ignored while holding `L_mem`.** Root cause is absent cooperative
  cancellation. Different cause, own issue. This design shortens the window but does not add
  cancellation.
- **#238 (cross-process exclusion).** Deferred. This design is intra-process and forecloses nothing
  for it. **Noted (verified):** `cli.py:503` restores via `_backup_service().restore(...)` with no
  `memory_operation()` guard at all — a separate OS process, where an in-process `RLock` could not
  help anyway. The invariant is enforced only on the server-side cloud restore path
  (`protection.py:1831`). This design does not change that, and must not claim to.

---

## 5. Per-file changes

**`src/ormah/background/memory_lock.py`** — same purpose, new contents. `serialized_memory_job` is
removed. Two things take its place:

- `RestoredUnderfoot(Exception)` — defined **here**, and imported by `memory_engine.py`, keeping the
  dependency direction the codebase already has (`background` owns the job-side vocabulary; the
  engine raises it). No new import cycle: `memory_engine` does not otherwise import from
  `background`, so this must be verified during implementation and, if it would cycle, the exception
  moves to `memory_engine.py` and `memory_lock.py` imports it instead.
- `restore_aware_job(job)` — a decorator that reads `engine.restore_epoch` on entry, passes it to
  the job, and catches `RestoredUnderfoot` to end the run cleanly (logged, not raised into
  APScheduler). Jobs therefore keep a decorator; what changes is that it no longer *holds* anything —
  it only supplies the epoch and defines abort behaviour.

The module docstring states what the lock actually guarantees instead of implying whole-run coverage.

**`src/ormah/engine/memory_engine.py`** — three additions, one removal:

- `_restore_epoch: int` in `__init__`, beside the lock (~:103).
- `memory_operation_at(epoch)`, sibling of `memory_operation()` (:549).
- epoch increment in `reload_restored_graph` (:1329).
- remove `@_serialized_memory_operation` from `ingest_conversation` (:2404). Nothing else there
  changes: `_extract_memories_llm` (:2425) becomes unlocked, and `self.remember(req, ...)` (:2478)
  is **already** `@_serialized_memory_operation`, locking per node. The debt created is dedup —
  `_is_duplicate_memory` is now read outside the lock, so two concurrent ingests can both pass.
  Revalidated inside the apply step.

**The seven jobs** — each drops the decorator and wraps its apply steps:

| Job | Apply point | Acquisitions per run |
|---|---|---|
| `auto_linker` | `:286-310` (transaction + `file_store.save`) | one per pair |
| `conflict_detector` | `:246-286` | one per pair |
| `consolidator` | `:136-177` | one per cluster |
| `duplicate_merger` | `:341`, `:372-374` | one per pair |
| `importance_scorer` | `file_store.save` at `:130-134` + each `_commit_updates_chunked` chunk | one per node + one per chunk |
| `auto_cluster` | `save` at `:49-53` + each chunk at `:60` | one per node + one per chunk |
| `decay_manager` | `:78` | one per demoted node |

**The decay tier revalidation lives entirely inside `decay_manager.py`** — deliberately. Inside the
`memory_operation_at(epoch)` wrapping line 78, re-read the node's `tier`/`stability`/`last_accessed`
and recompute retrievability; skip if it no longer qualifies.

Two reasons for that placement: it changes no engine API, and `decay_manager.py` is a file **PR #257
does not touch** (#257 touches `tests/test_background/test_decay_manager.py`, not the module). So the
piece that resolves the collision with #257 is precisely the piece that does not conflict with it.
Merge conflicts stay confined to `memory_engine.py` and `consolidator.py`, and are mechanical.

---

## 6. Interaction with PR #257 (#223)

Removing whole-run exclusion from `run_decay` opens a **third outcome** that #257's
`test_recall_concurrency.py` does not admit: decay snapshots `tier='working'` (`:34-37`), a
promotion lands, and decay demotes to `archival` anyway via `update_node` (`:78`). That test asserts
`final.tier is Tier.working`. It would **fail**.

That is good news — the test is this change's canary. The problem is sequencing: the test lives on
another open PR, so it does **not exist** on this island (cut from `upstream/main`, per
FORK-WORKFLOW rule 2).

**Decision: independent, then notify.** This island writes its own decay-revalidation test against
`upstream/main` and does not depend on #257. The two PRs merge in any order. After the work exists,
comment on #257 and/or #240 explaining that `test_recall_concurrency`'s concurrency proof should be
re-anchored on the in-transaction revalidation rather than on the global lock — and that with this
PR its assertions remain valid. **Any such comment is confirmed with André before posting.**

---

## 7. Testing

The measured symptom is temporal; the cause is structural. Asserting "the write returned in under
X ms" would be flaky and would measure the machine. Asserting "the lock is not held across the LLM
call" measures the bug.

Instrumentation reuses the `OrderProbe` pattern already in `tests/test_index/test_builder.py:107-152`.
Entries are counted **at depth 0** — `L_mem` is an `RLock`, so counting raw `__enter__` calls yields
the wrong number.

1. **LLM-under-lock regression (the four LLM jobs).** A `LockProbe` plus a fake LLM recording
   `lock_held_at_call`.
   *Worked example — `auto_linker`, 3 pairs:* today the fake LLM is called 3 times, all recording
   `lock_held=True`, with 1 depth-0 acquisition. After the fix: 3 calls with `lock_held=False`,
   3 acquisitions. `assert not any(c.lock_held for c in calls)` **fails today, passes after** — it
   is the bug, literally.

2. **Foreground progress (the 25-minute symptom).** A `sleep(2)`-based fake LLM with a "write
   completes in <0,5 s" assertion was **considered and rejected: it would not catch the bug
   reliably** — a timing race, green or red by machine load, and an intermittent failure is worse
   than no test. Replaced with `threading.Event`: the fake LLM **blocks**; a foreground thread runs
   `engine.remember()` and must complete *while* the job is parked there; only then is the event
   released. No sleeps, no margin, deterministic. Today it hangs to test timeout; after, it passes.

3. **Long holds without an LLM (`decay_manager`, `importance_scorer`, `auto_cluster`).** For these
   three the bug is not "LLM under lock" — it is whole-run retention with no LLM at all, and it is
   what reaches the **default install**. Assertion is the depth-0 acquisition count: `== 1` today
   for any item count, proportional to items after. A test that only watched the LLM would report
   these three green without touching their bug.

4. **Restore epoch (#210 acceptance criterion).** Job running, epoch bumped mid-run via the same
   hook, assert the job raises `RestoredUnderfoot` **and that no edge or file was written after the
   bump**. The second half is the requirement: aborting without having dirtied anything, not merely
   aborting.

5. **Decay tier revalidation — #257's canary, written on this island.** Node qualifies as a decay
   candidate at snapshot; between snapshot and apply it is promoted to `working` with a fresh
   `last_accessed`; assert it is **not** demoted.

6. **Ingest dedup revalidation.** Two concurrent ingests of the same content; assert one node.

7. **Lock-order preservation.** Reuse the existing `OrderProbe` to assert no new apply step acquires
   `L_mem` inside a `db.transaction()` — the inversion that caused #207. This test is not about
   #240; it is the net that stops #240's fix from reopening #207.

### Verification command

All three FORK-WORKFLOW gates are load-bearing (island venv, clean `PYTHONPATH`, clean `HOME`).
Without them the number is not ours.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
#   printed path MUST contain ormah-wt-240/
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

---

## 8. The issue's four questions, answered

1. **Shared/exclusive guard, or a wall-clock ceiling?** *Neither.* Hold-duration reduction. A
   shared/exclusive guard is the correct end state but converts a starvation bug into a distributed
   lost-update audit whose failures are silent (`stability`, `access_count`), and it breaks #257's
   test, which is open now. A ceiling does not fix anything: 60 s of unanswerable writes is still
   the bug, and `index_updater`'s 34,5 s cold scan passes under any sane ceiling.
2. **Does this block #223?** No. This design preserves every per-operation guarantee verbatim, and
   adds the revalidation that protects #223 from a *future* lock change. See §6.
3. **Does #211 close with this?** **No.** This design keeps the `L_mem → L_db` hierarchy and makes
   it *more* important, because jobs now acquire and release repeatedly. #211 stays open.
4. **Is #238 in scope?** Deferred, and nothing here forecloses it. See §4.

---

## 9. What stays assumed or inferred

- **(inferred)** That one acquisition per pair/cluster/node is short enough. It is short because no
  LLM call is inside it, but no measurement was taken on the fixed code. The tests assert
  *structure* (lock not held across the LLM call), not latency. A latency claim requires re-running
  the original probe against the fix, which is not part of this spec.
- **(assumed)** That aborting a run on epoch change is acceptable operationally — the job simply
  returns at its next interval. Not validated against a maintainer preference; the four issue
  questions have had no reply since 2026-08-18.
- **(verified, and a limit on what may be claimed)** The restore invariant is enforced only on the
  server-side cloud restore path. `cli.py:503` bypasses it entirely, in a separate process. This
  design neither fixes nor worsens that; it is #238's ground.
- **(inferred)** Merge conflicts with PR #257 are "mechanical". Based on the file-overlap set
  (`memory_engine.py`, `consolidator.py`), not on an attempted merge.

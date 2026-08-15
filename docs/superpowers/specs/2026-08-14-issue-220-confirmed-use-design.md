# Separate Surfaced Results from Confirmed Memory Use — Design

**Issue:** [#220](https://github.com/r-spade/ormah/issues/220) · **Decision record:** [#191](https://github.com/r-spade/ormah/issues/191)
**Date:** 2026-08-14
**Supersedes:** the first version of this spec (commit `9859ccd`) and its plan (`19bb362`).

> **Every file path and line number in this document was read from `upstream/main`
> (`a28837b`), not from `local-main`.** This is not a formality. The previous attempt at this
> issue failed because its spec and plan were written against `local-main` while the
> implementation ran in a worktree cut from `upstream/main`. The two bases are 623 commits
> apart; `memory_engine.py` differs by ~972 lines and `session_watcher.py` by ~1581. Every
> address in that document was wrong by construction. Read `upstream/main` — via
> `git show upstream/main:<path>` or from inside the worktree — for any address not listed here.

---

## 1. Problem

Ormah treats a memory's appearance in a search result as evidence that the memory was used.
Every direct result of a broad recall goes through `_touch_access`, one helper that updates
`access_count`, `last_accessed`, `last_review` and `stability` together. A memory that is
surfaced often accumulates lifetime even when the caller ignores it — a self-reinforcing loop
in which visibility manufactures its own justification.

Per #191, the rule is: **a memory stays active because of confirmed use** — not because Ormah
surfaced it, not because it is historically popular, not because it is well connected.

## 2. What is already correct on `upstream/main`

Measured, not assumed. These acceptance criteria from #220 already hold and require **no work**:

| Criterion | Why it already holds |
|---|---|
| Graph activation does not change lifecycle fields | all four call sites are guarded by `if r.get("source") not in ("activated", "conflict")` |
| Conflict expansion does not change lifecycle fields | same guard |
| Bare whisper does not change lifecycle fields | `context_builder.py:523` and `:896` pass `touch_access=False` |
| `recall_node(id)` confirms exactly the requested node, not its neighbours | `memory_engine.py:646` touches `resolved_node_id` only; neighbours are fetched for formatting |
| Retrieval/whisper event logging stays intact | `_log_feedback_candidates` is a separate call from `_touch_access` on every path |

Stating this matters: the previous plan treated all six surfaces as equally broken and budgeted
work for each. Four of them were already correct.

## 3. The actual defect, in four points

| # | Where (`upstream/main`) | Defect |
|---|---|---|
| 1 | `memory_engine.py:892` — `recall_search`, hybrid path | writes lifecycle with **no guard at all** |
| 2 | `memory_engine.py:938` — `recall_search`, FTS fallback | same, unguarded |
| 3 | `memory_engine.py:679` — `recall_search_structured(touch_access=True)` | the default is `True`, and `api/routes_ui.py:60` calls it without the kwarg → **UI search reinforces memory** |
| 4 | `memory_engine.py:2498` — `submit_feedback`; `background/session_watcher.py:561` — the `auto_llm_judge` block | qualified positive feedback records affinity and signals but **never records confirmed use** |

Points 1–3 are **subtraction**: behaviour that must stop. Point 4 is **addition**: behaviour that
must start. That seam is the design's organising principle, and it is where the previous plan —
six tasks with interlocking dependencies — came apart.

## 4. Architecture

**The boundary is the entry point, not a flag.** Search paths do not get a lifecycle write that
is switched off; they lose the capability entirely. A parameter that defaults to the wrong value
is a loaded gun, and the next consumer that forgets to pass `False` re-opens the bug — which is
precisely how `routes_ui.py` acquired it.

**Lifecycle fields**, the concrete meaning of "must not mutate": `access_count`, `last_accessed`,
`last_review`, `stability` — in the markdown file **and** in the SQLite `nodes` row. A contract
test that checks only the database would pass while the file rots.

### 4.1 Task A — subtraction

| File (`upstream/main`) | Change |
|---|---|
| `src/ormah/engine/memory_engine.py:775, 811, 892, 938` | delete the four `_touch_access` call sites and the `if touch_access:` blocks guarding two of them |
| `src/ormah/engine/memory_engine.py:679-694` | remove the `touch_access` parameter from `recall_search_structured` and its docstring paragraph |
| `src/ormah/engine/memory_engine.py:1936` | rename `_touch_access` → `_record_confirmed_use`, **body byte-identical** |
| `src/ormah/engine/context_builder.py:523` | remove the `"touch_access": False` dict key |
| `src/ormah/engine/context_builder.py:896` | remove the `touch_access=False` kwarg |
| `eval/recall/runner.py:74` | remove `touch_access=False` |
| `docs/04 - Whisper - Involuntary Recall.md:101` | correct the reference to `touch_access = False` |

`context_builder.py:523` is load-bearing: that dict is splatted as `**search_kwargs` at `:572`.
Leaving the key behind turns every whisper into a `TypeError`.

**Test call sites that lose the kwarg** (6): `test_background/test_importance_scorer.py:304`;
`test_engine/test_memory_engine.py:546, 569, 584, 597, 619`.

**Tests that become obsolete and are replaced, not deleted:**
`test_engine/test_scoring_signals.py:368-495` is a class asserting that `_touch_access` *is*
called for direct matches and skipped for `activated`/`conflict` nodes. After this change search
calls nothing at all, so the class is rewritten to assert exactly that.
`test_engine/test_mutation_stamping.py:146` follows the rename.

**Deliberately untouched:** `FileStore.touch_access` (`src/ormah/store/file_store.py:145`) is a
namesake with zero production callers and two tests of its own
(`test_store/test_file_store.py:121`, `test_engine/test_mutation_stamping.py:95`). It is out of
scope and must be named in the PR body so a reviewer does not read it as an oversight.

### 4.2 Task B — addition

After this change `_record_confirmed_use` has exactly three callers:

| Caller | Condition | Target |
|---|---|---|
| `recall_node(id)` | always — and it **claims its own event** so later feedback on it cannot reinforce again | the requested node, never its neighbours |
| `submit_feedback` | it **takes the claim** for this `(whisper event, node)` pair: `signal == 1` **and** `source ∈ {explicit, implicit, auto_llm_judge}` **and** no claim existed | the resolved node |
| `session_watcher`, `auto_llm_judge` path | it takes the claim, on the same conditions — **not** `polarity == 1` | each node in the batch that claimed |

The source allowlist is **fail-closed**: any other source, and every negative signal, does not
confirm. `auto_heuristic` stays excluded until #218 provides signal calibration. Negative
feedback remains prompt-specific affinity evidence and never touches stability.

**Confirmation is a property of the event, not of the request** (Dev Council, 2026-08-14). One
whisper event reinforces at most once. `submit_feedback` is replayable by construction — affinity
and signals both write `ON CONFLICT DO NOTHING` and still return success — so reinforcing per
request would let a retried tool call, a double-click, or a second source manufacture retention
from a single confirmed use.

**The gate cannot be derived from existing rows.** The second council round (2026-08-14) refuted
the first round's answer — reading the event's confirmed state off `affinity` before and after the
writes — and the code confirms the refutation. Two candidates, two opposite failures:

- **`affinity` is mutable.** Its unique key is `(node_id, whisper_log_id) WHERE whisper_log_id IS
  NOT NULL` (`db.py:389`), the insert is `ON CONFLICT DO NOTHING` (`memory_engine.py:2547`), and
  only `source == "explicit"` follows with `UPDATE affinity SET signal = ?, source = ?` (`:2569`).
  So explicit `+1 → -1 → +1` reads false→true **twice** and reinforces twice; and a pre-existing
  `auto_heuristic` row makes a later qualified `implicit +1` a no-op insert with no update, leaving
  the gate false forever and losing a legitimate reinforcement in silence.
- **`signals` omits polarity.** Its unique key is `(whisper_log_id, signal_type, source)`
  (`schema.sql:189`) and the row is never updated (`:2575`), so explicit `-1` followed by explicit
  `+1` collides, the stored polarity stays `-1`, and a real confirmation **never** fires.

A rowcount over either table inherits the same defect, for the same reason: their keys and their
mutability answer a different question than "has this event ever been confirmed?"

**The gate is a dedicated latch.** A new table holds one row per `(whisper event, node)` pair:

```sql
CREATE TABLE IF NOT EXISTS confirmed_use_claims (
    whisper_log_id INTEGER NOT NULL REFERENCES whisper_log(id) ON DELETE CASCADE,
    node_id        TEXT NOT NULL,
    claimed_at     TEXT NOT NULL,
    PRIMARY KEY (whisper_log_id, node_id)
);
```

`became_confirmed` is the row count of a single `INSERT ... ON CONFLICT DO NOTHING` into it,
executed **inside the caller's transaction** and only when the incoming signal qualifies. Both
callers share the helper, so the invariant holds across them — which matters because
`has_llm_judge` only sees the watcher's own signal source and is blind to feedback submitted
through MCP. The latch is monotonic: nothing deletes it, so a polarity cycle cannot re-arm it, and
it consults neither `affinity` nor `signals`.

`whisper_log_id` is `NOT NULL` because SQLite permits repeated `NULL`s in a primary key, which
would defeat the latch. The foreign key is `ON DELETE CASCADE`, not the `SET NULL` the other
`whisper_log_id` references use — those columns are nullable, and `SET NULL` on a `NOT NULL`
column would make `whisper_log_cleanup`'s delete fail. CASCADE also bounds the table by
`whisper_log`'s own retention, and `whisper_log.id` is `AUTOINCREMENT`, so a cascaded delete
cannot resurrect a claimable event.

`node_id` carries **no** foreign key, and that is deliberate. An earlier draft gave it
`REFERENCES nodes(id)` for symmetry; implementation measured the cost. It broke 16 pre-existing
tests in `tests/test_engine/test_submit_feedback.py` and `tests/test_whisper_health.py`, which
fabricate node ids that never reach the `nodes` table — a legitimate way to exercise the feedback
path without creating nodes. The constraint bought nothing in return: the only writer is
`_claim_confirmed_use`, and it receives a node id `submit_feedback` has already resolved against
the store, so the reference would guard against a bug the code cannot commit. A claim outliving
its node is harmless — the latch only ever prevents a second reinforcement — and the
`whisper_log` cascade already bounds the table.

### 4.2.1 Serializing the mutator

`_record_confirmed_use` does `load` → modify → `save` → DB update. `FileStore` is constructed with
the engine's `_memory_operation_lock` (`memory_engine.py:94`), so each file operation takes that
lock individually while the read-modify-write across them stays unprotected. **Measured on
`upstream/main`:** neither `_touch_access` (`:1936`) nor any of its five callers carries
`@_serialized_memory_operation`. Two concurrent confirmations can collapse to one increment, and a
confirmation can save a stale node over a concurrent edit.

The race is pre-existing and this design already shrinks its surface from five callers to three,
but the function is becoming the canonical confirmed-use operation, so it is closed here:
`_record_confirmed_use` gains the decorator. The body is untouched; the lock is a reentrant
`RLock`, so already-serialized callers are unaffected, and the `memory_lock → db_lock` order
matches every other serialized writer. That order is precisely why §4.3's rule is mandatory rather
than merely tidy.

### 4.3 Concurrency: the reinforcement runs outside the transaction

`IndexDB.transaction()` (`src/ormah/index/db.py:62-82`) holds a process-level `self._lock` for
the **entire body** of the block, not merely the `BEGIN`. It is reentrant per thread, which is
why `submit_feedback` can already nest a transaction inside its own. The consequence: while any
transaction is open, every write from every thread is blocked.

`_record_confirmed_use` performs `file_store.load` and `file_store.save` — disk I/O. Calling it
inside an open transaction holds the global write lock across that I/O; in the session watcher,
across N markdown saves in a loop.

**Decision:** collect confirmed node IDs inside the transaction, reinforce after it commits.

With the decorator from §4.2.1 in place this is no longer only a throughput argument: calling
`_record_confirmed_use` inside an open transaction would take `db_lock` before `memory_lock`,
inverting the order every serialized writer uses. Reinforcing after the commit is a correctness
rule.

```python
# session_watcher, auto_llm_judge path
confirmed = []
with engine.db.transaction() as conn:
    for record in judge_records:
        recorded += _insert_usage_signal(conn, ...)
        if record["polarity"] in (1, -1):
            _insert_affinity(conn, ...)
        if engine._claim_confirmed_use(
            conn, record["row"]["id"], record["row"]["node_id"],
            signal=record["polarity"], source=_LLM_JUDGE_AFFINITY_SOURCE,
        ):
            confirmed.append(record["row"]["node_id"])
# lock released here
for node_id in confirmed:
    try:
        engine._record_confirmed_use(node_id)
    except Exception:
        logger.exception("confirmed-use reinforcement failed for node %s", node_id)
```

Each node is isolated, and the catch is broad on purpose. The signals are already committed when
this loop runs, so an escaping exception would abort the ingest slice, skip every later node, and
leave `has_llm_judge` set — the retry then filters the event out and those reinforcements are gone.
`OSError` alone is too narrow: `MemoryNode.stability` is `Field(default=1.0, ge=0.0)`
(`models/node.py:59`), so zero is legal and the mutator's `math.exp(-days_since / node.stability)`
raises `ZeroDivisionError`; `sqlite3.Error` and markdown validation errors are equally reachable.

```python
# submit_feedback
with self.db.transaction():
    resolved_node_id, became_confirmed, result = self._submit_feedback_locked(...)
# lock released here
if became_confirmed:
    try:
        self._record_confirmed_use(resolved_node_id)
    except Exception:
        logger.exception("confirmed-use reinforcement failed for node %s", resolved_node_id)
return result
```

This requires `_submit_feedback_locked` to return the `resolved_node_id` and the claim flag
alongside its message — it already computes the node ID at `memory_engine.py:2529` and currently
discards it. `became_confirmed` is the claim taken inside the existing transaction, per §4.2.

**`submit_feedback` isolates the mutator too** (second council round). The first version isolated
only the watcher. But the API route returns `submit_feedback`'s value directly, so an exception
after `COMMIT` turns a call whose affinity and signals rows are already durably written into a 500 —
and, because the claim is taken, the client's retry returns success without reinforcing. Both
callers therefore catch, log, and return normally.

### 4.3.1 The delivery contract is at-most-once

Stated plainly, because it is a decision and not an oversight. `_record_confirmed_use` saves the
markdown file **before** updating SQLite, and that file write cannot join the transaction or be
rolled back. Both peers in the second council round confirmed that **no ordering of claim and
mutator delivers exactly-once**:

| Arrangement | Concurrent double reinforcement | Recoverable after a post-commit failure |
|---|---|---|
| Claim inside the transaction, mutator after `COMMIT` (**chosen**) | impossible | no — the claim is taken, the retry skips |
| Mutator first, claim after | possible — both callers pass the check | yes |
| Lock + file I/O inside the transaction | impossible | no — the file save still escapes `ROLLBACK` |

The first row is chosen. A crash or exception between `COMMIT` and the mutator loses that event's
reinforcement permanently, and a DB failure after the file save can leave markdown and SQLite
disagreeing on the lifecycle fields until the next successful write to that node.

The cost is real and was quantified in the first council round: with `S = 1` and `growth = 1.5`,
uses on day 1 and day 2, dropping the day-1 update yields about **2.24** stability instead of
**3.07**. The node stays permanently below its true trajectory. The earlier claim that "the next
confirmed use recovers it" was **false**.

It is accepted anyway, on the issue's own terms: `#220` exists because Ormah was manufacturing
retention from mere surfacing, so **a double reinforcement is worse than a missed one**. Exactly-once
would need a durable pending/applied protocol plus a reconciliation loop — rejected in both council
rounds, the second time over an explicit counter-argument from Codex, because a recovery loop that
re-applies missed reinforcements would invert the purpose of the issue. Misses are logged.

The claim is **never deleted on failure**, for the same file-write reason: the markdown may already
carry the increment, so a delete-and-retry would increment it a second time.

Both transaction blocks live in one function, `_record_whisper_usage_signals`
(`session_watcher.py:407`): the `auto_heuristic` path opens its own at `:498`, the
`auto_llm_judge` path a separate one at `:561`. Only the second is modified. Because the two
paths do not share a block, there is no route by which a heuristic record can reach the
confirmed-use list — the separation is structural, and contract test 12 pins it.

**Accepted cost:** the reinforcement is not atomic with the signal. A crash between the commit
and the reinforcement leaves a recorded signal without its reinforcement, and that loss is
**permanent** — the watcher will not re-judge the event, because `has_llm_judge` is already set.

An earlier draft of this section claimed the next confirmed use would correct it. That claim was
**false**, and the Dev Council (2026-08-14) quantified the error: with `S = 1`,
`fsrs_stability_growth = 1.5`, and confirmed uses on day 1 and day 2, dropping the day-1 update
yields roughly **2.24** stability instead of **3.07**. The formula is multiplicative in the
current stability and time-dependent through retrievability, so a skipped step does not wash out —
the node stays permanently below its true trajectory. The cost is accepted with that understood,
not because it self-heals.

Two things bound it. The write is per node inside a loop that catches every exception per node
(§4.3), so the realistic failure — one unreadable or malformed node — costs only that node's
reinforcement, never the rest of the batch. What remains is a hard process kill in the window
between `COMMIT` and the loop.

**Rejected alternative:** holding the global write lock across disk I/O, which stalls every
whisper and every ingest for the duration. **Also rejected:** a durable pending-confirmed-use
table with a reconciliation loop that replays it until applied, including after restart — new
surface, new correctness criterion, and its own test suite, to repair a window that only a hard
kill can open. The council proposed this and, on the second round, agreed that the residual
crash window alone does not justify it.

### 4.4 What does not change

`_record_confirmed_use` keeps its body byte-identical, including the silent return when the node
is missing, and no error handling is added *inside* it — §4.3's isolation lives in the caller,
which is a different thing. The only change to the function itself is the `@_serialized_memory_operation`
decorator (§4.2.1). The stability formula
(`stability * fsrs_stability_growth * (retrievability ** -0.2)`) is untouched — bounding,
cooldown and saturation are #221.

The only schema change is the new `confirmed_use_claims` table (§4.2), added to `schema.sql` as
`CREATE TABLE IF NOT EXISTS`. `Database.init_schema` (`db.py:84-89`) runs `executescript` on every
startup, so a purely additive table needs no `_migrate` step — unlike the `affinity` migration,
which had to alter an existing table's unique constraint. No existing table, column, or index is
touched. This does widen Task B beyond the pure "addition" the original design promised; it is the
smallest change that makes the gate correct, and the gate is the point of the issue.

## 5. Verification

Regression is prevented by contract tests on the surfaces, not by a type or a naming convention.
Each test captures all four lifecycle fields before and after, in **both** the markdown and the
SQLite row.

### Non-mutation contracts (Task A)

| # | Surface | Note |
|---|---|---|
| 1 | `recall_search`, hybrid | real search over N nodes |
| 2 | `recall_search`, FTS fallback | hybrid disabled |
| 3 | `recall_search_structured`, hybrid | called with **no** lifecycle kwarg — the default was the bug |
| 4 | `recall_search_structured`, FTS fallback | idem |
| 5 | UI search through `api/routes_ui.py:60` | exercised through the route, not the engine |
| 6 | whisper through `context_builder` | still non-mutating after losing the flag |

**Test 5 fails on clean `upstream/main`.** It is the proof that the defect exists, and it is
written before the fix.

### Confirmed-use contracts (Task B)

| # | Event | Expected |
|---|---|---|
| 7 | `recall_node(id)` | the requested node mutates; **each neighbour** is asserted unchanged |
| 8 | `submit_feedback(+1, explicit \| implicit \| auto_llm_judge)` | only the resolved node mutates |
| 9 | `submit_feedback(+1, auto_heuristic)` | nothing mutates |
| 10 | `submit_feedback(-1, any source)` | nothing mutates |
| 10a | the same `submit_feedback(+1, explicit)` replayed | confirms **once** |
| 10b | `submit_feedback(-1, explicit)` then `(+1, explicit)` | confirms — the negative claimed nothing, so this is the event's first confirmation |
| 10c | `submit_feedback(+1, implicit)` then `(+1, explicit)` | confirms **once** — one event, not one per source |
| 10d | `submit_feedback(+1, explicit)`, then `(-1)`, then `(+1)` | confirms **once** — the polarity cycle cannot re-arm the latch |
| 10e | `submit_feedback(+1, auto_heuristic)` then `(+1, implicit)` | confirms — an unqualified affinity row must not swallow a real use |
| 10f | `submit_feedback(+1, explicit)` with the mutator raising `ZeroDivisionError` | returns the recorded-feedback message, no exception escapes, lifecycle unchanged, affinity row still committed |
| 7a | `recall_node(id)`, then `submit_feedback(+1, explicit)` on the `whisper_log_id` recall_node itself surfaced | confirms **once** — the fetch already claimed its own event |
| 11 | session watcher, `auto_llm_judge`, positive verdict | confirms, and signals/affinity rows are still written |
| 12 | session watcher, `auto_heuristic` | does not confirm, **and takes no claim** |
| 13 | the same transcript judged twice | confirms **once** (`has_llm_judge` and the claim, two independent guards) |
| 13a | `submit_feedback(+1, implicit)` then a positive judge verdict on the same event | confirms **once** — the cross-caller case `has_llm_judge` cannot see |
| 14 | watcher batch where node 1's mutator raises `ZeroDivisionError` | node 2 is still reinforced; `recorded` is unaffected |
| 15 | concurrent `_record_confirmed_use` on one node from N threads | `access_count` advances by exactly N, file and DB agree |

Pairs 8/9 and 11/12 are what give the allowlist teeth: without the negative case, a loose
condition passes.

**Contracts 10d, 10e and 13a are the three that killed the previous design**, and each one maps to
a specific defect the second council round found. 10d is the false positive from `affinity`'s
in-place `UPDATE`. 10e is the false negative from `auto_heuristic` occupying the single affinity row
per event. 13a is the cross-caller double reinforcement that `has_llm_judge` cannot prevent, because
it only recognises the watcher's own signal source. A gate derived from `affinity` passes 10a–10c
and fails all three of these — which is exactly why 10a–10c alone were not enough evidence the first
time.

Contract 10f pins the at-most-once contract at the API boundary: the miss is acceptable, a 500 is
not. Contract 15 is racy by nature and may pass on an unserialized mutator by luck; it is kept as a
regression pin, with that limitation stated rather than hidden.

**Contract 7a came from the whole-branch review, and it caught a regression this design
introduced.** `recall_node` reinforces unconditionally, then calls `_log_feedback_candidates`,
which creates a `whisper_log` row for that same node and hands its id to the agent — and the agent
instructions tell the model to `submit_feedback(+1)` with that id when it draws on the memory. On
`upstream/main` that sequence reinforced once, because feedback did not reinforce at all. With
§4.2's callers in place and no claim taken by `recall_node`, it reinforced **twice**: measured
`access_count` 0 → 1 → 2 and `stability` 1.0 → 1.5 → 2.25. Inflating retention on the most
deliberate surface in the system is precisely what this issue exists to stop, so `recall_node` now
claims its own event before reinforcing. Neither the per-task reviews nor either council round could
have caught this: it only exists once both halves are in place, and only running the code shows it.

### Gate

The baseline — the list of test IDs that already fail on clean `upstream/main` — is measured
**once in the worktree, at the start**, and is shared input to both tasks rather than a task of
its own. "Tests pass" means *no test ID outside that list fails*. `make lint`
(`ruff check src/ tests/`) must pass before each commit.

PR #229's description claims a pre-existing `A LIMIT or k = ? constraint is required on vec0 knn
queries` failure in auto-link, conflict and worker-thread vector search. **That is a claim from a
PR description, not a measurement.** The baseline step measures it. If the suite is green, that
contradicts #229 and is itself worth reporting.

## 6. Where the work happens

Per `FORK-WORKFLOW.md`, non-negotiable:

- worktree at `../ormah-wt-220` on branch `fix/220-confirmed-use`, cut from `upstream/main`
- **never** `git checkout` a contribution branch inside `Tools/ormah` — that directory is what
  the running Beta serves via launchd `com.ormah.server.dev`
- push to `fork`, never `upstream`; do not rename remotes
- the spec and the plan are written by reading `upstream/main` — the process correction of this round

**Blocked, and only this:** the PR must not be opened while draft PR
[#229](https://github.com/r-spade/ormah/pull/229) still declares `Closes #220–#223`. Implementing
and committing are free; `gh pr create` waits for that PR to be closed as superseded, or for its
`Closes` lines to be dropped.

Landing order for the cluster is #220 → #222 → #221 → #223, as four separate PRs.

## 7. Out of scope

The reinforcement formula (#221) · importance blocking decay (#222) · archival promotion (#223) ·
`auto_heuristic` admission (#218) · UI search retrieval logging (#231) ·
`FileStore.touch_access` · any change to the stability formula.

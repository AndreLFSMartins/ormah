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
| `recall_node(id)` | always (already present at `memory_engine.py:646`) | the requested node, never its neighbours |
| `submit_feedback` | `signal == 1` **and** `source ∈ {explicit, implicit, auto_llm_judge}` | the resolved node |
| `session_watcher`, `auto_llm_judge` path | `polarity == 1` | each node in the batch |

The source allowlist is **fail-closed**: any other source, and every negative signal, does not
confirm. `auto_heuristic` stays excluded until #218 provides signal calibration. Negative
feedback remains prompt-specific affinity evidence and never touches stability.

### 4.3 Concurrency: the reinforcement runs outside the transaction

`IndexDB.transaction()` (`src/ormah/index/db.py:62-82`) holds a process-level `self._lock` for
the **entire body** of the block, not merely the `BEGIN`. It is reentrant per thread, which is
why `submit_feedback` can already nest a transaction inside its own. The consequence: while any
transaction is open, every write from every thread is blocked.

`_record_confirmed_use` performs `file_store.load` and `file_store.save` — disk I/O. Calling it
inside an open transaction holds the global write lock across that I/O; in the session watcher,
across N markdown saves in a loop.

**Decision:** collect confirmed node IDs inside the transaction, reinforce after it commits.

```python
# session_watcher, auto_llm_judge path
confirmed = []
with engine.db.transaction() as conn:
    for record in judge_records:
        recorded += _insert_usage_signal(conn, ...)
        if record["polarity"] in (1, -1):
            _insert_affinity(conn, ...)
        if record["polarity"] == 1:
            confirmed.append(record["row"]["node_id"])
# lock released here
for node_id in confirmed:
    engine._record_confirmed_use(node_id)
```

```python
# submit_feedback
with self.db.transaction():
    resolved_node_id, result = self._submit_feedback_locked(...)
# lock released here
if signal == 1 and source in _CONFIRMED_USE_SOURCES:
    self._record_confirmed_use(resolved_node_id)
return result
```

This requires `_submit_feedback_locked` to return the `resolved_node_id` alongside its message —
it already computes the value at `memory_engine.py:2529` and currently discards it.

Both transaction blocks live in one function, `_record_whisper_usage_signals`
(`session_watcher.py:407`): the `auto_heuristic` path opens its own at `:498`, the
`auto_llm_judge` path a separate one at `:561`. Only the second is modified. Because the two
paths do not share a block, there is no route by which a heuristic record can reach the
confirmed-use list — the separation is structural, and contract test 12 pins it.

**Accepted cost:** the reinforcement is not atomic with the signal. A crash between the commit
and the reinforcement leaves a recorded signal without its reinforcement — one memory misses one
reinforcement, and the next confirmed use corrects it. **Rejected alternative:** holding the
global write lock across disk I/O, which stalls every whisper and every ingest for the duration.
**Also rejected:** a reconciliation job that sweeps positive signals lacking a reinforcement —
new surface, new correctness criterion, and its own test suite, to repair an event whose damage
is one lost reinforcement.

### 4.4 What does not change

`_record_confirmed_use` keeps its body byte-identical, including the silent return when the node
is missing. No new error handling. The stability formula
(`stability * fsrs_stability_growth * (retrievability ** -0.2)`) is untouched — bounding,
cooldown and saturation are #221.

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
| 11 | session watcher, `auto_llm_judge`, `polarity == 1` | confirms, and signals/affinity rows are still written |
| 12 | session watcher, `auto_heuristic` | does not confirm |

Pairs 8/9 and 11/12 are what give the allowlist teeth: without the negative case, a loose
condition passes.

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

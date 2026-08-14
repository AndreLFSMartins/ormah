# Design — separate surfaced results from confirmed memory use

- **Issue:** [#220](https://github.com/r-spade/ormah/issues/220) `bug(lifecycle)`
- **Decision record:** [#191](https://github.com/r-spade/ormah/issues/191) (closed)
- **Cluster:** #220 → #222 → #221 → #223, one PR each (landing order agreed with @r-spade, 2026-08-14)
- **Date:** 2026-08-14

## Problem

`_touch_access` (`src/ormah/engine/memory_engine.py:2408`) is one helper that performs four
mutations at once — `access_count += 1`, `last_accessed`, `last_review`, and
`stability *= fsrs_stability_growth` — on both the markdown file and the SQLite row. There is no
way to ask for one without the others.

It has five call sites. One is legitimate: `recall_node(id)` at L783, a deliberate fetch of one
node. The other four sit inside `for r in results` loops — L912 and L948 in
`recall_search_structured`, L1029 and L1075 in `recall_search`. **Every node that appears in a
result list is credited as if it had been read.**

A ten-result recall where the caller used one memory awards identical lifecycle credit to all ten.

### Measured, on a live store — 698 nodes, 2026-08-14

| `access_count` | nodes | `stability` |
|---:|---:|---:|
| 0 | 657 | 1.00 |
| 1 | 31 | 1.52 |
| 2 | 4 | 2.28 |
| 3 | 6 | 3.41 |

Exactly `1.5^n`, matching `fsrs_stability_growth = 1.5` (`config.py:171`). Stability is
multiplicative and uncapped below `fsrs_max_stability = 365`.

A node decays when `R = exp(-t / S)` falls below `fsrs_decay_threshold = 0.3`, i.e. after
`t = 1.204 * S` days. So surfacing buys lifetime directly:

| appearances | `stability` | survives |
|---:|---:|---:|
| 0 | 1.00 | 1.2 days |
| 3 | 3.38 | 4.1 days |
| 10 | 57.7 | 69 days |
| 15 | 365 (capped) | 439 days |

Fifteen appearances in result lists — with nobody ever reading the content — buy over a year of
life. `fsrs_max_stability = 365` caps the *stability*, not the lifetime: at the cap a node survives
`1.204 × 365 = 439` days.

### The loop closes through importance, not through ranking

Neither `stability` nor `access_count` appears in `hybrid_search.py`; search ranking is not
directly affected. The self-reinforcement runs through two independent channels in the importance
scorer, and then through the decay gate:

```
memory appears in a search
    ├─→ access_count++ ──→ importance_scorer.py:72  access_signal ↑
    └─→ stability × 1.5 ─→ importance_scorer.py:84  recency_signal = exp(-days / stability) ↑
                                        │
                                   importance ↑
                                        │
                         decay_manager.py:45  high importance skips decay
                                        │
                                survives in the pool
                                        │
                                appears again ──┐
                                        ▲       │
                                        └───────┘
```

The second channel is the subtle one: importance's *recency* signal uses `stability` as its time
constant, so inflating stability also makes a node look more recent than it is.

### Current blast radius

41 of 698 nodes have `access_count > 0`. The damage is modest today for an accidental reason —
whisper already passes `touch_access=False` (`context_builder.py:525` and `:892`), so only explicit
`recall()` and UI search inflate. The mechanism, not the current damage, is what is unbounded.

## Design

### 1. The boundary is the entry point, not a parameter

Two operations, and which one runs is decided by *which function the caller entered through*.

**Surfacing** — the node appeared. Logging only, through the existing
`_log_feedback_candidates`. No lifecycle write. Applies to `recall_search`,
`recall_search_structured`, whisper, UI search, spreading activation, and conflict expansion.

**Confirmed use** — `_record_confirmed_use(node_id)`, the single lifecycle mutator. Exactly three
callers:

1. `recall_node(id)` — deliberate fetch of one node (already the case; only the name changes)
2. `_submit_feedback_locked` — when `signal == 1` **and** `source ∈ {explicit, implicit, auto_llm_judge}`
3. `session_watcher`, `auto_llm_judge` positive path — which writes affinity directly and never
   passes through `submit_feedback`

The source list is an explicit allowlist and **fail-closed**: an unrecognised `source` does not
confirm. `auto_heuristic` is excluded pending [#218](https://github.com/r-spade/ormah/issues/218).
Negative feedback never confirms, from any source — it is prompt-specific affinity evidence, not
grounds to touch stability or tier.

### 2. Rename over guard

`_touch_access` is renamed to `_record_confirmed_use` with its **body byte-identical**. The rename
carries half the safety of this change: `_touch_access` reads like harmless bookkeeping, which is
precisely why four call sites adopted it without thought. Nobody writes `_record_confirmed_use`
inside a `for r in results` by accident.

The `touch_access` parameter of `recall_search_structured` is **removed**, along with the two
`touch_access=False` arguments in `context_builder.py`. A flag that only ever takes one value is
not configuration; leaving it in place would keep suggesting that a mutating mode exists.

A `UseKind` enum with a checked `SURFACED` no-op was considered and rejected. It preserves the
exact coupling this issue exists to cut — search code would still call a lifecycle function — and
its signature is wrong for the job: surfacing needs `prompt_text`, per-node scores, `session_id`
and `surface`, which is the shape of `_log_feedback_candidates`, not of a single `node_id`. The
regression guarantee comes from contract tests instead (§Testing).

### 3. Surfaces

| Surface | Today | After | Nature |
|---|---|---|---|
| `recall_search` hybrid | **mutates** N nodes | log only | removal |
| `recall_search` FTS fallback | **mutates** N nodes | log only | removal |
| `recall_search_structured` hybrid | mutates when `touch_access` | never mutates | removal |
| `recall_search_structured` FTS fallback | mutates when `touch_access` | never mutates | removal |
| UI search (`GET /api/search`) | **mutates** (uses the default) | never mutates | removal |
| Whisper / context build | already clean | unchanged | regression test |
| `activated` / `conflict` results | already excluded | unchanged | regression test |
| `recall_node` neighbours | already clean | unchanged | regression test |
| `recall_node(id)` itself | mutates the requested node | unchanged, renamed | unchanged |
| `submit_feedback` qualified positive | **does nothing** | confirms use | **addition** |
| `submit_feedback` negative | does nothing | unchanged | unchanged |
| `session_watcher` `auto_llm_judge` positive | writes affinity only | + confirms use | **addition** |
| `session_watcher` `auto_heuristic` positive | writes affinity only | unchanged | unchanged |

Half of this issue is an addition, not a rewire: `submit_feedback` never touched the lifecycle.
Verified by reading `_submit_feedback_locked` (L3136–L3234) — there is no `_touch_access` call.

Two claims in the "already clean" rows were verified rather than assumed:

- **Whisper.** `context_builder` only ever calls `recall_search_structured`, never the ungated
  `recall_search`. L535 does `search_kwargs.update(intent.search_params)` *after* setting
  `touch_access: False`, so an override was possible in principle;
  `prompt_classifier.py:358-374` only ever produces `created_after`, `created_before` and
  `search_query`. No override exists.
- **`activated` / `conflict`.** `memory_engine.py:2604` assigns one of the two to every node
  `_spread_activation` adds, so the exclusion filter covers all of them.

One case the current exclusion list does **not** cover: `_supplement_temporal` produces results
with `source="temporal"`, which is absent from `("activated", "conflict")` — temporal supplements
are mutated today. Deleting the loops removes this too, and it is evidence for deletion over any
filter-based approach: the filter was already incomplete.

### 4. Transaction placement

`db.transaction()` is reentrant per thread (`index/db.py:72`), so nesting is safe. But
`_record_confirmed_use` writes the markdown file *before* the DB row (the repository's
Council R3 C5 mutation convention), so a rollback would leave the file stamped and the row not.
Two consequences:

- **`submit_feedback`** — the call goes as the **last statement** of `_submit_feedback_locked`.
  It stays inside the outer transaction opened at L3128, which is desirable (feedback and its
  lifecycle effect should be atomic), and being last means nothing after it can fail and roll back
  a markdown write that already happened.
- **`session_watcher`** — the `auto_llm_judge` loop runs inside
  `with engine.db.transaction() as conn` over a whole batch. Qualifying `node_id`s are collected
  during the loop and `_record_confirmed_use` is applied **after** the block closes, so per-node
  file I/O does not hold `BEGIN IMMEDIATE` across the batch.

**No new error handling.** The body stays identical, including the existing early return when the
node is missing. Adding a `try/except` here would change behaviour this issue must not change.

## Testing

Every test asserts on the same four fields: `access_count`, `last_accessed`, `last_review`,
`stability`.

**Non-mutation (the contract)**

- broad recall, hybrid path — N results, zero fields changed on any of them
- broad recall, FTS fallback path — same, with hybrid search forced unavailable
- `GET /api/search` — same
- whisper / context build — same
- `activated` and `conflict` results — same
- `recall_node` neighbours — same

**Mutation, exactly where intended**

- `recall_node(id)` mutates the requested node and no other
- `submit_feedback(signal=1, source="explicit")` confirms use on the resolved node only
- `submit_feedback(signal=1, source="implicit")` — same
- `session_watcher` `auto_llm_judge` positive confirms use

**Fail-closed**

- `signal=1, source="auto_heuristic"` does not confirm
- `signal=-1`, any source, does not confirm
- unknown `source` string does not confirm
- `session_watcher` `auto_llm_judge` negative does not confirm

These contract tests, not a type, are the regression guarantee: they catch a reintroduced
lifecycle write through any mechanism, including one nobody anticipated.

**Baseline first.** Run the suite on clean `upstream/main` and record the result before claiming
anything green. PR #229 reported pre-existing failures
(`A LIMIT or k = ? constraint is required on vec0 knn queries` in auto-link, conflict and
worker-thread vector search, plus a setup binary-detection assumption). Without the baseline there
is no way to separate what this change broke from what was already red.

## Delivery

Per `FORK-WORKFLOW.md`, non-negotiable:

```bash
git fetch upstream
git worktree add -b fix/220-confirmed-use ../ormah-wt-220 upstream/main
# work in ../ormah-wt-220 — Tools/ormah stays on local-main (it is what the running Beta serves)
git push fork fix/220-confirmed-use
/council-pr            # base r-spade:main, head fork:fix/220-confirmed-use
```

Branch cut from `upstream/main`, never from `local-main`. Push to `fork`. Do not rename remotes.

**Blocking pre-condition for opening the PR:** draft PR
[#229](https://github.com/r-spade/ormah/pull/229) is still OPEN and its body carries
`Closes #220–#223`. If it merges, it auto-closes all four issues. Raised with @r-spade at
[#229#issuecomment-5296007628](https://github.com/r-spade/ormah/pull/229#issuecomment-5296007628);
the PR should not be opened until he closes it or drops the `Closes` lines.

The PR body should carry one line of fact, not a debt: *UI search does not log retrieval events —
it did not before this change either.* Tracked separately as
[#231](https://github.com/r-spade/ormah/issues/231).

### Explicitly not in this change

- **The reinforcement formula.** `stability × 1.5` stays uncapped and uncooled. It now compounds
  over rare real events instead of over appearances, which is the point of this issue, but the
  formula itself is [#221](https://github.com/r-spade/ormah/issues/221).
- **Importance blocking decay.** The gate at `decay_manager.py:45` survives intact —
  [#222](https://github.com/r-spade/ormah/issues/222), which lands next.
- **Archival promotion.** `_touch_access` does not touch `tier` today, so "surfacing must not
  promote an archival node" is already true and becomes a regression test. Adding reversible
  promotion is [#223](https://github.com/r-spade/ormah/issues/223).
- **`auto_heuristic` admission.** Waits on [#218](https://github.com/r-spade/ormah/issues/218).
  This is not a footnote: on the reference store, `auto_heuristic` accounts for 153 of the 184
  positive affinity rows, so #218 gates off **83% of all positive feedback**. This change admits
  31 events (25 `auto_llm_judge` + 6 `implicit`); `explicit` has never been used at all.
- **UI search retrieval logging.** [#231](https://github.com/r-spade/ormah/issues/231), follow-up
  after #223.

## Risk register

| Risk | Register | Mitigation |
|---|---|---|
| PR #229 merges and auto-closes #220–#223 | **verified** — PR is OPEN, draft, body carries `Closes` | comment posted; do not open the PR until resolved |
| A future call site reintroduces a lifecycle write in a search loop | **assumed** — nothing structurally prevents it | contract tests fail loudly on any of the six non-mutation surfaces |
| Suite is red before the change and the cause is misattributed | **inferred** — #229 reported pre-existing vec0 failures, not re-measured here | record the `upstream/main` baseline before running anything |
| Confirmed-use signal is starved after this change | **verified by measurement** — 31 admitted vs 153 excluded | accepted deliberately; #218 is the fix, now assigned |
| `auto_llm_judge` confirmed-use path untested on live data | **verified** — session watcher is off on the reference store, so those 25 rows are historical | covered by unit tests; no live validation available on this machine |
| Markdown stamped but DB rolled back | **inferred** from the write order in the existing helper | call placed last inside the feedback transaction; batched after the transaction in the session watcher |

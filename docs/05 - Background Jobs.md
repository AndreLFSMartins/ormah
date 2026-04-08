# Background Jobs

Verified against the current repository state on 2026-04-07.

Ormah uses APScheduler to run maintenance tasks that keep the derived graph and ranking state healthy over time.

## Scheduler

**Code**: `src/ormah/background/scheduler.py`

The scheduler is a `BackgroundScheduler` with a `120` second misfire grace window.

Registered jobs:

| Job | Default interval | LLM required? | Purpose |
|---|---:|:---:|---|
| `auto_linker` | 24h | yes | classify and create semantic edges |
| `decay_manager` | 24h | no | demote stale working memories |
| `conflict_detector` | 24h | yes | detect contradictions / evolutions |
| `duplicate_merger` | 24h | yes | detect near-duplicates |
| `auto_cluster` | 60m | no | assign spaces to unassigned nodes |
| `consolidator` | 24h | yes | synthesize working-memory clusters |
| `importance_scorer` | 120m | no | recompute importance |
| `index_updater` | 1m | no | incremental derived-index sync |

## Sleep-Cycle Order

When `/admin/tasks/run-all` is used, tasks run in this order:

```text
importance_scorer
-> index_updater
-> duplicate_merger
-> conflict_detector
-> auto_linker
-> auto_cluster
-> consolidator
-> decay_manager
```

## Auto-Linker

Auto-linker finds candidate pairs through embeddings, applies a cross-space penalty, and asks the LLM to classify the relationship.

Possible outcomes include:

- `supports`
- `part_of`
- `depends_on`
- `contradicts`
- `related_to`
- `none`

## Conflict Detector

**Code**: `src/ormah/background/conflict_detector.py`

The conflict detector:

1. samples belief-like nodes
2. finds semantically similar pairs
3. asks the LLM whether they truly conflict
4. distinguishes:
   - **evolution**: newer view supersedes older one
   - **tension**: simultaneous incompatible beliefs

Important correction:

- both `evolved_from` and `contradicts` edges are currently written with `weight=0.9`

The older `0.4` figure some docs mentioned belongs to spreading activation during search, not stored conflict edges.

## Duplicate Merger

Duplicate detection uses a composite score built from:

- embedding similarity
- title similarity
- token overlap

### Merge semantics

`MemoryEngine.execute_merge()` does **not** create a brand-new merged node.

Instead it:

1. chooses a keeper node
2. optionally overwrites the keeper's title/content with merged content
3. snapshots the removed node for undo
4. remaps edges from removed -> kept
5. soft-deletes the removed markdown node
6. records merge history

That distinction matters in presentations: duplicate merging is currently a "keep one node and rewrite around it" flow, not a "create a third canonical merged node" flow.

## Consolidator

Consolidator is different from duplicate merge.

It:

1. finds clusters of similar **working-tier** nodes
2. asks the LLM to synthesize a richer summary
3. creates a **new** consolidated node
4. links originals using `derived_from`
5. demotes originals to `archival`

So:

- duplicate merge -> keep one existing node
- consolidation -> create a new synthesized node

## Auto-Cluster

Auto-cluster is a simple heuristic job:

- looks for nodes with no space
- checks the spaces of connected neighbors
- uses majority vote
- writes that chosen space back to markdown and SQLite

It does not do embedding clustering or hierarchical clustering despite the name.

## Importance and Decay

- `importance_scorer` computes a normalized multi-signal importance value
- `decay_manager` uses FSRS-style retrievability and importance to decide whether to demote working memories

High-importance nodes are protected from decay.

## Walkthrough Example

Imagine two memories:

- `Chose SQLite for Ormah`
- `We switched Ormah to Postgres`

Conflict detector flow:

1. finds them as a semantically similar pair
2. LLM judges whether they are really about the same subject
3. if the newer one supersedes the older one, it writes `evolved_from`
4. the stored edge weight is `0.9`

Now compare duplicate merge:

- `Chose SQLite for Ormah`
- `Ormah uses SQLite`

If judged duplicate:

1. a keeper node is chosen
2. its content may be rewritten to include the best wording from both
3. the other node is removed and edges are remapped

## Code Anchors

- `src/ormah/background/scheduler.py`
- `src/ormah/background/auto_linker.py`
- `src/ormah/background/conflict_detector.py`
- `src/ormah/background/duplicate_merger.py`
- `src/ormah/background/consolidator.py`
- `src/ormah/background/auto_cluster.py`
- `src/ormah/background/importance_scorer.py`
- `src/ormah/background/decay_manager.py`

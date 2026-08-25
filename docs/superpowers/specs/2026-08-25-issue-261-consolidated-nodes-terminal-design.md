# Design: consolidated nodes are terminal for cluster discovery (#261)

- **Issue:** r-spade/ormah#261 — a consolidated node stays in the `working` tier and
  re-clusters, producing summaries written from summaries
- **Base:** `upstream/main` (clean island, Recipe A of `FORK-WORKFLOW.md`)
- **Branch:** `fix/261-consolidated-nodes-are-terminal`, worktree `../ormah-wt-261`
- **Date:** 2026-08-25

## Problem

`_apply_consolidation` creates the consolidated node with `tags=["consolidated"]` and leaves
`tier` at the `CreateNodeRequest` default, `working`. `_find_consolidation_clusters` selects
every `working` node and excludes nothing by tag, both when picking a cluster seed and when
validating a candidate member. A consolidation output is therefore eligible as a consolidation
input on the next run. Two consolidated siblings are *short* by construction (3-8 sentences),
so they fit a cluster more easily than their sources ever did; when they re-cluster, the new
summary is written from two summaries while the real sources sit in `archival`, no longer read.
Each pass is lossy; applied to its own output the loss compounds and cannot be recovered.

Verified by reading `upstream/main:src/ormah/background/consolidator.py` (the two `SELECT`s)
and `upstream/main:src/ormah/models/node.py` (`tier: Tier = Tier.working` default).

## Decision

A `consolidated` node is **terminal** for cluster discovery: it is never a seed and never a
member of a consolidation cluster. A summary is the primary representation of its cluster and
is not re-summarised.

Consequence accepted: when genuinely new related memories arrive, they form a *second* summary
next to the first instead of updating it. Merging the two is `duplicate_merger`'s job (human-
curated proposals, ADR 0005). Re-consolidating from the original sources — the semantically
ideal behaviour — needs provenance that #258 is building and interacts with #260's cluster
splitting; it is a follow-up, recorded on the issue, not part of this change.

Alternatives rejected:

- *Member yes, seed no, at most one per cluster* — still rewrites a summary from a summary
  (S1 → S2 → S3), the same defect at a lower rate.
- *Re-consolidate from sources* — right semantics, wrong size for this issue (see above).
- *Document the current behaviour* — the short-summary size constraint pushes toward
  re-clustering, so "summary of summary" would be a frequent accident, not a rare choice.

## Change

One file: `src/ormah/background/consolidator.py`, only `_find_consolidation_clusters`.

- A module constant holds the exclusion predicate, written once and used in both queries:

  ```python
  _NOT_CONSOLIDATED = (
      "NOT EXISTS (SELECT 1 FROM node_tags WHERE node_id = nodes.id AND tag = 'consolidated')"
  )
  ```

- Seed query becomes
  `SELECT id, title, content, space FROM nodes WHERE tier = 'working' AND {_NOT_CONSOLIDATED}`.
- Member query becomes
  `SELECT id, title, content, space, tier FROM nodes WHERE id = ? AND {_NOT_CONSOLIDATED}`;
  the existing `tier != "working"` check on the fetched row stays.
- Docstring states that `consolidated`-tagged nodes are terminal and are excluded from
  discovery as seed and as member.

`node_tags(tag)` is already indexed (`idx_node_tags_tag`, `schema.sql`). No schema change, no
migration, no settings. `_apply_consolidation`, the prompt, `run_consolidation` and
`_consolidate_cluster` are untouched — PR #260 (#192) edits those and not discovery, so the
two changes do not conflict.

## Tests

`tests/test_background/test_consolidator.py`. Both tests must be red on `upstream/main`.
Embeddings are real (fastembed via the `engine` fixture); identical content yields
similarity 1.0, which is what makes clustering deterministic here.

1. **Unit — discovery never returns a consolidated id.** Create two similar raw `working`
   nodes and two `working` nodes with the *same* content tagged `consolidated`. Call
   `_find_consolidation_clusters(engine)` and assert no returned cluster contains a
   consolidated id. Worked example without the fix: the seed "consolidated A" pulls
   "consolidated B" (similarity 1.0) and the raw pair into one cluster of 4 — the assertion
   fails. With the fix: one cluster of the two raw nodes only.

2. **End to end — the issue's scenario.** `consolidation_max_cluster_nodes = 2`, four
   similar sources, `llm_generate` mocked to return one fixed summary. Run 1 produces N1 and
   N2 (both `working`, identical content). Run 2 must create **no** new node; N1 and N2 remain
   `working`; no `derived_from` edge targets N1 or N2. Without the fix run 2 consolidates
   N1 + N2 into N3 — the summary-of-summaries.

Fixture check to do first in the red phase: `engine.remember(..., tags=["consolidated"])`
must populate `node_tags`. If test 1 is green *before* the fix, this assumption failed and the
predicate has to read tags another way (the markdown), not the index.

## Out of scope

- Re-consolidation from sources when new related memories arrive (follow-up after #258).
- Idempotency under retry (#258).
- The Claude-in-the-loop maintenance route (#259).
- Anything in `_apply_consolidation`, the prompt, or the LLM route.

## Verification

Island gates from `FORK-WORKFLOW.md`, in this order: import gate (`ormah.__file__` inside
`ormah-wt-261/`), red run of the two tests, fix, green run of the full suite with clean
`HOME`, `git log --oneline upstream/main..HEAD` showing only this change's commits.

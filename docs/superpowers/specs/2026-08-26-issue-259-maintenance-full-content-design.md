# Issue #259 — Claude-in-the-loop consolidation must summarize from full content

- **Date:** 2026-08-26 (v3 — rewritten after `/council` rejected v1 and v2)
- **Issue:** [r-spade/ormah#259](https://github.com/r-spade/ormah/issues/259)
- **Branch:** `fix/259-maintenance-full-content` (island cut from `upstream/main` @ `90c431e`)
- **Worktree:** `Tools/ormah-wt-259`

## Problem

Phase 1 of the `run_maintenance` two-call protocol hands consolidation clusters to the Claude
maintenance agent through **two** truncation points, not one:

1. `MemoryEngine.get_maintenance_batches` normalizes every candidate through a single `_norm`
   helper that cuts content to 400 characters (`src/ormah/engine/memory_engine.py:1828`). All
   four batches share it — link, conflict, merge, and consolidation.
2. The agent does not read that dict. `ormah-maintenance` calls `mcp__ormah__run_maintenance`;
   `_dispatch` returns `_format_maintenance_batches`, which cuts cluster content to **200**
   characters (`src/ormah/adapters/mcp_adapter.py:183`) and screening pairs to 300 (`:141-144`).

Phase 2, `apply_maintenance_results` (`memory_engine.py:1902`), feeds the agent's consolidations
to `_apply_consolidation`, which **demotes the sources to `archival`**. So a summary written from
a 200-character view of each source displaces the full sources from the whisper pool. The model
cannot preserve what it was never shown, and the output carries no scar.

Truncation is correct for the other three batches: link, conflict and merge are *screening*
views, where the agent decides whether a pair is worth acting on and the full text is not the
subject of the decision.

**Both cuts must go, in the same PR.** Fixing only `_norm` — as this spec's v1 proposed — leaves
the agent reading 200 characters, which is worse than the 400 the issue denounces. This was found
by the Cursor peer in the `/council` run of 2026-08-26 and confirmed by reading the island.

### Second defect, found while reading the code (not in the issue)

`_find_consolidation_clusters` selects `id, title, content, space`
(`src/ormah/background/consolidator.py:40`, and the by-id re-read at `:78`) — **no `type`**.
The other three finders do select it. Because `_norm` reads `node.get("type", "")`, every
consolidation cluster node reaches the agent with `"type": ""`, while phase 2 asks the agent for
a `type` back (`c.get("type", "fact")`, `memory_engine.py:1912`). The agent picks the consolidated
node's type without seeing the type of a single source.

Verified by execution, a probe against the island's own venv:

```
CLUSTERS: 1
KEYS: ['content', 'id', 'space', 'title']
```

## Decisions

### Trim to the longest prefix that fits — never slice a node

A cluster whose serialized size exceeds `claude_maintenance_cluster_max_chars` is trimmed to the
**longest prefix that fits**. The cluster already arrives ordered by `_find_consolidation_clusters`
— seed first, then matches by descending similarity — so the prefix keeps the most central and
the most similar nodes. Content is never sliced. Nodes left out stay in `working` and return on
the next cycle. If the prefix cannot reach `consolidation_min_cluster_size`, the cluster is
dropped entirely with a WARNING naming it.

**v2 proposed greedy bin-packing, and it was wrong.** Both `/council` peers converged on it and I
confirmed each case by executing the specified helper:

```
[500,500,400,400], budget 900   -> [[500,400]]        2 of 4 nodes lost
                                                       (optimal: [[500,400],[500,400]])
seed 600 + m1 400 + m2 400      -> [['m1','m2']]      the SEED is dropped silently
5 nodes of 12001, budget 24000  -> []                 empty caplog
```

Next-fit closes a bin whenever the next node does not fit, and the `len(sub) >= 2` filter then
deletes every singleton it created — so it discards nodes that would have paired, and it tends to
discard the seed, the most central node of the cluster. A prefix has no bins, so it has no orphan
singletons, and the seed is by definition the first element it keeps.

**v1 proposed no cap at all, and that was wrong too.** `MemoryNode.content` has no `max_length` and
`ingest_max_content_chars` is 100000 (`config.py:279`), so the uncapped worst case is ~2M
characters. If any layer truncates the tool result silently — the Claude Code host, or
`truncateHead` in the Pi plugin — the #192 defect returns in full: partial view, sources archived
all the same.

Accepted trade-off: a cluster that does not fit whole consolidates only its prefix; the tail
waits a cycle. By #192's measurement (5.923 nodes, 301 reconstructed consolidation events), no
historical event would have been trimmed at any budget >= 16000, so this is a tail safety net,
not the common path.

### The budget measures the serialized node, not raw content

`len(json.dumps(node, ensure_ascii=False))` on the **already normalized** node, not
`len(node["content"])`.

v2 budgeted raw content, which measures the wrong thing: the normalized node also carries `id`,
`title`, `type` and `space`, and JSON escaping can multiply size — two contents of 12.000 NUL
characters satisfy a 24000 raw budget and serialize to ~144k. The Codex peer found this.

### A setting of its own, not #192's

New setting `claude_maintenance_cluster_max_chars`, default **24000**, applied per cluster.

The default reuses #192's measurement because it was taken on this same store: worst real event
12.961 chars, theoretical worst case 24.038.

**Batch bound.** One prefix per cluster and at most 4 clusters gives a consolidation payload of at
most `4 x 24000 = 96_000` serialized characters — true by construction, unlike v2's number. The
phase-1 tool result also carries the three screening batches (up to 25 pairs each at 300 chars,
roughly 45k), so the whole response is bounded at ~141k characters, about 35k tokens.

### Trim applied in `get_maintenance_batches`, not in the finder

`_find_consolidation_clusters` is shared with the background consolidator, which has its own
budget policy on PR #260. Trimming inside it would impose this route's policy on that one. The
trim happens in `get_maintenance_batches`, after `_norm`, so it measures exactly what ships and
the MCP formatter needs to know nothing about budgets.

### `type` fix included

One column in a SELECT, same defect shape ("the model cannot preserve what it was never shown"),
in code this PR already touches. Accepted trade-off: the diff is wider than #259 literally asks.
The executor applies it to the queries **as they stand in the island**, because #261 (PR #263,
open) adds a `_NOT_CONSOLIDATED` filter to those same lines; a copy-pasted SELECT would revert it.

## Design

### Change (a) — explicit content limit on `_norm`

```python
def _norm(node: dict, content_limit: int | None = 400) -> dict:
    content = node.get("content") or ""
    return {
        "id": node.get("id", ""),
        "title": node.get("title", ""),
        "type": node.get("type", ""),
        "space": node.get("space", ""),
        "content": content if content_limit is None else content[:content_limit],
    }
```

Screening batches keep calling `_norm(...)` with no argument. Only consolidation passes
`content_limit=None`.

### Change (b) — trim oversized clusters in `get_maintenance_batches`

A module-level helper, testable without going through the engine:

```python
def _select_cluster_within_budget(
    cluster: list[dict], budget: int, min_size: int
) -> list[dict]:
    """Longest prefix of `cluster` whose serialized size fits `budget`.

    The cluster arrives seed-first, matches by descending similarity, so the
    prefix keeps the most central nodes. Nodes are never sliced; those left out
    stay in the working tier. Returns [] when the prefix cannot reach `min_size`.
    """
```

Applied to the **normalized** cluster, so the measurement is of what actually ships:

```python
        cluster_budget = getattr(self.settings, "claude_maintenance_cluster_max_chars", 24000)
        min_size = self.settings.consolidation_min_cluster_size
        consolidation_clusters = [
            trimmed
            for cluster in consolidation_clusters
            if (trimmed := _select_cluster_within_budget(
                [_norm(n, content_limit=None) for n in cluster], cluster_budget, min_size
            ))
        ]
```

### Change (c) — the MCP formatter stops cutting cluster content

`src/ormah/adapters/mcp_adapter.py:183`: emit `n['content']` whole for consolidation clusters.
The `[:300]` in `_pair_block` stays — screening is unchanged.

### Change (d) — `type` in the cluster SELECT

`consolidator.py` lines 40 and 78: add `type` to the selected columns, preserving whatever else
those lines carry in the island at execution time.

### Out of scope

`apply_maintenance_results`, `_apply_consolidation`, the MCP tool schema, the background
consolidator's own budget (PR #260), and every other settings default.

## Testing

All tests fail before their fix. None iterates a possibly-empty list — each asserts non-empty
first, so none can pass vacuously. Cluster formation is made deterministic with
`consolidation_cluster_threshold = 0.0` and `consolidation_min_cluster_size = 2`, which a probe
proved sufficient with two similar nodes.

**Full content, both cut points:**

1. `test_consolidation_cluster_carries_full_content` — two 600-char nodes; the batch's cluster
   nodes carry all 600. Red today at `400 != 600`.
2. `test_formatter_emits_full_cluster_content` — `_format_maintenance_batches` with a 600-char
   cluster node contains all 600. **Red today at `[:200]`** — the test v1 never had, and the
   reason v1 would have shipped without fixing the issue.
3. `test_formatter_still_truncates_screening_pairs` — pair content stays at 300.

**The screening guard, rebuilt:**

4. `test_norm_truncates_screening_batches` — monkeypatches `_find_link_candidates` to return
   600-char content, then asserts the batch cut it to 400. v1's version asserted on the real
   finder, which already cuts to 400 in `_node_dict` before `_norm` runs (`auto_linker.py:154`,
   and the two `_nd` at `conflict_detector.py:199` / `duplicate_merger.py:222`) — so it stayed
   green even with `_norm`'s limit removed and guarded nothing. Both peers found this.

**Trim policy:**

5. `test_cluster_within_budget_is_returned_whole` — nothing is trimmed when it fits.
6. `test_oversized_cluster_is_trimmed_to_a_prefix` — the prefix keeps the leading nodes, every
   kept node's content is intact, and the dropped ones are absent.
7. `test_seed_is_never_dropped` — the case that killed v2: a large seed followed by smaller
   matches. The seed must be in the result. Red against a next-fit implementation.
8. `test_cluster_below_min_size_after_trim_is_dropped_with_warning` — `caplog` names the cluster.
9. `test_budget_counts_serialized_size_not_raw_content` — a node whose content is short but whose
   JSON escaping is large is budgeted by its serialized size. Red against a `len(content)` budget.
10. `test_worst_case_cardinality_stays_bounded` — 4 clusters of `max_cluster_nodes` pairable
    nodes; every emitted cluster serializes within budget, the batch within `4 x budget`, and the
    result is non-empty (so it cannot pass by emitting nothing).

**Type:**

11. `test_clusters_carry_node_type` — `_find_consolidation_clusters` emits `type`.
12. `test_consolidation_cluster_carries_type` — it survives into the batch.

## Verification gates (FORK-WORKFLOW.md)

- **Import gate** — verified for this island: `.venv/bin/python -c "import ormah; print(ormah.__file__)"`
  prints `/Users/andre/Documents/GitHub/Tools/ormah-wt-259/src/ormah/__init__.py`.
- **Test runs** — `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest`,
  redirected to a file with `PYTEST_EXIT=$?` appended (never piped to `tail`).
- **Island gate** — `git log --oneline upstream/main..HEAD` shows only this change's commits.
- **Collision check** — against PR #260 (`consolidator.py` budget) and PR #263 / #261
  (`_NOT_CONSOLIDATED` on the same SELECT lines).
- **Spec location** — this document lives on `local-main`: `docs/superpowers/` is in the pre-push
  `PROTECTED` allowlist and would block the contribution branch.

## Review history

Two `/council` runs, both profiles architecture+performance, both with Cursor and Codex
returning `needs-attention` and neither approving.

- **v1**, run `82c0d868-82a0a0a5-78c861c9`: 7 findings, none rejected. Falsified both of v1's
  load-bearing premises — that `_norm` was the single cut point (the MCP formatter cuts at 200),
  and that an uncapped batch could not lose data.
- **v2**, run `5bf5592c-8c32273c-050cf979`: 4 findings, all HIGH, none rejected. Both peers
  converged on the next-fit packing discarding pairable nodes and on the 192k bound measuring
  only raw content.

**Note on the review setup:** the peers review the working tree of `Tools/ormah`, which is on
`local-main` (~693 commits ahead), while this plan targets `upstream/main`. In the v2 run the
Cursor peer recommended reusing `_split_cluster_to_fit` "already in this tree" — it exists on
`local-main` and on the #192 branch, but **not** on `upstream/main`. Peer behavioural findings
hold; every file or symbol reference must be re-checked against the island before acting on it.

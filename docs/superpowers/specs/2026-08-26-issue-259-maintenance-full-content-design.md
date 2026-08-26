# Issue #259 — Claude-in-the-loop consolidation must summarize from full content

- **Date:** 2026-08-26 (v2 — rewritten after `/council` rejected v1)
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

### Split on overflow — never skip, never slice

A cluster whose total content exceeds `claude_maintenance_cluster_max_chars` is **split** into
sub-clusters by greedy bin-packing in the order `_find_consolidation_clusters` already returns
(seed first, then matches by descending similarity). A sub-cluster left with a single node is
dropped; a single node larger than the whole budget stays in `working` with a WARNING.

This mirrors the #192 decision of 2026-08-24, where skipping was rejected explicitly — a skipped
cluster is a consolidation that never happens. Slicing is the defect itself.

v1 of this spec proposed **no cap at all**, on the argument that the agent's window is orders of
magnitude larger than any cluster and that the cost of being wrong was "latency, not data loss".
Both `/council` peers falsified that independently: `MemoryNode.content` has no `max_length` and
`ingest_max_content_chars` is 100000 (`config.py:279`), so the uncapped worst case is 4 clusters
x 5 nodes x 100k = **~2M characters**. If any layer truncates the tool result silently — the
Claude Code host, or `truncateHead` in the Pi plugin — the #192 defect returns in full: partial
view, sources archived all the same. The claim that no data could be lost was wrong.

### A setting of its own, not #192's

New setting `claude_maintenance_cluster_max_chars`, default **24000**, applied per cluster.

The default reuses #192's measurement because it was taken on this same store: 5.923 nodes and
301 reconstructed consolidation events, worst real event 12.961 chars, theoretical worst case
24.038. At any budget >= 16000 none of the 301 historical events would have been split, so the
split is a safety net for the tail, not the common path. Four clusters at this budget cap the
batch at ~96k characters.

It is **not** `consolidation_max_prompt_chars`: that setting exists only on PR #260, still open,
so reusing it would chain this PR behind that one. The consumers also differ — the Claude agent's
window is not Ollama's `num_ctx`, so a shared number would be coincidence rather than design.

### Split applied in `get_maintenance_batches`, not in the finder

`_find_consolidation_clusters` is shared with the background consolidator, which has its own
budget policy on PR #260. Splitting inside it would impose this route's policy on that one. The
split happens in `get_maintenance_batches`, so the emitted batch is already split and the MCP
formatter needs to know nothing about budgets — one decision point, one place to test.

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

### Change (b) — split oversized clusters in `get_maintenance_batches`

A module-level helper, so it is testable without going through the engine:

```python
def _split_cluster_to_budget(cluster: list[dict], budget: int) -> list[list[dict]]:
    """Greedy bin-pack a cluster into sub-clusters within `budget` characters.

    Order is preserved (seed first, then descending similarity). Sub-clusters of
    fewer than 2 nodes are dropped: a single node has nothing to consolidate with.
    """
```

A node whose own content exceeds `budget` forms a one-node sub-cluster, which is then dropped,
and the engine logs a WARNING naming the node id and its size.

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

**Split policy:**

5. `test_oversized_cluster_is_split_not_truncated` — a cluster over budget yields two or more
   sub-clusters, and every node's content is intact in whichever sub-cluster holds it.
6. `test_single_node_subcluster_is_dropped` — a leftover of one node does not reach the batch.
7. `test_node_larger_than_budget_is_dropped_with_warning` — the node stays out and a WARNING
   names it (`caplog`).
8. `test_worst_case_cardinality_stays_bounded` — 4 clusters x 5 nodes of 100k chars; the
   serialized batch stays within 4 x budget. This is the test both peers asked for: proof that
   a genuinely large payload remains operable, which the 600-char tests do not provide.

**Type:**

9. `test_clusters_carry_node_type` — `_find_consolidation_clusters` emits `type`.
10. `test_consolidation_cluster_carries_type` — it survives into the batch.

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

`/council` 2026-08-26, run `82c0d868-82a0a0a5-78c861c9`, profiles architecture+performance.
Cursor and Codex both returned `needs-attention`; neither approved. Seven findings, none
rejected. v1's two load-bearing premises — that `_norm` was the single cut point, and that an
uncapped batch could not lose data — were both falsified. This document is the rewrite.

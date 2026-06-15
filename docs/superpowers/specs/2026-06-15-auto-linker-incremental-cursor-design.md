# Auto-linker incremental cursor (#26)

**Date:** 2026-06-15
**Branch:** `perf/auto-linker-incremental` (off 0.11.0)
**Status:** approved design, pending implementation plan
**Issue:** upstream #26 — `auto_linker` is O(n²): full-table scan × brute-force vector search × LLM-per-candidate every run.

## Problem

`run_auto_linker` (`src/ormah/background/auto_linker.py`) scans **every** node each run and,
per node, re-encodes its text, runs a brute-force `vec_store.search` (itself O(n)), and calls
the LLM per surviving candidate. Total cost is **O(n²)** compute + O(candidates) LLM calls,
repeated every `auto_link_interval_minutes` (default 1440 = 24h). `_find_link_candidates`
(the maintenance-protocol preview, via `get_maintenance_batches` → `maintenance_manager`)
has the **same shape**, additionally sorting with `ORDER BY RANDOM()`.

`auto_link_checked` already skips already-evaluated pairs, but only *after* the expensive
encode+search — so the scan cost is unbounded in `n` regardless. On the real store
(8.355 nodes) most of each run is spent re-encoding and re-searching nodes that yield
nothing (4.776 nodes — 57% — have never produced an evaluated pair).

## Approach (chosen: A — watermark in `meta`)

A single mechanism serves both **backfill** (drain the historical backlog) and **incremental**
(only new/changed nodes), differing only in the watermark's initial value.

### State & config
- **`meta.auto_link_watermark`** — ISO timestamp of the `updated` field of the last
  fully-processed node. Absent ⇒ treated as epoch (`""`) ⇒ backlog drains from the oldest
  node. (`meta` is the existing key-value table that already holds `last_maintenance_run`.)
- **New setting `auto_link_max_nodes_per_run: int = 500`** — bounds the scan (the outer
  loop). `auto_link_max_edges_per_run` (500) stays as a secondary write guard.
- No new table, no new dependency, no change to the `nodes` schema.

### `run_auto_linker`
Replace `SELECT id, content, title, type, space FROM nodes` (all rows) with:

```sql
-- watermark is the composite (updated, id) of the last processed node;
-- shown here as a single column for readability (see "Timestamp ties").
SELECT id, content, title, type, space, updated
FROM nodes
WHERE (updated, id) > (:wm_updated, :wm_id)
ORDER BY updated ASC, id ASC LIMIT :max_nodes_per_run
```

The inner logic is unchanged: encode → `vec_store.search` → threshold/cross-space penalty →
`auto_link_checked`/existing-edge skip → `_llm_classify_link` → `_apply_edge`. After the loop,
write `auto_link_watermark = updated of the last fully-processed node` to `meta` (inside a
transaction). Per-run cost: **O(batch · n)** instead of O(n²).

### `_find_link_candidates` (decision (a): in scope)
Extract the candidate scan into a shared incremental generator used by both callers. It
**reads** the same watermark but does **not** advance it (it is a side-effect-free preview),
and replaces `ORDER BY RANDOM()` with the same deterministic `updated ASC` window. This
removes the duplication the issue calls out and fixes both O(n²) sites with one technique.

## Correctness

- **No links lost:** every possible pair is discovered when the *newer* node of the pair is
  processed — `vec_store.search` is symmetric and `auto_link_checked` deduplicates. The older
  side need not be re-scanned.
- **Updates re-enter Δ:** node update bumps `updated` *and* deletes the node's
  `auto_link_checked` rows (`memory_engine.py` :806/:850/:1201/:1206), so it naturally
  re-appears above the watermark.
- **Partial run / crash / `max_edges` hit mid-node:** watermark only advances to the last
  *complete* node; reprocessing is idempotent (checked pairs are skipped; no duplicate edges).
- **Timestamp ties:** cursor is the composite `(updated, id)` so equal `updated` values are
  neither skipped nor repeated.

## Testing (TDD — tests first)

1. Run processes only `updated > watermark`, never the full table; respects the batch limit.
2. Watermark advances to the last processed node's `updated`; never past unprocessed nodes.
3. Backlog drains across multiple runs; once Δ is empty a run is cheap (no encode/search).
4. Updated node re-enters Δ; an old↔new pair is created when the new node is processed.
5. Absent watermark ⇒ epoch; empty store ⇒ no-op.
6. `_find_link_candidates` returns only candidates in the watermark window, deterministically,
   without advancing the watermark.
7. Existing `auto_link_checked` tests stay green (no re-check, invalidation on update).

## Out of scope

- The edge-quality concern (local gemma3:4b classifies ~90% of pairs as `supports`, ~16.7k
  edges) — a separate issue, not this perf fix.
- Reusing stored embeddings instead of re-encoding each Δ node — possible later optimization;
  with a bounded batch the re-encode is no longer the bottleneck.
- ANN for the vector search itself (upstream #25) — separate; benefit compounds once added.
- Tier-based prioritization of the drain order — addable later via `ORDER BY` within approach A.

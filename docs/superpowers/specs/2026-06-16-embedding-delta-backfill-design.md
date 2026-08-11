# Embedding Delta Backfill + Continuous Reconciliation (#32) — Design

> **Issue:** [#32](https://github.com/r-spade/ormah/issues/32) — a single missing embedding triggers a full ~25-min re-embed of all nodes (swallowed embed failures + O(n) recovery).

## Problem

On every server restart, `MemoryEngine.startup()` re-embeds the **entire** node set
(~9k memories, ~25 min via local Ollama, synchronous, blocking the uvicorn port bind)
whenever the vector store is missing **even a single** entry.

Two compounding defects:

1. **Leak (creates the gap).** `_index_embedding` swallows encode/upsert failures with no
   retry. The node row is already persisted, so when Ollama is slow/down during a
   `remember`/ingest (typical for the overnight `session_watcher` batch, or a cold start),
   the vector is silently never written. Gaps accumulate. Reinforced by:
   - `builder.full_rebuild` runs `DELETE FROM node_vectors` **without** re-embedding (the
     builder has no encoder).
   - sqlite-vec `vec0` can silently drop rows in large transactions.
2. **Amplifier (O(n) recovery).** `startup()` uses a coarse `vec_count < node_count` check
   and calls `_reindex_all_embeddings()`, which re-embeds **all** N nodes synchronously
   before the HTTP port binds — even for a 1-node gap.

Real-store evidence (~9k nodes): two full re-embeds in one day — an 886-node gap (Ollama
unstable overnight) and a **1-node** gap (still paid a full ~25-min re-embed).

## Goal

Bound startup embedding cost to **O(gap)** and make it **non-blocking**:
- Move embedding recovery out of the synchronous startup path → the port binds immediately.
- Recover only the **missing** vectors (delta), not all nodes.
- Make the write path **robust** (bounded retry) and add a **continuous reconciliation job**
  that heals gaps formed at runtime (the 886-node case formed overnight, not at startup),
  without requiring a restart.

## Non-goals

- Stale-vector repair. `builder.incremental_update()` calls `_remove_node(keep_vectors=True)`
  on a *changed* file, keeping the old (now-stale) vector. That is a **distinct** defect
  (outdated vector, not missing vector) and is out of scope for #32.
- ANN / vector-search-scale work (#25), auto_linker O(n²) (#26), bounded forgetting (#28).
  A healthy vector store helps them but they are independent.

## Architecture

Replace the synchronous startup re-embed with a **recurring reconciliation job** that runs in
the background scheduler, with two modes:

| Mode | Trigger | Action | Cost |
|------|---------|--------|------|
| **Delta** | `vec_count < node_count` (missing rows) | anti-join → embed only missing nodes | O(gap) |
| **Schema bump** | `stored_version < _EMBEDDING_SCHEMA_VERSION` | full re-embed; bump version **only on success** | O(n), rare |

The job:
- is registered in `start_scheduler()` like every other job (`tracked()` + `JobTracker`,
  `misfire_grace`, APScheduler default `max_instances=1` → no overlap);
- is driven by a new `embedding_backfill_interval_minutes` setting (default 60), which the
  operator can set to `999999` to disable in-process and let the **sleep-cycle** drive it —
  consistent with the existing maintenance jobs;
- is included in `POST /admin/tasks/run-all` (`_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`,
  `_SLEEP_CYCLE_ORDER`) so the 02:00 sleep-cycle pass runs it;
- is given a `next_run_time` a few seconds after start so it fires **once right after the
  port binds** on every restart (the core #32 recovery), regardless of the interval setting.
  This is the one intentional deviation from the other jobs (which do not run at startup);
  cost is ~0 when there is no gap (the delta anti-join returns 0 rows).

### `MemoryEngine.backfill_embeddings()` (new)

```python
def backfill_embeddings(self) -> dict:
    count = SELECT count(*) FROM nodes
    stored_version = int(meta['embedding_schema_version'] or 0)
    if stored_version < _EMBEDDING_SCHEMA_VERSION:
        rows = SELECT id, title, content FROM nodes            # full re-embed
        ok = self._embed_node_rows(rows)
        if ok:                                                 # bump only on success
            meta['embedding_schema_version'] = _EMBEDDING_SCHEMA_VERSION
    else:
        rows = SELECT id, title, content FROM nodes
               WHERE id NOT IN (SELECT id FROM node_vectors_rowids)   # delta
        if rows:
            self._embed_node_rows(rows)
    return {"mode": ..., "embedded": ..., "vec_count": ..., "node_count": ...}
```

Bumping the schema version only **after** a successful full re-embed makes a crash mid-embed
recoverable: on the next run, `stored_version` is still old → it retries the full re-embed.

### `MemoryEngine._embed_node_rows(rows)` (extracted)

Extracted from the current `_reindex_all_embeddings`: build embeddings, then `upsert_batch`
in chunks of 100 with `PRAGMA wal_checkpoint(TRUNCATE)` between chunks (the existing
sqlite-vec mitigation), then verify `vec_count`. Returns whether the verify passed.
`_reindex_all_embeddings()` becomes a thin wrapper `self._embed_node_rows(all_nodes)` so the
public reindex path keeps working unchanged.

### `MemoryEngine._index_embedding` robustness

Wrap encode+upsert in a bounded retry loop (`embedding_index_max_retries`, exponential backoff
`embedding_index_retry_backoff_seconds`). After exhausting retries, log a warning and return —
the gap is left for the reconciliation job to repair. Backoff stays short so the inline
`remember`/ingest path is not blocked for long. The retry reduces gap frequency; the
reconciliation job is the eventual-consistency guarantee.

### `MemoryEngine.startup()` change

Remove the synchronous embedding block (current L121–138) entirely, including the
schema-version read/bump (which moves into `backfill_embeddings`). Keep the `count == 0 →
full_rebuild` and the FTS-rebuild blocks. After this change `startup()` no longer touches the
encoder, so the port binds without waiting on embeddings.

### `embedding_backfill.run_embedding_backfill(engine)` (new module)

Thin job wrapper following the existing `run_decay(engine)` / `run_auto_linker(engine)`
pattern: calls `engine.backfill_embeddings()` and returns its summary for the `JobTracker`.

## Configuration (new settings in `config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `embedding_backfill_interval_minutes` | 60 | reconciliation job interval; set `999999` to run only via sleep-cycle |
| `embedding_index_max_retries` | 2 | bounded retries in `_index_embedding` before giving up |
| `embedding_index_retry_backoff_seconds` | 0.5 | base backoff (exponential) between retries |

## Concurrency / safety

- Job runs in the `BackgroundScheduler` thread, like the other jobs; `max_instances=1`
  prevents a slow run from overlapping the next tick.
- Encoding happens outside any DB transaction; upserts are chunked at 100 with a checkpoint
  between chunks, releasing the write lock between blocks — avoids the long-lock freeze
  pattern of #18/#19.
- `next_run_time` is set post-bind so the first run never blocks the port bind.

## Testing

Unit (engine fixture, `.venv/bin/python -m pytest`):
- **delta**: seed N nodes, delete K vectors, run `backfill_embeddings` → exactly K re-embedded,
  `vec_count == node_count`, mode == "delta".
- **delta no-op**: full store → 0 embedded.
- **schema bump**: `stored_version < current` → all re-embedded, version bumped to current.
- **schema bump failure**: encoder raises → version **not** bumped (re-read meta).
- **`_index_embedding` retry**: transient failure then success writes the vector; exhausting
  retries leaves the gap and does **not** raise.
- **`startup()` fast path**: startup no longer calls the encoder / `_reindex_all_embeddings`.

Integration:
- job registered in the scheduler and present in `_SLEEP_CYCLE_ORDER`; `run-all` invokes it.

## Files

| File | Change |
|------|--------|
| `src/ormah/config.py` | 3 new settings |
| `src/ormah/engine/memory_engine.py` | remove startup embed block; extract `_embed_node_rows`; add `backfill_embeddings`; retry in `_index_embedding` |
| `src/ormah/background/embedding_backfill.py` | new `run_embedding_backfill(engine)` |
| `src/ormah/background/scheduler.py` | register `embedding_backfill` job (interval + post-bind `next_run_time`) |
| `src/ormah/api/routes_admin.py` | add to `_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`, `_SLEEP_CYCLE_ORDER` |

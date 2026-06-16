# Embedding Delta Backfill (#32) Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each subagent gets THIS overview + its own task file (`NN-*.md`). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bound startup embedding cost to O(gap) and make it non-blocking — recover only missing vectors (delta) via a recurring background reconciliation job, instead of synchronously re-embedding all N nodes before the port binds.

**Architecture:** Move embedding recovery out of `MemoryEngine.startup()` into a new `embedding_backfill` background job with two modes — **delta** (anti-join → embed only nodes missing from `node_vectors_rowids`) and **schema bump** (full re-embed, version bumped only on success). The job follows the existing scheduler pattern (`tracked()` + `JobTracker`, interval setting), is included in the `/admin/tasks/run-all` sleep-cycle pass, and fires once right after the port binds via `next_run_time`. The write path (`_index_embedding`) gains bounded retry; the job is the eventual-consistency guarantee.

**Tech Stack:** Python 3.11, SQLite (`sqlite3` via `Database`) + sqlite-vec `vec0`, pydantic-settings, APScheduler (`BackgroundScheduler`), local encoder (Ollama/fastembed), pytest (`asyncio_mode=auto`, default run excludes `integration`).

**Spec:** `docs/superpowers/specs/2026-06-16-embedding-delta-backfill-design.md`

---

## Conventions for every task

- Run tests with the working-tree interpreter: `.venv/bin/python -m pytest <path> -v`
  (per `[[ormah-dev-run-setup]]` — the global `uv`-tool ormah is a different version).
- Lint touched files: `.venv/bin/ruff check src/ tests/` (line-length 100, py311).
- The `engine` pytest fixture (`tests/conftest.py`) gives a live `MemoryEngine` with
  `engine.remember(CreateNodeRequest(...)) -> (node_id, msg)` (which embeds via
  `_index_embedding`), `engine.db.conn`, `engine.file_store.load(id)`,
  `engine.backfill_embeddings()`, `engine.settings`.
- `_EMBEDDING_SCHEMA_VERSION` is currently `2` (`memory_engine.py:45`). The shadow table
  `node_vectors_rowids` has an `id TEXT` column (verified) — the delta query joins against it.
- Commit after each task with the message shown in its final step.

## File map

| File | Responsibility | Task |
|------|----------------|------|
| `src/ormah/config.py` | 3 new settings + validators | 01 |
| `src/ormah/engine/memory_engine.py` | extract `_embed_node_rows(nodes) -> (embedded, failed)` from `_reindex_all_embeddings` | 02 |
| `src/ormah/engine/memory_engine.py` | new `backfill_embeddings()` (delta + schema-bump modes) | 03 |
| `src/ormah/engine/memory_engine.py` | bounded retry in `_index_embedding` | 04 |
| `src/ormah/engine/memory_engine.py` | remove synchronous embed block from `startup()` | 05 |
| `src/ormah/background/embedding_backfill.py` | new `run_embedding_backfill(engine)` job wrapper | 06 |
| `src/ormah/background/scheduler.py` | register `embedding_backfill` job (interval + post-bind `next_run_time`) | 07 |
| `src/ormah/api/routes_admin.py` | add to `_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`, `_SLEEP_CYCLE_ORDER` | 08 |

## Task order & dependencies

1. **01 Config** — no deps.
2. **02 `_embed_node_rows` extraction** — no deps (pure refactor; existing reindex tests stay green).
3. **03 `backfill_embeddings`** — needs 02 (calls `_embed_node_rows`).
4. **04 `_index_embedding` retry** — needs 01 (settings).
5. **05 Remove startup embed block** — needs 03 (recovery now lives in the job).
6. **06 Background job module** — needs 03 (calls `backfill_embeddings`).
7. **07 Scheduler registration** — needs 01 (interval setting) + 06 (`run_embedding_backfill`).
8. **08 Admin run-all / sleep-cycle** — needs 06.

## Key design points baked in (from spec)

- **Delta is O(gap):** `SELECT id, title, content FROM nodes WHERE id NOT IN (SELECT id FROM node_vectors_rowids)`.
- **Schema bump is crash-safe:** version is bumped **only after** a fully-successful re-embed
  (`failed == 0`); a crash mid-embed leaves the old version so the next run retries.
- **Non-blocking startup:** `startup()` no longer touches the encoder — the port binds immediately;
  the job's `next_run_time` (~10s post-start) does the first reconciliation off the bind path.
- **Operator control:** `embedding_backfill_interval_minutes` (default 60) can be set to `999999`
  to disable in-process and let the 02:00 sleep-cycle (`run-all`) drive it — like the other jobs.
- **Concurrency safety:** chunked upserts (100) + `wal_checkpoint(TRUNCATE)` release the write lock
  between blocks (avoids the #18/#19 long-lock freeze); APScheduler `max_instances=1` prevents overlap.

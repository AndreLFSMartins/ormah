# Embedding Delta Backfill (#32) Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each subagent gets THIS overview + its own task file (`NN-*.md`). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bound startup embedding cost to O(gap) and make it non-blocking — recover only missing vectors (delta) via a recurring background reconciliation job, instead of synchronously re-embedding all N nodes before the port binds. Recovery must be bounded even under permanent per-node failures and must not depend on the scheduler being healthy.

**Architecture:** Move embedding recovery out of `MemoryEngine.startup()` into a new `embedding_backfill` job with two modes — **delta** (anti-join → embed only nodes missing from `node_vectors_rowids`, O(gap)) and **schema bump** (re-embed all embeddable nodes once, then advance the version **unconditionally** after the pass). On a schema bump, any node that fails to encode has its **stale vector deleted** so it becomes genuinely missing — caught by the next delta run. A permanently-failing ("poison") node therefore stays visible in `missing` / `embedding_gap` forever and is retried (one row) each tick — never dropped, never masked. The job **raises while `missing > 0`** so `/admin/health` reflects the degradation. A scheduler-independent post-bind fallback retries with backoff until the gap closes or the attempt budget is exhausted, guaranteeing recovery even if `start_scheduler` fails. The write path (`_index_embedding`) gains bounded retry.

**Tech Stack:** Python 3.11, SQLite (`sqlite3` via `Database`) + sqlite-vec `vec0`, pydantic-settings, APScheduler (`BackgroundScheduler`), local encoder (Ollama/fastembed), pytest (`asyncio_mode=auto`, default run excludes `integration`).

**Spec:** `docs/superpowers/specs/2026-06-16-embedding-delta-backfill-design.md` · **Council:** `.council/council-result.md` (**R2: quarantine dropped** — replaced by delete-stale + advance-after-pass + delta-retries-missing).

---

## Conventions for every task

- Run tests with the working-tree interpreter: `.venv/bin/python -m pytest <path> -v` (per `[[ormah-dev-run-setup]]`).
- Lint touched files: `.venv/bin/ruff check src/ tests/` (line-length 100, py311).
- `engine` fixture (`tests/conftest.py`): `engine.remember(CreateNodeRequest(...)) -> (id, msg)` (embeds via `_index_embedding`), `engine.db.conn`, `engine.file_store.load(id)`, `engine.backfill_embeddings()`, `engine.settings`.
- `_EMBEDDING_SCHEMA_VERSION` is `2` (`memory_engine.py:46`). Shadow table `node_vectors_rowids` has an `id TEXT` column. The delta anti-join uses `LEFT JOIN node_vectors_rowids v ON n.id = v.id WHERE v.id IS NULL` (scales better than `NOT IN`).
- Commit after each task with the message shown in its final step.

## Core concepts (council R2 baked in — no quarantine)

- **embeddable node:** `_embedding_text(title, content)` is non-empty. The SQL proxy `_EMBEDDABLE_SQL` is `COALESCE(NULLIF(TRIM(content), ''), NULLIF(TRIM(title), '')) IS NOT NULL`. There is **no** quarantine concept — every embeddable node is always a candidate.
- **missing / `embedding_gap`:** embeddable nodes with no row in `node_vectors_rowids` (`LEFT JOIN ... WHERE v.id IS NULL`). This is the honest gap; `_missing_embeddable_count()` takes **no arguments**. A node that cannot be embedded stays here forever — visible, never masked.
- **schema bump:** when `stored_version < _EMBEDDING_SCHEMA_VERSION`, re-embed all embeddable nodes in one pass; for each node that fails to encode, **delete its stale vector** (so it becomes genuinely missing and is retried by delta); then advance the version **unconditionally** — the store has been fully reprocessed.
- **delta:** when `stored_version == _EMBEDDING_SCHEMA_VERSION`, embed only the missing embeddable nodes (anti-join), O(gap) — including any poison node, one row per tick.
- **health:** the job **raises while `missing > 0`** so `tracked()` records a failure and `/admin/health` reflects the degraded vector store (**council I6**).

## File map

| File | Responsibility | Task |
|------|----------------|------|
| `src/ormah/config.py` | 3 new settings + validators | 01 |
| `src/ormah/engine/memory_engine.py` | `_embed_node_rows(nodes) -> (embedded, failed)` with `vec_count` verification | 02 |
| `src/ormah/engine/memory_engine.py` | `_EMBEDDABLE_SQL` + `_missing_embeddable_count()` (no args) | 03 |
| `src/ormah/engine/memory_engine.py` | `backfill_embeddings()` (delta + schema-bump, delete-stale, advance-after-pass) | 03 |
| `src/ormah/engine/memory_engine.py` | bounded retry in `_index_embedding` | 04 |
| `src/ormah/engine/memory_engine.py` | remove synchronous embed block from `startup()` | 05 |
| `src/ormah/background/embedding_backfill.py` | `run_embedding_backfill(engine)` — raises while `missing > 0` | 06 |
| `src/ormah/background/scheduler.py` | register job (interval + post-bind `next_run_time`) | 07 |
| `src/ormah/api/routes_admin.py` | add to `_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`, `_SLEEP_CYCLE_ORDER` | 08 |
| `src/ormah/main.py` | scheduler-independent retry/backoff fallback | 09 |
| `src/ormah/engine/memory_engine.py` (`stats`) + integration test | observability (`embedding_gap`, `embedding_schema_version`) + E2E recovery | 10 |

## Task order & dependencies

1. **01 Config** — no deps.
2. **02 `_embed_node_rows` + vec_count verify** — no deps (pure refactor).
3. **03 `_missing_embeddable_count` + `backfill_embeddings`** — needs 01, 02.
4. **04 `_index_embedding` retry** — needs 01.
5. **05 Remove startup embed block** — needs 03.
6. **06 Background job (raises while incomplete)** — needs 03.
7. **07 Scheduler registration** — needs 01, 06.
8. **08 Admin run-all / sleep-cycle** — needs 06.
9. **09 Scheduler-independent fallback** — needs 06 (main.py kicks the job off a daemon thread, with retry/backoff, when the scheduler fails to start).
10. **10 Observability + E2E recovery** — needs 03, 06, 07.

## Key design points

- **Poison loop closed without quarantine:** the schema pass deletes the stale vector of any node that fails to encode and advances the version once; from then on delta retries only the *missing* nodes (O(gap), one row per poison node), never an unbounded full re-embed.
- **Poison node stays honest:** a permanently-failing node remains in `missing` / `embedding_gap` forever and is retried each tick — never dropped, never masked. There is no quarantine list and no fail-count meta.
- **Health (council I6):** `run_embedding_backfill` raises while `missing > 0`, so `tracked()` records a failure and `/admin/health` shows the degradation.
- **Scheduler-independent fallback (council I1b):** a daemon thread in `lifespan` runs reconciliation when `start_scheduler` did not start, **retrying with exponential backoff** until the gap closes or the attempt budget (`_BACKFILL_FALLBACK_MAX_ATTEMPTS=5`) is exhausted — not a one-shot. The scheduler still drives the recurring cadence on the happy path.
- **Non-blocking startup:** `startup()` no longer **embeds** nodes (it still warms the encoder via `_warmup_embedder()`). The port binds without waiting on embeddings.
- **Operator control:** `embedding_backfill_interval_minutes` (default 60) → `999999` disables in-process; the 02:00 sleep-cycle (`run-all`) drives it — like the other jobs.
- **Concurrency safety:** chunked upserts (100) + `wal_checkpoint(TRUNCATE)` release the write lock between blocks (avoids #18/#19); APScheduler `max_instances=1` prevents overlap.

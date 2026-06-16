# Embedding Delta Backfill (#32) Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each subagent gets THIS overview + its own task file (`NN-*.md`). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bound startup embedding cost to O(gap) and make it non-blocking — recover only missing vectors (delta) via a recurring background reconciliation job, instead of synchronously re-embedding all N nodes before the port binds. Recovery must be bounded even under permanent per-node failures and must not depend on the scheduler being healthy.

**Architecture:** Move embedding recovery out of `MemoryEngine.startup()` into a new `embedding_backfill` job with two modes — **delta** (anti-join → embed only nodes missing from `node_vectors_rowids`) and **schema bump** (re-embed all, version advanced only when the store is verified complete). Persistently-failing nodes are **quarantined** (bounded retry budget) so a single poison node cannot force an O(n) re-embed every tick. Completeness is verified against `vec_count`, not just encode success, so silent sqlite-vec drops are caught. A scheduler-independent post-bind one-shot guarantees recovery even if `start_scheduler` fails. The write path (`_index_embedding`) gains bounded retry.

**Tech Stack:** Python 3.11, SQLite (`sqlite3` via `Database`) + sqlite-vec `vec0`, pydantic-settings, APScheduler (`BackgroundScheduler`), local encoder (Ollama/fastembed), pytest (`asyncio_mode=auto`, default run excludes `integration`).

**Spec:** `docs/superpowers/specs/2026-06-16-embedding-delta-backfill-design.md` · **Council:** `.council/council-result.md` (R1 findings baked in).

---

## Conventions for every task

- Run tests with the working-tree interpreter: `.venv/bin/python -m pytest <path> -v` (per `[[ormah-dev-run-setup]]`).
- Lint touched files: `.venv/bin/ruff check src/ tests/` (line-length 100, py311).
- `engine` fixture (`tests/conftest.py`): `engine.remember(CreateNodeRequest(...)) -> (id, msg)` (embeds via `_index_embedding`), `engine.db.conn`, `engine.file_store.load(id)`, `engine.backfill_embeddings()`, `engine.settings`.
- `_EMBEDDING_SCHEMA_VERSION` is `2` (`memory_engine.py:45`). Shadow table `node_vectors_rowids` has an `id TEXT` column. The delta anti-join uses `LEFT JOIN node_vectors_rowids v ON n.id = v.id WHERE v.id IS NULL` (scales better than `NOT IN`).
- Commit after each task with the message shown in its final step.

## Core concepts (council R1 baked in)

- **embeddable node:** `_embedding_text(title, content)` is non-empty AND the node id is **not** quarantined. `embeddable_count` is the completeness target.
- **quarantine:** node ids that failed to embed `>= embedding_schema_max_attempts` cumulative times, persisted in `meta['embedding_quarantine']` (JSON list). Excluded from delta and from the completeness target so they cannot churn (fixes the poison-node O(n) loop, **C1**) or sit forever in the delta (**m1**).
- **completeness:** after any embed pass, `missing = count(embeddable nodes WHERE id NOT IN rowids)`. The schema version advances only when `missing == 0` (verified against `vec_count`, catching silent vec0 drops — **I2**). A run that ends with `missing > 0` or `failed > 0` reports **non-ok** to the JobTracker (**I4**).

## File map

| File | Responsibility | Task |
|------|----------------|------|
| `src/ormah/config.py` | 4 new settings + validators | 01 |
| `src/ormah/engine/memory_engine.py` | `_embed_node_rows(nodes) -> (embedded, failed)` with `vec_count` verification | 02 |
| `src/ormah/engine/memory_engine.py` | quarantine helpers + `embeddable`/`missing` queries | 03 |
| `src/ormah/engine/memory_engine.py` | `backfill_embeddings()` (delta + schema-bump, quarantine, completeness) | 03 |
| `src/ormah/engine/memory_engine.py` | bounded retry in `_index_embedding` | 04 |
| `src/ormah/engine/memory_engine.py` | remove synchronous embed block from `startup()` | 05 |
| `src/ormah/background/embedding_backfill.py` | `run_embedding_backfill(engine)` — non-ok on incomplete | 06 |
| `src/ormah/background/scheduler.py` | register job (interval + post-bind `next_run_time`) | 07 |
| `src/ormah/api/routes_admin.py` | add to `_TASK_RUNNERS`, `_TASK_DESCRIPTIONS`, `_SLEEP_CYCLE_ORDER` | 08 |
| `src/ormah/main.py` | scheduler-independent post-bind one-shot fallback | 09 |
| `src/ormah/engine/memory_engine.py` (`stats`) + integration test | observability (`embedding_gap`, `embedding_schema_version`) + E2E recovery | 10 |

## Task order & dependencies

1. **01 Config** — no deps.
2. **02 `_embed_node_rows` + vec_count verify** — no deps (pure refactor).
3. **03 Quarantine + `backfill_embeddings`** — needs 01, 02.
4. **04 `_index_embedding` retry** — needs 01.
5. **05 Remove startup embed block** — needs 03.
6. **06 Background job (non-ok on incomplete)** — needs 03.
7. **07 Scheduler registration** — needs 01, 06.
8. **08 Admin run-all / sleep-cycle** — needs 06.
9. **09 Scheduler-independent fallback** — needs 06 (main.py kicks the job off a daemon thread when the scheduler fails to start).
10. **10 Observability + E2E recovery** — needs 03, 06, 07.

## Key design points

- **C1 (poison loop) closed:** quarantine + retry budget bound the schema migration to O(N × budget) one-time, then delta forever — never an unbounded full re-embed.
- **I1 (scheduler dependency) closed:** a daemon-thread one-shot in `lifespan` runs reconciliation even if `start_scheduler` raised; the scheduler still drives the recurring cadence on the happy path.
- **I2 / I4 closed:** version advances only on verified completeness (`vec_count`), and incomplete runs surface as non-ok job health.
- **Non-blocking startup:** `startup()` no longer **embeds** nodes (it still warms the encoder via `_warmup_embedder()` — wording corrected vs the original draft). The port binds without waiting on embeddings.
- **Operator control:** `embedding_backfill_interval_minutes` (default 60) → `999999` disables in-process; the 02:00 sleep-cycle (`run-all`) drives it — like the other jobs.
- **Concurrency safety:** chunked upserts (100) + `wal_checkpoint(TRUNCATE)` release the write lock between blocks (avoids #18/#19); APScheduler `max_instances=1` prevents overlap.

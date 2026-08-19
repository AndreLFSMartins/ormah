# Reversible Promotion + Seven-Day Initial Lease (#223) — Implementation Plan Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `archival` nodes a way back to `working` on confirmed use, and give every new node a seven-day unused lease instead of a ~29-hour one.

**Architecture:** One pure function (`lifecycle.promotion_floor`) supplies the floor; the tier flip happens inside `MemoryEngine._record_confirmed_use`, which already owns the at-most-once confirmed-use claim, so promotion inherits its qualification rules for free. A new `superseded_by` field, written by the consolidator, blocks automatic promotion for exactly the nodes a consolidation replaced.

**Tech Stack:** Python 3.11+, pydantic, SQLite (sqlite-vec), pytest (`asyncio_mode = auto`), ruff.

**Spec (read first, it is the source of truth):** `docs/superpowers/specs/2026-08-17-issue-223-reversible-promotion-design.md`

---

## Global Constraints

- **Work in the island, never in `Tools/ormah`:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-223`, branch `feat/223-reversible-promotion`, cut from `upstream/main` + two dependency merges (top: `06b6447`).
- **The island is NOT `local-main`.** `archived_at`, `forgetting_manager.py` and `docs/lifecycle/` do not exist there. Never copy a line number from `local-main`; reference symbols.
- **Nothing under `docs/`, `.env.example`, `docs/lifecycle/`, `.council/` or `docs/superpowers/` may be committed on this branch.** This plan lives on `local-main` only. `docs/lifecycle/` is NOT covered by the pre-push `PROTECTED` allowlist — the hook will not stop it.
- **Every test command must prove which tree it imported** (see the gate below). A number from the wrong tree has already been retracted once in this work.
- **Never pipe pytest to `tail`** — the exit code becomes `tail`'s. Redirect and record `$?`.
- **Baseline (re-derived 2026-08-17):** `1925 passed, 12 failed`. All 12 are pre-existing and exonerated as the real `~/.config/ormah/.env` leaking into `Settings()` — they pass with a clean `HOME`. They are: 6 in `tests/test_setup.py` (byte-identical to `upstream/main`), 2 in `tests/test_config.py`, `test_background/test_consolidator.py::test_consolidation_settings_defaults`, `test_background/test_hippocampus.py::test_new_file_triggers_ingestion`, and 2 in `test_background/test_session_watcher.py`.
- **Exonerate by test NAME, never by file.** This branch appends tests to `tests/test_config.py` (Task 1) and `tests/test_background/test_consolidator.py` (Task 6), so "the branch does not touch these files" stops being true the moment you start. **A task is green when the twelve baseline *names* are still the only failures.** Watch `test_consolidation_settings_defaults` in particular: Task 1 moves a `Settings` default, which is exactly what that test reads.
- **Push is explicit:** `git push fork feat/223-reversible-promotion`. The branch has no upstream on purpose; a bare `git push` is refused. Never point it at `fork/fix/220-confirmed-use`.

### The test gate — run both halves, every time

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
#   printed path MUST contain ormah-wt-223/ — if not, STOP, the run is against local-main
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest <target> -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Six of the twelve baseline failures need a clean `HOME` to pass; to isolate, add `HOME=$(mktemp -d)`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/ormah/config.py` | `fsrs_initial_stability` default `1.0 → 5.814` | 1 |
| `src/ormah/lifecycle.py` | new pure `promotion_floor(stability, initial_stability)` | 1 |
| `src/ormah/models/node.py` | new `superseded_by: str \| None` on `MemoryNode` | 2 |
| `src/ormah/store/markdown.py` | serialize when not `None`; parse via `meta.get` | 2 |
| `src/ormah/index/schema.sql` | `superseded_by TEXT` on `nodes` | 3 |
| `src/ormah/index/db.py` | one entry in the `enrichment_migrations` pair list | 3 |
| `src/ormah/index/builder.py` | carry `superseded_by` through `INSERT OR REPLACE` | 3 |
| `src/ormah/engine/memory_engine.py` | `remember()` initial stability; promotion in `_record_confirmed_use`; `_mark_superseded`; version comment | 4, 5, 6, 7 |
| `src/ormah/background/consolidator.py` | mark provenance **before** demoting | 6 |

**`builder.py` is not in the spec's list of seven files.** It is required: `_index_file_nodes_only` runs `INSERT OR REPLACE INTO nodes` with an explicit 18-column list, and `REPLACE` is DELETE+INSERT, so any omitted column reverts to its DEFAULT. Without this change the consolidator's own `update_node(tier=archival)` — called one line after marking — re-indexes the file and wipes `superseded_by` back to `NULL`. The promotion gate itself reads Markdown and still blocks correctly, but the index column would be permanently `NULL`, which is a lie for the SQL consumer #209 is named in the spec as.

---

## Tasks

| # | Deliverable | File |
|---|---|---|
| 1 | Seven-day lease default + `promotion_floor` | `01-lease-and-floor.md` |
| 2 | `superseded_by` on the model and in Markdown | `02-superseded-field.md` |
| 3 | `superseded_by` in schema, migration and reindex | `03-index-column.md` |
| 4 | `remember()` uses the configured initial stability | `04-remember-initial-stability.md` |
| 5 | Promotion inside `_record_confirmed_use` | `05-promotion.md` |
| 6 | Consolidation provenance and its ordering fail-safe | `06-consolidation-provenance.md` |
| 7 | Version pin, docs-in-code, and the full verification gate | `07-verification.md` |

Tasks 1–3 are independent of each other. Task 4 needs Task 1. Task 5 needs Tasks 1–3. Task 6 needs Tasks 2, 3 and 5. Task 7 is last.

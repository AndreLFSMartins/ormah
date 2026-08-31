# Issue #240 — scope `L_mem` to the apply step: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task lives in its own file in this folder; give a subagent **only this overview plus its task file**.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-240-serialized-job-lock-scope-design.md` (read §2, §3 and §5 before Task 1).

**Goal:** Background jobs stop holding `L_mem` for a whole run; they hold it only around each apply step, guarded by a restore epoch that aborts the run if a full graph restore lands mid-run.

**Architecture:** `MemoryEngine` gains a monotonic `_restore_epoch`, bumped inside `reload_restored_graph` (already exclusive under `L_mem`), and a `memory_operation_at(epoch)` context manager that takes `L_mem` and raises `RestoredUnderfoot` if the epoch moved. `background/memory_lock.py` loses `serialized_memory_job` and gains `RestoredUnderfoot` plus `restore_aware_job`, a decorator that reads the epoch on entry, passes it to the job as its second positional argument, and swallows `RestoredUnderfoot` so the run ends cleanly instead of raising into APScheduler. Each of the seven jobs wraps its own apply steps.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), `threading.RLock`, SQLite via `ormah.index.db.Database`.

## Global Constraints

- **Island:** work happens in `/Users/andre/Documents/GitHub/Tools/ormah-wt-240` on branch `fix/240-serialized-job-lock-scope`, cut from `upstream/main`. Never `cd` elsewhere.
- **Planning artifacts (this file, the spec) live on `local-main` in the main checkout, never on the island.** The `pre-push` hook is fail-closed and `^docs/superpowers/` is in its `PROTECTED` allowlist — committing them on the island makes `git push fork` reject.
- **Acquisition order is always `L_mem → L_db`.** No apply step may take `L_mem` inside an open `db.transaction()`; that inversion is what #207 fixed. Task 10 adds the net that keeps it closed.
- **Abort, do not skip.** On epoch change the whole snapshot is stale: let `RestoredUnderfoot` propagate out of the job body. Never catch it per-item.
- **`index_updater` / the `FileStore` scan is out of scope** (spec §4). Do not touch `src/ormah/index/builder.py`.
- **No new `try/except Exception` around an apply step that would swallow `RestoredUnderfoot`.** Several jobs already wrap their whole body in `except Exception` — Task 1 makes `RestoredUnderfoot` survive that by having `restore_aware_job` handle it *outside*, so each job must re-raise it from any inner handler it passes through. Every task that touches such a job says exactly where.
- **Verification gates (all three load-bearing — without them the number is not ours):**
  ```bash
  env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
  #   printed path MUST contain ormah-wt-240/
  env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
  echo "PYTEST_EXIT=$?" >> out.txt
  ```
  Every task's "run the tests" step means the middle command, narrowed to the task's test file. The full suite runs in Task 10.
- **`make server` is forbidden** — the dev server is launchd-managed.
- Lint: `ruff check src/ tests/`, `line-length = 100`, `target-version = py311`.

## Task order

| # | File | Deliverable |
|---|---|---|
| 1 | `01-engine-epoch.md` | `RestoredUnderfoot`, `restore_aware_job`, `restore_epoch`, `memory_operation_at`, epoch bump |
| 2 | `02-lock-probe.md` | `tests/test_background/lock_probe.py` — depth-0 acquisition counter |
| 3 | `03-decay-manager.md` | `run_decay` per-node apply + tier revalidation (#257's canary) |
| 4 | `04-importance-and-cluster.md` | `run_importance_scoring`, `run_auto_cluster` |
| 5 | `05-auto-linker.md` | `run_auto_linker` + the foreground-progress test |
| 6 | `06-conflict-detector.md` | `run_conflict_detection` |
| 7 | `07-duplicate-merger.md` | `run_duplicate_detection` |
| 8 | `08-consolidator.md` | `run_consolidation` |
| 9 | `09-ingest-split.md` | `ingest_conversation` extract/apply split + dedup revalidation |
| 10 | `10-retire-and-net.md` | Delete `serialized_memory_job`, lock-order net, restore-abort integration test, full suite |
| 11 | `11-pay-remaining-revalidation-debts.md` | Revalidate snapshotted state in consolidator, auto_cluster, duplicate_merger |

Tasks 3–8 are independent of each other once Tasks 1 and 2 land. Task 9 is independent of 3–8. Task 10 deletes the decorator, so every job must already be converted before it runs.

Task 11 was added after the final whole-branch review, which found that the revalidation debt spec §5 named for decay (and Task 3 paid) exists unpaid in three other jobs. André's decision was to pay all three rather than document them as accepted windows.

## What must not get lost when the PR is opened

Both come from the spec and belong in the **PR body**, not only here:

1. **This PR does not fix the default install.** The `index_updater` scan (~495 ms every 60 s, 34,5 s cold, no LLM involved) is deliberately out of scope. **#240 stays partially open** on that point.
2. **Findings 2 and 3 need their own issues** — task pause does not survive restart (missing APScheduler jobstore); `SIGTERM` ignored while holding `L_mem` (no cooperative cancellation). Neither is opened yet.

Commenting on **#257** or **#240** about the interaction with `test_recall_concurrency` requires **André's explicit confirmation before posting** (spec §6).

# index_updater Lock-Order Inversion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each task lives in its own file; give an implementer only this overview plus their task file.

**Goal:** Remove the `L_db -> L_mem` lock-order inversion in `IndexBuilder.incremental_update` that deadlocks the server against every background memory job within ~2 minutes of each start.

**Architecture:** Hoist the two `FileStore` calls (`list_paths`, `file_hash`) above the write transaction so no `L_mem` request is ever made while holding `L_db`. This mirrors `full_rebuild`, which already hoists `list_paths`. No new lock is retained.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), `threading.RLock`, SQLite via `sqlite3`.

**Spec:** `docs/superpowers/specs/2026-08-10-index-updater-lock-order-design.md`

## The defect in one picture

```text
auto_linker    : L_mem (acquired) -> waits for L_db   [auto_linker.py:312]
index_updater  : L_db  (acquired) -> waits for L_mem  [builder.py:119]
```

`L_mem` is `MemoryEngine._memory_operation_lock`, a `threading.RLock` with no timeout. The engine
hands the *same object* to `FileStore` (`FileStore(nodes_dir, self._memory_operation_lock)`), so any
decorated `FileStore` call made inside a write transaction requests `L_mem` while holding `L_db`.

`index_updater` runs every 60 s, which is why the deadlock returns ~2 minutes after each restart.

## Global Constraints

Every task's requirements implicitly include this section.

- Work happens in a **worktree cut from `upstream/main`**, never a `git checkout` inside
  `Tools/ormah` — that tree is what the running Beta serves (FORK-WORKFLOW.md Golden rule 1):

  ```bash
  git fetch upstream
  git worktree add -b fix/index-updater-lock-order ../ormah-wt-index-lock upstream/main
  cd ../ormah-wt-index-lock
  ```

- Push branches to `fork`, never to `upstream` (Golden rule 3).
- ruff: `target-version = py311`, `line-length = 100`.
- Default pytest run excludes `integration`-marked tests (`addopts = -m 'not integration'`).
- Known-good baseline: **7 pre-existing failures** (`test_cloud_settings` 1, `test_setup` 6).
  The fix must add zero new failures.
- `incremental_update`'s behaviour must not change: same `(added, updated)` return, same tolerance
  for a file that disappears or fails to hash mid-run.

## Tasks

| # | File | Deliverable |
|---|---|---|
| 1 | `01-red-test.md` | A test that hangs on the deadlock today |
| 2 | `02-fix.md` | The hoist, turning the test green |
| 3 | `03-verify.md` | Full suite + ruff against the baseline |
| 4 | `04-ship.md` | Branch on `fork`, Beta running the fix, verified live |

Run them in order. Task 1's red run is a gate: if it fails fast instead of hanging, the test proves
nothing and Task 2 must not start.

## Standing warnings

- **Do not add `@serialized_memory_job` to `index_updater`.** It looks like the consistent move and
  is what f7ac305 did for a different caller, but here it converts a deadlock into sustained write
  starvation: the job would hold `L_mem` across the whole 36k-file loop, every 60 s. Reasoned in the spec.
- The defect is present unchanged in `upstream/main` at 0.14.8 — an upstream bug, not a Beta regression.
- Out of scope: the ~1 s whisper latency (the parse loop still runs inside the txn), the two coexisting
  installs, and a systematic re-audit of every transaction-opening class.

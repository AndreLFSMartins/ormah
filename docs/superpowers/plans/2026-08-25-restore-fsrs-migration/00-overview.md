# Restore Re-evaluates the FSRS Migration (#236) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A restore (or any full index rebuild) onto an existing `index.db` re-evaluates the FSRS migration, so pre-FSRS nodes are seeded and already-migrated nodes are left alone.

**Architecture:** Treat the lifecycle meta keys (`fsrs_migrated`, `lifecycle_model_version`) as derived state that `IndexBuilder.full_rebuild` invalidates, exactly like `auto_link_watermark`. `MemoryEngine.rebuild_index` becomes a serialized memory operation and calls `_migrate_fsrs()` after re-embedding. The seed itself becomes per-node eligible — it touches only nodes with `last_review IS NULL AND stability = 1.0 AND access_count > 0` — so it can never overwrite a value another writer produced, and a mixed store seeds its pre-FSRS nodes while leaving migrated ones alone. No new state, no manifest changes.

**Tech Stack:** Python 3, SQLite, pytest. Run tests with `python -m pytest` from the repo root.

## Global Constraints

- Branch: `fix/236-restore-fsrs-migration`. Worktree: `/Users/andre/Documents/GitHub/Tools/ormah-wt-236`.
- Spec: `docs/superpowers/specs/2026-08-25-restore-fsrs-migration-design.md`.
- Code, comments, commit messages in English. No `--no-verify`. Commit by exact file paths.
- Every test in this plan must be run and seen FAILING before the implementation step that makes it pass.
- Out of scope: backup manifest changes, `_lifecycle_model_version` heuristics, the incremental-update race with a concurrent rebuild.

---

## Self-review

- Spec coverage: Design 1 → Task 1; Design 2 → Task 2; Design 3 (docstring) → Task 2 Step 3; Design 4 (CLI path) → Task 3; Design 5 (scope note) → Task 2 Step 3. Tests section: all four listed tests map to Tasks 1-3.
- Placeholders: none. The PR body's `<paste summary line>` is filled from Task 4 Step 1 output.
- Type consistency: `_make_node`, `_version`, `_stability` are the helpers already defined at the top of `test_lifecycle_model_version.py`; `_service` and `MemoryNode` imports already exist in `test_backup.py`.

## Tasks

1. [01-task.md](01-task.md) — `full_rebuild` clears the lifecycle keys
2. [02-task.md](02-task.md) — Per-node seed eligibility + completeness guard (council rounds 1-3)
3. [03-task.md](03-task.md) — `rebuild_index` re-runs the FSRS migration
4. [04-task.md](04-task.md) — End-to-end restore through `BackupService`
5. [05-task.md](05-task.md) — Full suite and PR

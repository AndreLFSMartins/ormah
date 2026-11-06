# The FSRS Migration Re-evaluates On Every Start — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The per-node FSRS seed runs on every `_migrate_fsrs()` call instead of being short-circuited by the store-wide version marker, and the completeness guard that gates the marker compares graph membership instead of cardinality.

**Architecture:** Two edits to `MemoryEngine`, both in `src/ormah/engine/memory_engine.py`. The early return in `_migrate_fsrs` moves below the seed call, so it gates only the marker write. `_graph_is_fully_indexed` stops comparing `len(list_paths())` to `COUNT(*)` and instead compares the set of `node.id` parsed from disk against the set of `id` in the `nodes` table, returning `False` the moment any file fails to parse. No new state, no schema change, no new dependency.

**Tech Stack:** Python 3.11+, SQLite, pytest. Run tests from the repo root.

## Global Constraints

- Branch: `fix/236-restore-fsrs-migration`. Worktree: `/Users/andre/Documents/GitHub/Tools/ormah-wt-236` — a git worktree; do NOT `cd` to the main checkout.
- Spec: `docs/superpowers/specs/2026-08-26-migration-runs-on-every-start-design.md`.
- Code, comments and commit messages in English. No `--no-verify`. Commit by exact file paths.
- **The suite does not collect under the developer's normal environment.** `~/.config/ormah/.env` sets `ORMAH_LLM_PROVIDER=claude_cli`, which this branch's `Settings` validator rejects, so `tests/conftest.py` raises at import. Prefix every pytest invocation with an isolated HOME — the tasks spell the full command out:
  `env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome python -m pytest ...`
  NEVER edit `~/.config/ormah/.env` — a launchd daemon loads it at boot.
- Every test in this plan must be run and seen FAILING before the implementation step that makes it pass. If a test passes when the plan predicts red, STOP and report it rather than pushing on.
- These pre-existing tests must stay green and must not be edited: `test_a_legacy_store_is_backfilled_without_reseeding`, `test_a_rebuilt_index_does_not_reseed_earned_stability`, `test_a_restore_onto_an_existing_index_keeps_earned_stability`, `test_no_version_is_recorded_while_a_file_is_missing_from_the_index`. They are what proves "always seed" is not destructive; a red there means the design is wrong, not the test.
- Do not use bare `git stash` / `git stash pop` — the stash stack is shared across worktrees.
- Out of scope: `src/ormah/index/builder.py`, `src/ormah/background/scheduler.py`, `_lifecycle_model_version()`'s heuristics, backup manifest changes, and the memory lock held across the embedding pass (filed as r-spade/ormah#264).

## File Structure

- `src/ormah/engine/memory_engine.py` — both behavior changes, plus one new import.
- `tests/test_engine/test_lifecycle_model_version.py` — two new tests appended.

No other file is created or modified.

## A test the spec listed that this plan drops

The spec's testing section named a third new test: a row in `nodes` with no file on disk. It is not in this plan because it cannot go red. Deleting a file without adding one also unbalances the counts, so the pre-change cardinality check already reports incomplete — the test would pass both before and after, discriminating nothing. That direction is still covered: set inequality catches `indexed - disk` as well as `disk - indexed`.

## Self-review

- **Spec coverage:** Design 1 (seed always runs) → Task 1. Design 2 (membership guard, fail-closed on parse failure) → Task 2. Spec testing item 1 → Task 1 Step 1. Spec testing item 2 → Task 2 Step 1. Spec testing item 3 → dropped, reason above. Spec testing item 4 → the existing `test_no_version_is_recorded_while_a_file_is_missing_from_the_index`, asserted in Task 2 Step 4. The three "must stay green" tests are named above and re-asserted in Task 1 Step 4.
- **Placeholders:** none. Every code step carries the code.
- **Type consistency:** `_graph_is_fully_indexed() -> bool` unchanged in signature. `parse_node(text) -> MemoryNode` and `.id` match the existing usage in `src/ormah/index/builder.py`. `_make_node`, `_version`, `_stability`, `_unmigrated_meta` are helpers already defined at the top of the test file.
- **Ordering:** Task 1 must land before Task 2. Task 2's test needs the seed to have run before the guard is consulted, and its predicted red output assumes Task 1's restructured control flow.

## Tasks

1. [01-task.md](01-task.md) — The seed runs on every call
2. [02-task.md](02-task.md) — The completeness guard compares membership

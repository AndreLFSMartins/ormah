# Consolidated Nodes Are Terminal (#261) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_find_consolidation_clusters` never uses a `consolidated`-tagged node as a cluster seed or member, so a summary is never summarised again.

**Architecture:** One SQL predicate (`NOT EXISTS` on `node_tags`) held in a module constant and applied to both discovery queries in `src/ormah/background/consolidator.py`. Two red-first tests in `tests/test_background/test_consolidator.py` using the real fastembed encoder — identical content gives similarity 1.0, which makes clustering deterministic.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode = auto`), SQLite via `engine.db.conn`, fastembed.

**Spec:** `docs/superpowers/specs/2026-08-25-issue-261-consolidated-nodes-terminal-design.md`

## Global Constraints

- Branch is a clean island from `upstream/main`: `fix/261-consolidated-nodes-are-terminal`, worktree `../ormah-wt-261` (`FORK-WORKFLOW.md` Recipe A). Never edit `Tools/ormah` (it serves the live Beta).
- Every test command runs with `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest …` and the import gate is proven first (Task 1). Never pipe pytest into `tail`.
- Only `_find_consolidation_clusters` and its docstring change in `consolidator.py`. `_apply_consolidation`, the prompt, `run_consolidation`, `_consolidate_cluster` stay byte-identical (PR #260 edits those).
- No schema change, no migration, no new setting.
- ruff: `line-length = 100`.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Tasks

- [Task 1: Clean island + import gate](01-island-and-import-gate.md)
- [Task 2: Red tests — discovery re-clusters consolidated nodes](02-red-tests.md)
- [Task 3: Fix — exclude consolidated nodes from both discovery queries](03-fix-discovery-queries.md)
- [Task 4: Island gate + push](04-island-gate-and-push.md)

Each task is executed on its own with only its file + this overview as context.

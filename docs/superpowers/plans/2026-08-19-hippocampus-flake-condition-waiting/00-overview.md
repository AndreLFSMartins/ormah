# test_hippocampus Condition-Based Waiting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the fixed wall-clock budgets from `tests/test_background/test_hippocampus.py` so a loaded CI runner stops reddening unrelated PRs.

**Architecture:** Add one private polling helper to the test file and route the two waits that block on asynchronous work through it. No production code changes. The work lands as a clean island cut from `upstream/main` and ships as an upstream PR.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), watchdog, ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-08-19-hippocampus-flake-condition-waiting-design.md`

## Global Constraints

- Only `tests/test_background/test_hippocampus.py` may be modified. Nothing under `src/`.
- `time.monotonic()`, never `time.time()`, for deadlines.
- Helper default timeout `10.0`, poll interval `0.01`.
- The helper returns the last predicate value; it never raises. The original assertion stays the one that fails.
- `time.sleep(0.05)` inside the debounce test's write loop is deliberate and stays.
- Commit trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Every pytest number must come from a run made through the import gate in Task 1, Step 4 (`env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python`), or it does not count.

## File Structure

| Path | Responsibility |
|---|---|
| `tests/test_background/test_hippocampus.py` | The only file modified. Gains `_wait_until` and two converted waits. |

## Tasks

1. [`01-clean-island.md`](01-clean-island.md) — Task 1: Build the clean island
2. [`02-wait-helper-and-ingestion.md`](02-wait-helper-and-ingestion.md) — Task 2: `_wait_until` and the ingestion wait (line 83)
3. [`03-debounce-wait.md`](03-debounce-wait.md) — Task 3: The debounce wait (line 169)
4. [`04-verify-and-ship.md`](04-verify-and-ship.md) — Task 4: Verify against the baseline and ship

Each task file is self-contained. A worker gets this overview plus exactly one task file.

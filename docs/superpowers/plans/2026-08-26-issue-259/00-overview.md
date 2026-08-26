# Issue #259 — Maintenance consolidation reads full content: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Claude-in-the-loop maintenance path from writing consolidation summaries out of a 400-character view of each source, and give the agent the sources' `type`.

**Architecture:** `get_maintenance_batches` normalizes all four candidate batches through one `_norm` helper that truncates to 400 chars. Give `_norm` an explicit `content_limit` parameter defaulting to 400 (screening batches unchanged) and pass `None` for the consolidation batch only. Separately, add `type` to the two SELECTs in `_find_consolidation_clusters`, which is the only finder that omits it.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), ruff (line-length 100), fastembed + sqlite-vec for the real embeddings the cluster fixtures need.

## Global Constraints

- **Working directory:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-259` — the clean island. Never work in `Tools/ormah` (it serves the running Beta).
- **Branch:** `fix/259-maintenance-full-content`, cut from `upstream/main` @ `90c431e`.
- **Every python/pytest invocation** must strip the leaked environment, or the island imports `local-main`'s code and the numbers are worthless:
  `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python ...`
- **Never pipe pytest to `tail`** — the exit code becomes tail's. Redirect to a file and append `PYTEST_EXIT=$?`.
- **No documentation files in this branch.** `docs/superpowers/` is in the pre-push `PROTECTED` allowlist and would block the push. The spec and this plan live on `local-main`.
- **No settings changes.** `consolidation_max_cluster_nodes`, `claude_maintenance_batch_size` and every other default stay as they are.
- Spec: `docs/superpowers/specs/2026-08-26-issue-259-maintenance-full-content-design.md` (on `local-main`).

## Tasks

| # | File | Deliverable |
|---|------|-------------|
| 1 | [01-full-content.md](01-full-content.md) | The consolidation batch stops truncating source content at 400 chars. |
| 2 | [02-node-type.md](02-node-type.md) | Cluster candidates carry `type`, so the agent no longer picks the consolidated node's type blind. |
| 3 | [03-verification.md](03-verification.md) | Full suite, lint, island-clean gate, #260 collision check, push to `fork`. |

Each task file is self-contained: an executor needs only this overview plus its own task file.
Tasks are ordered — Task 2's tests assert on the `_norm` behaviour Task 1 establishes.

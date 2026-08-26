# Issue #259 — Maintenance consolidation reads full content: Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Claude-in-the-loop maintenance path from writing consolidation summaries out of a truncated view of each source, at **both** cut points, while keeping the phase-1 payload bounded by splitting oversized clusters instead of slicing or skipping them.

**Architecture:** There are two truncations between the store and the agent: `_norm` (400 chars, `memory_engine.py`) and `_format_maintenance_batches` (200 chars for clusters, `mcp_adapter.py`). Both must go for the consolidation batch and both must stay for screening. To keep the payload bounded once uncapped, `get_maintenance_batches` bin-packs each cluster into sub-clusters within `claude_maintenance_cluster_max_chars` before normalizing — so the split is decided in one place and the formatter needs to know nothing about budgets.

**Tech Stack:** Python 3.11+, pydantic-settings, pytest (`asyncio_mode = auto`), ruff (line-length 100), fastembed + sqlite-vec for the cluster fixtures.

## Global Constraints

- **Working directory:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-259` — the clean island. Never work in `Tools/ormah` (it serves the running Beta).
- **Branch:** `fix/259-maintenance-full-content`, cut from `upstream/main` @ `90c431e`.
- **Every python/pytest invocation** must strip the leaked environment, or the island imports `local-main`'s code and the numbers are worthless:
  `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python ...`
- **Never pipe pytest to `tail`** — the exit code becomes tail's. Redirect to a file and append `PYTEST_EXIT=$?`.
- **No documentation files in this branch.** `docs/superpowers/` is in the pre-push `PROTECTED` allowlist and would block the push. The spec and this plan live on `local-main`.
- **Apply SQL edits to the queries as they stand in the island**, never by pasting the plan's version wholesale — #261 (PR #263, open) touches the same SELECT lines with a `_NOT_CONSOLIDATED` filter.
- **One new setting only:** `claude_maintenance_cluster_max_chars`. Every other default stays as it is.
- Spec: `docs/superpowers/specs/2026-08-26-issue-259-maintenance-full-content-design.md` (on `local-main`).

## Task order matters

Task 1 lands the budget helper **before** Task 2 uncaps anything, so no commit in this branch
ever produces an unbounded phase-1 payload.

| # | File | Deliverable |
|---|------|-------------|
| 1 | [01-split-helper.md](01-split-helper.md) | `claude_maintenance_cluster_max_chars` + `_split_cluster_to_budget`, tested in isolation. No behaviour change yet. |
| 2 | [02-uncap-norm.md](02-uncap-norm.md) | `_norm` uncapped for consolidation, split applied, screening guard rebuilt so it actually guards. |
| 3 | [03-formatter.md](03-formatter.md) | The MCP formatter stops cutting cluster content at 200 — the cut the agent actually reads. |
| 4 | [04-node-type.md](04-node-type.md) | Cluster candidates carry `type`. |
| 5 | [05-verification.md](05-verification.md) | Full suite, lint, island-clean gate, collision checks (#260 and #261), push to `fork`. |

Each task file is self-contained: an executor needs only this overview plus its own task file.

## Why v2

`/council` (2026-08-26, run `82c0d868-82a0a0a5-78c861c9`) rejected v1: Cursor and Codex both
returned `needs-attention`, seven findings, none rejected. Two of v1's load-bearing premises were
falsified — that `_norm` was the single cut point, and that an uncapped batch could not lose data.
Task 3 exists because of the first; Task 1 because of the second; the rebuilt guard in Task 2
because both peers showed v1's version could never fail.

# Issue #259 — Maintenance consolidation reads full content: Implementation Plan (v3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Claude-in-the-loop maintenance path from writing consolidation summaries out of a truncated view of each source, at **both** cut points, while keeping the phase-1 payload bounded by splitting oversized clusters instead of slicing or skipping them.

**Architecture:** There are two truncations between the store and the agent: `_norm` (400 chars, `memory_engine.py`) and `_format_maintenance_batches` (200 chars for clusters, `mcp_adapter.py`). Both must go for the consolidation batch and both must stay for screening. To keep the payload bounded once uncapped, `get_maintenance_batches` normalizes each cluster and then trims it to the longest prefix that fits `claude_maintenance_cluster_max_chars` measured on the serialized node — one decision point, and the formatter needs to know nothing about budgets.

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
| 1 | [01-split-helper.md](01-split-helper.md) | `claude_maintenance_cluster_max_chars` + `_select_cluster_within_budget`, tested in isolation. No behaviour change yet. |
| 2 | [02-uncap-norm.md](02-uncap-norm.md) | `_norm` uncapped for consolidation, trim applied, both guards proven by mutation. |
| 3 | [03-formatter.md](03-formatter.md) | The MCP formatter stops cutting cluster content at 200 — the cut the agent actually reads. |
| 4 | [04-node-type.md](04-node-type.md) | Cluster candidates carry `type`. |
| 5 | [05-verification.md](05-verification.md) | Full suite, lint, island-clean gate, collision checks (#260 and #261), push to `fork`. |

Each task file is self-contained: an executor needs only this overview plus its own task file.

## Why v3

Two `/council` runs rejected the two earlier drafts. Cursor and Codex returned
`needs-attention` both times; neither ever approved.

- **v1** (run `82c0d868-82a0a0a5-78c861c9`, 7 findings): `_norm` was not the single cut point —
  the MCP formatter cuts at 200 — and an uncapped batch *can* lose data if the host truncates the
  tool result. Task 3 exists because of the first; Task 1 because of the second.
- **v2** (run `5bf5592c-8c32273c-050cf979`, 4 findings, all HIGH): the greedy next-fit packing
  discarded nodes that would have paired, and dropped the seed silently. Confirmed by executing
  the specified helper: `[500,500,400,400]` at budget 900 lost 2 of 4 nodes. Task 1 now selects a
  prefix instead. The v2 bound also measured raw content, ignoring metadata and JSON escaping —
  3000 NUL characters serialize to 18_070 — so the budget now measures `json.dumps(node)`.

**Review-setup caveat:** the peers review the working tree of `Tools/ormah`, which is on
`local-main` (~693 commits ahead), while this plan targets `upstream/main`. In the v2 run a peer
recommended reusing `_split_cluster_to_fit` "already in this tree"; it exists on `local-main` and
on the #192 branch, but **not** on `upstream/main`. Behavioural findings from peers hold — every
file or symbol reference must be re-checked against the island before acting on it.

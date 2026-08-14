# Separate Surfaced Results from Confirmed Memory Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Ormah from treating a memory's appearance in a search result as evidence it was used, and give confirmed use exactly three named callers.

**Architecture:** The boundary is the entry point, not a flag. Search paths lose their lifecycle writes entirely — deleted, not guarded — and `_touch_access` is renamed `_record_confirmed_use` with a byte-identical body, now serialized by `@_serialized_memory_operation`. Confirmed use is gated by one shared at-most-once claim on a new `confirmed_use_claims` table, taken inside the caller's transaction. Two tasks along a subtraction/addition seam. Regression is prevented by contract tests that read all four lifecycle fields from both the markdown file and the SQLite row.

**Reviewed by the Dev Council twice on 2026-08-14** (Cursor + Codex, two rounds each). The first review accepted five findings and rejected one. The second review **refuted the central fix of the first**: the event-transition gate read from `affinity` cannot work, because `affinity` is mutable. Task 1 passed both reviews untouched; Task 2 was rewritten around the claim table. Six findings accepted, two rejected. Both results are at `$COUNCIL_HOME/council-result.md` (the second overwrote the first; the raw peer outputs of both runs are under `$COUNCIL_HOME/runs/`).

**Tech Stack:** Python ≥3.11, pytest (`asyncio_mode = auto`), SQLite + sqlite-vec, FastAPI, ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-08-14-issue-220-confirmed-use-design.md` (commit `2522172`)
**Issue:** [#220](https://github.com/r-spade/ormah/issues/220)

## Global Constraints

- **Every line number in this plan was read from `upstream/main` (`a28837b`).** `local-main` is 623 commits ahead and its addresses do **not** apply. This is what broke the previous attempt. Line numbers shift as you edit — locate code by the quoted snippet, never by the number alone.
- **Fork workflow is non-negotiable** (`FORK-WORKFLOW.md`): the branch is cut from `upstream/main`; work happens in the worktree at `../ormah-wt-220`, **never** via `git checkout` inside `Tools/ormah` (that directory is what the running Beta serves via launchd `com.ormah.server.dev`); push to `fork`, never `upstream`; do not rename remotes.
- **The stability formula does not change.** `_record_confirmed_use` keeps `stability * fsrs_stability_growth * (retrievability ** -0.2)` byte-identical. Bounding, cooldown and saturation are #221.
- **No new error handling *inside* `_record_confirmed_use`**, including the silent return when the node is missing. Its *callers* isolate it — that is a different thing, and Task 2's watcher loop does exactly that.
- **`_record_confirmed_use` is serialized** with `@_serialized_memory_operation` (council finding). Its load/modify/save/DB-update sequence was never atomic; the decorator is the whole fix and the body still does not change.
- **Confirmed-use source allowlist is fail-closed:** exactly `{"explicit", "implicit", "auto_llm_judge"}` with `signal == 1`. `auto_heuristic` is excluded pending #218. Every other source, and every negative signal, does not confirm.
- **Reinforcement fires on an at-most-once claim, never on a request and never on derived state** (second council round). One whisper event reinforces at most once, no matter how many times a request is replayed, how many sources report positively on it, or which caller gets there first. The gate is a claim row on the new `confirmed_use_claims` table, taken with `INSERT ... ON CONFLICT DO NOTHING` **inside the caller's transaction**; only the caller that inserts reinforces. Both `submit_feedback` and the watcher use the same claim — see Task 2, Steps 4, 5 and 9.
- **Do not derive confirmation from `affinity` or `signals`.** Both were tried and both fail, in opposite directions. `affinity` is mutable (unique `(node_id, whisper_log_id)`, and explicit feedback `UPDATE`s that single row), so a `+1/-1/+1` cycle confirms twice and a pre-existing `auto_heuristic` row swallows a later qualified positive. The `signals` unique key omits `polarity` and its rows are never updated, so an explicit `-1` followed by `+1` never confirms at all. The claim table consults neither.
- **The delivery contract is at-most-once, not exactly-once.** `_record_confirmed_use` writes markdown before updating SQLite, and that write cannot join the transaction or be rolled back — so no ordering of claim and mutator yields exactly-once. A crash or exception after `COMMIT` loses that event's reinforcement permanently. This is a decision, not a gap: `#220` exists to stop Ormah manufacturing retention, so reinforcing twice is worse than missing once. A durable pending/applied protocol with a reconciliation loop was rejected in both council rounds. Misses are logged; **the claim is never deleted on failure**, because the mutator saves the markdown before the DB update and a delete-and-retry would increment the file twice.
- **The reinforcement runs outside the transaction**, on IDs collected inside it. `IndexDB.transaction()` holds a process-level lock for the whole block; `_record_confirmed_use` does disk I/O. With the decorator above, calling it inside an open transaction would also invert the `memory_lock → db_lock` order — so this constraint is now a correctness rule, not a performance preference.
- **Lifecycle fields** — the four that must be asserted on both sides: `access_count`, `last_accessed`, `last_review`, `stability`.
- **Do not open the PR** while draft PR [#229](https://github.com/r-spade/ormah/pull/229) still declares `Closes #220–#223`. Implementing and committing are free; only `gh pr create` is blocked.
- Lint gate: `make lint` (`ruff check src/ tests/`) must pass before each commit.
- **Do not touch** `FileStore.touch_access` (`src/ormah/store/file_store.py:145`) — a namesake with no production callers and two tests of its own. Name it in the PR body so a reviewer does not read it as an oversight.

## Setup — run once, before Task 1

This is shared input to both tasks, not a task of its own: it produces no deliverable and its output is a yardstick both tasks compare against.

- [ ] **Cut the worktree from `upstream/main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/220-confirmed-use ../ormah-wt-220 upstream/main
```

Expected: `Preparing worktree (new branch 'fix/220-confirmed-use')`.

- [ ] **Verify the base carries nothing local**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git rev-parse --abbrev-ref HEAD && git log --oneline upstream/main..HEAD | wc -l )
```

Expected: `fix/220-confirmed-use` then `0`. Any other count means the branch was cut from the wrong base — delete it and redo.

- [ ] **Install into the worktree**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && pip install -e ".[dev]" )
```

- [ ] **Record the red baseline**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort ) \
  > /private/tmp/claude-501/220-baseline-ids.txt
wc -l /private/tmp/claude-501/220-baseline-ids.txt
cat /private/tmp/claude-501/220-baseline-ids.txt
```

This file is the yardstick: **"tests pass" means no test ID outside this list fails.** It is evidence, not a deliverable — it lives outside the repo and is never committed.

PR #229 claims a pre-existing `A LIMIT or k = ? constraint is required on vec0 knn queries` failure in auto-link, conflict and worker-thread vector search. That is a claim from a PR description, not a measurement. Report what you actually measured. If the suite is green, say so — that contradicts #229 and is worth knowing.

## Task Order

| Task | File | Deliverable |
|---|---|---|
| 1 | `01-stop-surfacing-writes.md` | No search path writes lifecycle fields; the `touch_access` parameter is gone; `_touch_access` is renamed |
| 2 | `02-confirmed-use-callers.md` | The `confirmed_use_claims` latch; qualified positive feedback and the `auto_llm_judge` path record confirmed use through it |

Task 2 consumes exactly one thing from Task 1 — the name `_record_confirmed_use` — and nothing else. There is no other interface between them.

## Out of scope

The reinforcement formula (#221) · importance blocking decay (#222) · archival promotion (#223) · `auto_heuristic` admission (#218) · UI search retrieval logging (#231) · `FileStore.touch_access` · any change to the stability formula.

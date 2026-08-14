# Separate Surfaced Results from Confirmed Memory Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Ormah from treating a memory's appearance in a search result as evidence it was used, and make confirmed use a single named operation with exactly three callers.

**Architecture:** The boundary is the *entry point*, not a flag. Search paths lose their lifecycle writes entirely (delete, don't guard); `_touch_access` is renamed `_record_confirmed_use` with a byte-identical body and becomes reachable only from `recall_node`, qualified positive feedback, and the session watcher's `auto_llm_judge` positive path. Regression is prevented by contract tests on six non-mutation surfaces, not by a type.

**Tech Stack:** Python ≥3.11, pytest (`asyncio_mode = auto`), SQLite + sqlite-vec, FastAPI, ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-08-14-issue-220-confirmed-use-design.md`
**Issue:** [#220](https://github.com/r-spade/ormah/issues/220)

## Global Constraints

- **Fork workflow is non-negotiable** (`FORK-WORKFLOW.md`): the branch is cut from `upstream/main`, never from `local-main`; work happens in a **worktree**, never via `git checkout` inside `Tools/ormah` (that directory is what the running Beta serves via launchd `com.ormah.server.dev`); push to `fork`, never `upstream`; do not rename remotes.
- **The stability formula does not change in this plan.** `_record_confirmed_use` keeps `stability * fsrs_stability_growth * (retrievability ** -0.2)` byte-identical. Bounding and cooldown are #221.
- **No new error handling** in `_record_confirmed_use`. The body is unchanged, including the early return when the node is missing.
- **Confirmed-use source allowlist is fail-closed:** exactly `{"explicit", "implicit", "auto_llm_judge"}` with `signal == 1`. `auto_heuristic` is excluded pending #218. Any other source, and every negative signal, does not confirm.
- **Do not open the PR** until draft PR [#229](https://github.com/r-spade/ormah/pull/229) is closed or its `Closes #220–#223` lines are dropped. Implementation and commits are fine; only the PR is blocked.
- Lint gate: `make lint` (`ruff check src/ tests/`) must pass before each commit.

## Task Order

| Task | File | Deliverable |
|---|---|---|
| 1 | `01-baseline-and-worktree.md` | Worktree on `upstream/main` + recorded red baseline |
| 2 | `02-stop-surfacing-writes.md` | Search paths write no lifecycle fields; `touch_access` param gone |
| 3 | `03-rename-confirmed-use.md` | `_touch_access` → `_record_confirmed_use`; `recall_node` precision proven |
| 4 | `04-feedback-confirmed-use.md` | Qualified positive feedback records confirmed use |
| 5 | `05-session-watcher-confirmed-use.md` | `auto_llm_judge` positive records confirmed use |
| 6 | `06-docs.md` | Three upstream docs corrected |

Tasks 4 and 5 both consume `_record_confirmed_use` and therefore depend on Task 3. Task 2 must land before Task 3, because Task 3's rename would otherwise have to touch the four call sites Task 2 deletes.

## Interfaces produced

- `MemoryEngine._record_confirmed_use(self, node_id: str) -> None` — the single lifecycle mutator. Loads the node from `file_store`, updates `stability`, `last_review`, `last_accessed`, `access_count`, saves the markdown, then stamps the SQLite row. Returns `None`. Silently returns when the node does not exist.
- `MemoryEngine.recall_search_structured(self, query, limit=10, default_space=None, min_relevance=None, auto_temporal=True, spread_activation=True, query_vec=None, **filters) -> list[dict]` — note the removed `touch_access` parameter.

## Known-red baseline

PR #229 reported pre-existing failures on clean `upstream/main`: `A LIMIT or k = ? constraint is required on vec0 knn queries` in auto-link, conflict and worker-thread vector search, plus a setup binary-detection assumption. **This is a claim from that PR's description, not a measurement.** Task 1 measures it. No task in this plan may claim a suite is green without diffing against that recorded baseline.

## Out of scope, deliberately

The reinforcement formula (#221) · importance blocking decay (#222) · archival promotion (#223) · `auto_heuristic` admission (#218) · UI search retrieval logging (#231).

`FileStore.touch_access` (`src/ormah/store/file_store.py:202`) is dead code — zero production callers, two tests. It shares a name with the engine helper and is **not** touched by this plan. Mention it in the PR body so a reviewer does not mistake it for an oversight.

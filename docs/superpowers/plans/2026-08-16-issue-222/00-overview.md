# Issue #222 — importance no longer gates working-tier decay

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans. One task file per task; steps use `- [ ]` checkboxes.
> **Give each subagent this overview plus its own task file — never the whole folder.**

**Goal:** Make `working → archival` demotion depend on retrievability alone, and give importance its own recency signal driven by `importance_recency_half_life_days` instead of FSRS stability.

**Architecture:** Two independent background jobs change. `decay_manager.run_decay` loses its importance pre-gate. `importance_scorer.run_importance_scoring` swaps `exp(-days/stability)` for a half-life decay extracted into a module-level pure helper. No new modules, no schema change, no migration.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-08-16-issue-222-importance-decay-gate-design.md`
**Issue:** [r-spade/ormah#222](https://github.com/r-spade/ormah/issues/222) · **Decision source:** #191

## Task map

| File | Task | Deliverable |
|---|---|---|
| `01-worktree-baseline.md` | 0 | Worktree from `upstream/main` + known-red baseline recorded |
| `02-importance-half-life.md` | 1 | Half-life recency + config validator + guard (council I1) |
| `03-decay-gate.md` | 2 | Importance pre-gate removed + negative tests restored (council I2) |
| `04-lifecycle-chain-pin.md` | 2b | `scorer → decay → forgetting` coupling pinned by test (council C1) |
| `05-docs.md` | 3 | `docs/05` + `docs/12` corrected and qualified |
| `06-verify-push.md` | 4 | Full suite vs baseline, diff check, push to `fork` |

Order is strict: 0 → 1 → 2 → 2b → 3 → 4. Task 2b depends on both 1 and 2 being in place.

## Global Constraints

Every task's requirements implicitly include this section.

- **Fork workflow (`FORK-WORKFLOW.md`) is non-negotiable.** Work happens in a git worktree cut from `upstream/main`, never in `/Users/andre/Documents/GitHub/Tools/ormah` itself (that tree serves the running Beta). Push to the `fork` remote only.
- **`decay_importance_threshold` stays in `config.py`.** Its remaining consumer is `forgetting_manager._evaluate_protection` (gate #4), which is gated #28/#31 territory. Only its comment changes. Do NOT rename it, remove it, or touch `forgetting_manager.py`.
- **`importance` is shared state, not a private value.** `forgetting_manager` gate #4 reads the column `importance_scorer` writes, and the sleep cycle (`routes_admin.py:62-72`) runs `importance_scorer → … → decay_manager → forgetting_manager` in one pass. Not editing `forgetting_manager.py` does NOT isolate this change from it — the coupling is through data. Task 2b pins the resulting behavior.
- Lint: `ruff check src/ tests/` must pass; line-length 100.
- **Known-red baseline.** This repo has pre-existing failures on clean `upstream/main`: `A LIMIT or k = ? constraint is required on vec0 knn queries` in auto-link, conflict and worker-thread vector search, plus a setup binary-detection assumption. Task 0 records that baseline. Never claim a suite green without comparing against it.
- Do not modify: `tier_manager.py`, `forgetting_manager.py`, the importance weight/normalization logic, `docs/lifecycle/`, `docs/superpowers/`.

## Council Review (2026-08-16, round 1, Cursor + Codex)

Both peers returned `needs-attention` and converged independently on the same high finding.
Full record: `~/.council/state/r-spade-ormah-683b05e/council-result.md`.

- **C1 (high, both peers)** — `_run_cap_backstop` (`forgetting_manager.py:201-226`) evicts using hard protections only; line 221 says literally *"staleness not required for the cap"*. It never calls `_is_stale_eligible`, so the 90-day graveyard and the retrievability floor do NOT apply to the cap path. A node whose cumulative signals sit in `[0.40, 0.50)` and whose importance is currently inflated by high FSRS stability drops below gate #4 under the new formula, gets demoted (stamping `archived_at=now`), and is immediately cap-eligible. → **Task 2b** + **Task 3 Step 1** + **Task 4 Step 5.3**.
- **I1 (medium, both peers)** — `importance_recency_half_life_days` has no validator; `0` raises `ZeroDivisionError` outside the proposed `except`, killing the whole 120-minute job. → **Task 1**.
- **I2 (medium, Cursor)** — the rewrite leaves no "stays working" test for a normal node. → **Task 2**.

Rejected: both peers proposed fixing gate #4 or the cap directly. That edits `forgetting_manager.py`, which #191 gated and #31 already owes a rebase on. Correct fix, wrong PR — it belongs to #31. Debt recorded at [issue #223](https://github.com/r-spade/ormah/issues/223#issuecomment-5307883033).

**André's ruling (2026-08-16):** document and pin the C1 behavior with a test now; fix it in #31.

## Self-Review

**Spec coverage:** importance pre-gate removed (Task 2) · half-life recency wired (Task 1) · config field kept with updated comment (Task 2) · `test_high_importance_node_not_decayed` inverted (Task 2) · 50-accesses+4-edges case reproduced (Task 2) · recency independent of stability (Task 1) · recency follows configured half-life (Task 1) · importance uses outside decay preserved (Task 1 full suite, Task 2 forgetting suite) · custom weights covered by existing `test_weight_normalization` · docs updated (Task 3) · core/identity protection tested (Task 2) · fork workflow (Tasks 0 and 4). All ✓

**Council coverage:** C1 → Task 2b + Task 3 Step 1 + Task 4 Step 5.3 + the Global Constraint above ✓ · I1 → Task 1 Steps 1b/3/3b ✓ · I2 → Task 2 Step 1 ✓

**Type consistency:** `_recency_signal(days_ago: float, half_life_days: float) -> float` is defined in Task 1 Step 3 and called with that exact signature in Task 1 Steps 1 and 4. `run_decay(engine)` keeps its signature. Task 2b imports `run_importance_scoring`, `run_decay`, `run_forgetting` — all existing module-level functions taking `engine`.

**Placeholders:** none. Two decision points are pre-resolved by verification rather than left to the executor: `config.py` does not import `math` (Task 1 Step 3b), and `docs/12` uses a two-column table (Task 3 Step 4).

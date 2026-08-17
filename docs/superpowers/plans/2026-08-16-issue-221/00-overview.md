# Bounded Stability Reinforcement (#221) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unbounded FSRS stability update with a bounded, diminishing one, allow at most one numeric stability increase per node per day, and centralize the lifecycle math in a single module.

**Architecture:** A new pure module `src/ormah/lifecycle.py` owns every formula (retrievability, spacing, reinforced stability, cooldown). `memory_engine._touch_access` and `background/decay_manager.run_decay` become thin callers. Four new config knobs replace `fsrs_stability_growth`. The boolean `meta.fsrs_migrated` flag becomes an integer `meta.lifecycle_model_version`.

**Tech Stack:** Python ≥3.11, pydantic-settings, pytest (`asyncio_mode = auto`), SQLite, ruff (line-length 100, py311).

**Spec:** `docs/superpowers/specs/2026-08-16-issue-221-bounded-reinforcement-design.md`
**Issue:** [r-spade/ormah#221](https://github.com/r-spade/ormah/issues/221)

## Global Constraints

- **Work only inside `/Users/andre/Documents/GitHub/Tools/ormah-wt-221`** (branch `fix/221-bounded-reinforcement`, cut from `upstream/main` @ `a28837b`). Never edit `Tools/ormah` — it serves the running Beta.
- **Verification command:** `./.venv/bin/python -m pytest <path> -v` from the worktree root. A bare `python -m pytest` imports the `ormah` installed from `local-main` and reports a false green.
- **Never commit** anything under `docs/superpowers/`, `.council/`, `graphify-out/`, `CLAUDE.md`, `INSTRUCTIONS.md`, `SESSION_LOG.md`, `FORK-WORKFLOW.md` in this branch — the pre-push hook blocks the push.
- **The formula is fixed by #191** — do not tune it: `spacing = min(R^-0.2, cap)`, `S' = min(S × (1 + g × S^-w × spacing), max)`, with `g = 0.5`, `w = 0.5`, `cap = 2.0`, spacing exponent `0.2`.
- **Verified target numbers** (recompute if you change anything): `S=1` + 30 days → exactly `2.0`; `S=1` → `365.0` in exactly **74** closely spaced updates.
- Line length 100, `ruff check src/ tests/` must pass.
- Do not rescale existing `stability` values anywhere.
- **Merge prerequisites, not just a preferred order:** #220 (PR #234) and #222 (PR #235) must
  land before this one. Without #220 the branch does not literally implement "confirmed use";
  #222 rewrites the same `recency_signal` line Task 4 now touches. Implement and review freely
  against `upstream/main`, but hold the merge.
- **Any new decay test must lower `importance` below `decay_importance_threshold`.** Both the
  node default and the threshold are `0.5` and the gate is `>=`, so a test left at the default
  never reaches the retrievability code it claims to exercise. See Task 4.
- **The importance scorer gets the anchor flip and NOTHING else** (council round 2, C2). Do not
  import `lifecycle` there, do not read `r["stability"]`, do not replace the recency formula.
  After #222 that column is not selected, and `sqlite3.Row` raises an `IndexError` the surrounding
  `except (ValueError, TypeError)` does not catch — aborting the whole scoring job. See Task 4
  Step 5, which carries the `grep` that catches an overreach.
- **The same-device restore bypass is OUT OF SCOPE** (council round 2, both peers, `high`;
  decision: André, 2026-08-16). `full_rebuild` preserves `meta` and `reload_restored_graph` never
  calls `_migrate_fsrs`, so a pre-FSRS backup restored onto a migrated install skips the seed.
  Pre-existing on `a28837b`, so it goes to its own issue: r-spade/ormah#236. What this branch owes: never claiming
  the C3 `last_review` guard covers restore in general. See Task 5.
- **A verification step that contradicts its own task is the failure mode of this plan**
  (council round 3: 4 of 5 findings were gates, not code). Three greps had to be rewritten because
  they demanded a state the implementation forbids, or a zero count that would delete a test. When
  you touch any task, re-read **its verification steps** — they are not reaudited automatically by
  a fold, and they are what an implementer obeys when the prose and the gate disagree. If a gate
  and a step conflict, the gate is wrong until proven otherwise: stop and report, never "fix" the
  code to satisfy the gate.
- **Downgrade below the new lifecycle model is UNSUPPORTED** (council round 3, C2; decision:
  André, 2026-08-16). The dual `fsrs_migrated` + `lifecycle_model_version` write prevents a
  *reseed* on rollback; it does not prevent an old binary from writing unbounded stability under a
  version marker that says otherwise. Policy only — detecting an old-model write needs per-node
  provenance and is explicitly out of scope. See Task 5.
- **The reinforcement cooldown must be serialized** (council round 3, I1). The check-then-write
  pair is TOCTOU, and the recall paths that reach `_touch_access` carry no
  `@_serialized_memory_operation`. See Task 3.

## Setup (once, before Task 1)

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-221
python3 -m venv .venv
./.venv/bin/pip install -q -e ".[dev]"
./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v
```

Expected: the decay suite passes on unmodified `upstream/main`. That green is the baseline every later task compares against.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/ormah/lifecycle.py` (create) | All lifecycle math; no I/O, no DB, no settings object | 1 |
| `tests/test_lifecycle.py` (create) | Unit tests for the math (AC1, AC2, AC3) | 1 |
| `src/ormah/config.py` (modify) | Add 4 knobs + validators — **additive only** | 2 |
| `tests/test_config_fsrs.py` (create) | Validator coverage (AC7) | 2 |
| `src/ormah/config.py` (modify) | Remove `fsrs_stability_growth` + its validator entry | 3 |
| `tests/test_config_fsrs.py` (modify) | The two removal tests | 3 |
| `src/ormah/engine/memory_engine.py:1936` (modify) | `_touch_access` → cooldown + helper call + serialized (AC4) | 3 |
| `tests/test_engine/test_reinforcement_cooldown.py` (create) | Cooldown behavior, incl. concurrency | 3 |
| `src/ormah/background/decay_manager.py` (modify) | Shared retrievability + inverted anchor (AC5) | 4 |
| `src/ormah/background/importance_scorer.py` (modify) | Anchor flip **only** — never the formula (council C2, corrected round 2) | 4 |
| `tests/test_background/test_importance_scorer.py` (modify) | Recency ignores a lagging `last_review` | 4 |
| `src/ormah/engine/memory_engine.py:159` (modify) | Integer lifecycle-model version (AC6) | 5 |
| `docs/12 - Configuration Reference.md`, `docs/05`, `docs/01` (modify) | Config + behavior docs (AC7) | 6 |

## Task Order

1. **Task 1** — `lifecycle.py` + its unit tests. No dependencies.
2. **Task 2** — config knobs. No dependencies.
3. **Task 3** — `_touch_access`. Needs Tasks 1 and 2.
4. **Task 4** — `decay_manager`. Needs Task 1.
5. **Task 5** — lifecycle-model version. Independent, but land after 3 so the version marks a store that already runs the new curve.
6. **Task 6** — docs. Needs Tasks 2–5.

## Acceptance Criteria → Task Map

| AC | Task |
|---|---|
| `S=1` after 30 days → `1 → 2` | 1 |
| Spacing finite for extremely old nodes, no underflow failure | 1 |
| Diminishing growth; ~74 updates from `S=1` to the cap | 1 |
| Ten uses in one day → one numeric update, latest use time recorded | 3 |
| Decay manager and reinforcement share one retrievability implementation | 1, 4 |
| Lifecycle-model versioning represents more than migrated/not-migrated | 5 |
| Config validation, tests, and configuration docs cover every new knob/state | 2, 6 |

## Final Gate (after Task 6)

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-221
./.venv/bin/python -m pytest tests/ -v
./.venv/bin/python -m ruff check src/ tests/
git log --oneline upstream/main..HEAD
```

The `git log` must show only the commits from this plan. Anything else means the island was cut from the wrong base — rebuild it before pushing.

# Port #221 (bounded reinforcement) onto local-main's post-#220 API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring #221's bounded reinforcement into `local-main`, which already carries #220 and #222, without reintroducing the surfacing regression #220 removed.

**Architecture:** `fix/221-bounded-reinforcement` was cut from `upstream/main @ a28837b`, before #220 and #222. On `local-main`, `_touch_access` no longer exists — #220 renamed it to `_record_confirmed_use` and cut it from five call sites to two, both behind the `_claim_confirmed_use` at-most-once latch. This is a **port**, not a merge: the reinforcement logic moves into #220's method and **#221's five call sites are discarded**. `lifecycle.py`, the config knobs, `decay_manager` and the migration port essentially unchanged; `importance_scorer` needs only a one-line anchor flip, because #222 already replaced its FSRS recency with a half-life clock.

**Tech Stack:** Python ≥3.11, pydantic-settings, pytest (`asyncio_mode = auto`), SQLite, ruff (line-length 100, py311).

**Source of truth for ported code:** commit `4cf017f` on `fix/221-bounded-reinforcement`. Where a step says "port verbatim", use `git show 4cf017f:<path>` — do not retype.

## Global Constraints

- **Work only in `/Users/andre/Documents/GitHub/Tools/ormah-wt-221-integ`** (branch `integration/221-on-local-main`, cut from `local-main`). Never edit `Tools/ormah` — it serves the running Beta.
- **Verification command:** `./.venv/bin/python -m pytest <path> -v` from that worktree. A bare `python -m pytest` imports the `ormah` installed from another checkout and reports a false green.
- **`_touch_access` must not exist when this is done, and no call site may be added.** `_record_confirmed_use` keeps exactly its two callers. Reintroducing reinforcement on a search path is the regression #220 exists to remove; a grep gate in Task 2 checks it.
- **The formula is fixed by #191 — do not tune it:** `spacing = min(R^-0.2, cap)`, `S' = min(S × (1 + g × S^-w × spacing), max)`, with `g = 0.5`, `w = 0.5`, `cap = 2.0`.
- **Do not change any default.** `fsrs_reinforcement_cooldown_days` stays `1.0` (decision: André, 2026-08-17). The #220 latch plus this cooldown make growth much slower than either issue alone implied; that is the conservative direction and is deliberate.
- **Do not rescale existing `stability` values anywhere.** This carries a docs obligation, owed by Task 6.
- **Every commit on this branch passes the full suite.** No task ships a known-red test for a later task to fix. This is why Task 1 leaves out one removal test that Task 2 adds back — the knob it asserts against is still in use until then.
- Line length 100, `ruff check src/ tests/` must pass.
- This branch is local-only. It is **never** pushed to `upstream`, and it does not replace PR #239.

## Baseline

Measured on `integration/221-on-local-main` at `3bfe663` before Task 1, with the worktree's own venv:

```text
./.venv/bin/python -m pytest tests/ -q
2545 passed, 11 deselected, 1 warning in 107.80s
```

**The baseline is green — zero failures.** Do not carry over the "11-12 environmental failures" figure from the `fix/221-bounded-reinforcement` worktree: that branch sits on `upstream/main @ a28837b`, which predates `local-main`'s test-isolation fixes. On this branch the developer's real configuration no longer leaks into `test_config`, `test_consolidator`, `test_session_watcher` or `test_setup`.

This makes the gate strict: **any failure during this port is a real regression.** There is no known-red set to subtract. If something fails, stop and report it rather than matching it against a remembered baseline.

Venv isolation was verified, not assumed: `./.venv/bin/python -c "import ormah; print(ormah.__file__)"` resolves inside this worktree.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/ormah/lifecycle.py` (create) | All lifecycle math; no I/O, no DB, no settings object | 1 |
| `tests/test_lifecycle.py` (create) | Unit tests for the math | 1 |
| `src/ormah/config.py` (modify) | Add 4 knobs + validators — additive only | 1 |
| `tests/test_config_fsrs.py` (create) | Validator coverage | 1 |
| `src/ormah/engine/memory_engine.py` (modify) | `_record_confirmed_use` → cooldown + bounded helper | 2 |
| `src/ormah/config.py` (modify) | Remove `fsrs_stability_growth` + its validator entry | 2 |
| `tests/test_engine/test_reinforcement_cooldown.py` (create) | Cooldown behavior, incl. concurrency | 2 |
| `src/ormah/background/decay_manager.py` (modify) | Shared retrievability, anchor flip, scoped timestamp failure | 3 |
| `src/ormah/background/importance_scorer.py` (modify) | Anchor flip only — one line | 4 |
| `src/ormah/engine/memory_engine.py` (modify) | Integer lifecycle-model version | 5 |
| `docs/12`, `docs/05`, `docs/01` (modify) | Config + behavior docs | 6 |

## Task Order

Task 1 → 2 → 3 → 4 → 5 → 6. Task 2 needs 1. Task 3 needs 1. Tasks 4 and 5 are independent but land after 2 so every commit passes the suite.



## Final Gate

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-221-integ
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/python -m ruff check src/ tests/
git log --oneline local-main..HEAD
grep -rn "_touch_access" src/ tests/
```

Expected: the suite back at the recorded baseline and no worse; ruff clean; six commits, one per task, nothing inherited; **zero** hits for `_touch_access`.

Then, and only then, merge into `local-main` with `--no-ff` from `Tools/ormah`, committing by exact paths — `graphify-out/` is dirty by design and must stay out of the merge commit.

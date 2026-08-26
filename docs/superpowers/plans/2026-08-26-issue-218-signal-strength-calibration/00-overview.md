# Issue #218 — ordinal evidence scale for `signals.strength`: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. **Each subagent receives only this overview plus its own
> task file.**

**Goal:** Make `signals.strength` a single ordinal evidence scale — comparable in rank across
channels — so #272 and #191 can gate on it.

**Architecture:** A new leaf module `src/ormah/signal_strength.py` owns the ladder (constants +
three pure functions + one recompute helper). The three existing write sites import it. A backfill
migration recomputes historical rows exactly from the `evidence` JSON they already carry.

**Tech Stack:** Python ≥3.11, pytest (`asyncio_mode = auto`), SQLite, ruff (`py311`, line-length
100).

**Spec:** `docs/superpowers/specs/2026-08-26-issue-218-signal-strength-calibration-design.md`
(commit `069f611`). Read section 4 before Task 2.

## Global Constraints

- **Base is `upstream/main` @ `90c431e`.** Every line number in these task files is upstream's.
- **Work in the island `../ormah-wt-218`, never in `Tools/ormah`** — that tree is what the launchd
  Beta serves; switching its branch crashes every whisper hook (FORK-WORKFLOW golden rule 1).
- **Never trust a test number without the import gate** (Task 1). Every pytest invocation in this
  plan runs as:
  `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest ... -q`
  Redirect to a file and append `PYTEST_EXIT=$?`; never pipe pytest to `tail`.
- **`ruff check src/ tests/` must pass** before every commit.
- **Line length 100.**
- **`strength` has no readers** in `src/`, `ui/`, `schema.sql` or `db.py`. No behaviour may change.
  `tests/test_engine/test_confirmed_use_contract.py` staying green is the proof; a failure there
  falsifies the premise and sends the design back rather than getting patched around.
- **Out of scope, do not touch:** `_CONFIRMED_USE_SOURCES`, `_claim_confirmed_use`, the
  `session_watcher.py:495` judge suppression. That is #272.

## The ladder (authoritative — every task must match these values)

| band | channel / evidence | mapping |
|---|---|---|
| `1.00` | `explicit` | constant |
| `0.98` | heuristic `node_id` | constant |
| `0.94` | heuristic `title` | constant |
| `0.92` | heuristic `sentence` | constant |
| `0.82–0.90` | `auto_llm_judge` | affine `[min_confidence, 1.0] → [0.82, 0.90]` |
| `0.80` | `implicit` | constant |
| `0.40–0.78` | heuristic `token_overlap` | `0.40 + 0.38·(1 − e^−(r−0.5))` |
| `0.00` | any row with `polarity = 0` | convention |

## File structure

| file | responsibility |
|---|---|
| `src/ormah/signal_strength.py` | **new.** The ladder: constants, three channel functions, one recompute helper. Leaf — imports only `json` and `math`. |
| `src/ormah/background/session_watcher.py` | two write sites (heuristic, judge) call the ladder |
| `src/ormah/engine/memory_engine.py` | one write site (`submit_feedback`) + the backfill migration |
| `tests/test_engine/test_signal_strength.py` | **new.** Ladder unit + band-disjointness property |
| `tests/test_background/test_usage_signal_strength.py` | **new.** Watcher write sites, end to end |
| `tests/test_engine/test_feedback_signal_strength.py` | **new.** `submit_feedback` write site |
| `tests/test_engine/test_signal_strength_backfill.py` | **new.** Migration exactness + idempotence |

New focused test files rather than appending to `test_session_watcher.py` (already ~4,000 lines
upstream).

## Tasks

| # | file | deliverable |
|---|---|---|
| 1 | `01-island-setup.md` | island worktree + venv + **proven** import gate |
| 2 | `02-ladder-module.md` | `signal_strength.py` + its unit tests, no callers yet |
| 3 | `03-heuristic-write-site.md` | `_node_usage_evidence` on the ladder |
| 4 | `04-judge-write-site.md` | judge records use the judge band |
| 5 | `05-submit-feedback-write-site.md` | `explicit` ≠ `implicit` strength |
| 6 | `06-backfill-migration.md` | idempotent recompute of historical rows |

Task 2 comes first — every other task imports it. Task 4 appends to the test file Task 3
creates, so **4 follows 3**. Task 5 and Task 6 are independent of 3 and 4 and of each other,
though Task 6 reuses the `signal_strength` import Task 5 adds to `memory_engine.py` (it adds it
itself if Task 5 has not run).

## Done

All six tasks committed, `ruff` clean, the full suite green under the import gate, and
`test_confirmed_use_contract.py` still passing untouched.

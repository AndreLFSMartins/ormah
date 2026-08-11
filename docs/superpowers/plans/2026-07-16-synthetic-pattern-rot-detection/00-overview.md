# Synthetic-Pattern Rot Detection — Implementation Plan (overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect synthetic-prompt patterns that stopped matching and file a proposal asking the user to remove or repair them — so the #134 pattern list stops rotting invisibly.

**Architecture:** `is_synthetic_prompt` starts returning *which* regex matched instead of a bool; that value lands in a new `whisper_decisions.matched_pattern` column; a daily LLM-free job compares each live pattern's `last_seen` against a rot threshold and files a `pattern` proposal into the existing `proposals` table. Nothing is auto-applied.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, APScheduler, pytest (`asyncio_mode=auto`), ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-07-16-synthetic-pattern-rot-detection-design.md`
**Issue:** [#143](https://github.com/r-spade/ormah/issues/143) — slice 1 of 2.
**Revision:** REV 2 — council-reviewed 2026-07-16 (Cursor: approved with caveats; Codex: needs-attention,
2 criticals). 6 findings accepted, 4 rejected. Full record: `$COUNCIL_HOME/council-result.md`.

## Global Constraints

- **Branch:** cut `feat/synthetic-pattern-rot-detection` from `fix/whisper-synthetic-prompt-filter`, **not** from `upstream/main` (PR #141 is still OPEN and the consumed APIs do not exist upstream). Push to `fork`, never `upstream`. See `FORK-WORKFLOW.md`.
- **Do not commit this plan or the spec.** `docs/superpowers/` is gitignored (`.gitignore:103`).
- **ProposalType must be `pattern`, never `decay`.** `decay_manager.py:20-24` runs `DELETE FROM proposals WHERE type='decay' AND status='pending'` on every run, unguarded — reusing that value means our proposals get eaten nightly.
- **`proposed_action` must derive from the regex alone.** It is the dedup key. Any count or date in it changes every run, the dedup never hits, and the job files one proposal per day forever. Variable evidence goes in `reason`.
- **Callers of `match_synthetic_pattern` must test `is not None`, never truthiness.** The empty regex `""` matches everything and returns `""` — falsy but a real match.
- **No signal without the filter.** `find_rotted_patterns` returns `[]` when `whisper_synthetic_filter_enabled` is false. With the filter off nothing writes `silent_synthetic`, so every pattern would age into a false proposal claiming an upstream rename that never happened (council C1).
- **Rot needs opportunity, per pattern.** A pattern is only rotted if enough whisper traffic happened *since it last fired* (`whisper_pattern_rot_min_opportunity`, default 50). "Was there any traffic at all" was satisfied by a single prompt after a month away and rotted the whole list (final review).
- **Zero-valued knobs are rejected.** `rot_days`, `monitor_interval_minutes`, `rot_min_matches` and `rot_min_opportunity` must all be >= 1. At `0`, `interval_minutes` became an invisible 1-second hot loop and `rot_days` silently disabled the job — opposite disasters, both silent (final review).
- **`Database` takes a `Path`, never a `str`** — `db.py:23` calls `db_path.parent.mkdir()`.
- Ruff: line-length 100, `from __future__ import annotations` at the top of new modules.
- Every task ends green on `python -m pytest <its test file> -v` before commit.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/ormah/engine/prompt_classifier.py` | **Modify.** `is_synthetic_prompt -> bool` becomes `match_synthetic_pattern -> str \| None`. |
| `src/ormah/api/routes_agent.py:16,149-157` | **Modify.** Call-site: new import, `is not None` test, pass `matched_pattern` through. |
| `src/ormah/index/schema.sql:222-238` | **Modify.** `matched_pattern TEXT` on `whisper_decisions` (fresh installs). |
| `src/ormah/index/db.py` | **Modify.** `_migrate_whisper_decisions_schema` + its call inside `_migrate()`. |
| `src/ormah/engine/context_builder.py:293-327` | **Modify.** `_log_decision` gains `matched_pattern`. |
| `src/ormah/engine/memory_engine.py:1257-1273` | **Modify.** `note_synthetic_whisper_skip` threads `matched_pattern`. |
| `src/ormah/config.py:267-268` | **Modify.** Two settings. |
| `src/ormah/models/proposals.py:12-15` | **Modify.** `ProposalType.pattern`. |
| `ui/src/types.ts:84` | **Modify.** Hand-maintained union mirror. |
| `src/ormah/background/synthetic_pattern_monitor.py` | **Create.** Detection (pure) + the job. |
| `src/ormah/background/scheduler.py` | **Modify.** Register the job. |
| `src/ormah/api/routes_admin.py:24-55` | **Modify.** `_TASK_RUNNERS` + `_TASK_DESCRIPTIONS`. |

## Tasks

| # | File | Deliverable |
| --- | --- | --- |
| 1 | `01-match-synthetic-pattern.md` | `match_synthetic_pattern` returns the regex source; boundary still filters correctly. |
| 2 | `02-matched-pattern-column.md` | The boundary records *which* pattern fired in `whisper_decisions`. |
| 3 | `03-detection-logic.md` | Settings + `ProposalType.pattern` + `find_rotted_patterns` (pure, no side effects). |
| 4 | `04-job-and-registration.md` | The job files deduped proposals and is registered in the scheduler. |

Order is strict: task 2 consumes task 1's return value; task 4 consumes task 3's detection and task 2's column.

## Deviation from the spec (deliberate, verified)

The spec said to register the job in four places including `_SLEEP_CYCLE_ORDER`. **Reading the code corrected this:** `whisper_log_cleanup` — the closest analogue (background whisper maintenance, no LLM) — is registered *only* in `scheduler.py` and appears in neither `_TASK_RUNNERS` nor `_SLEEP_CYCLE_ORDER` (verified: `grep whisper_log_cleanup src/ormah/api/routes_admin.py` returns nothing).

This plan registers in `scheduler.py` + `_TASK_RUNNERS` + `_TASK_DESCRIPTIONS` (the manual `/admin` trigger is what makes rot verifiable without waiting 30 days) but **not** `_SLEEP_CYCLE_ORDER` — that pass is memory consolidation; config hygiene does not belong in it.

Also not touched: `_stagger_factor` (`scheduler.py:33-38`), which hardcodes the four LLM jobs. This job makes no LLM call.

## Verification (after task 4 — not "tests pass")

1. `make test` and `make lint` green, output cited.
2. Open a pre-change DB: confirm `matched_pattern` exists (`PRAGMA table_info(whisper_decisions)`) and the server starts.
3. Drive the real path on the running Beta: send `<task-notification>test` to `/agent/whisper`, confirm one `whisper_decisions` row with `outcome='silent_synthetic'` and `matched_pattern='<task-notification>'`.
4. Force rot: `ORMAH_WHISPER_PATTERN_ROT_DAYS=1` (`0` is now rejected by the validator), trigger via
   `/admin`, confirm one proposal per live pattern with history; trigger again, confirm no duplicates.
   Note the pattern also needs `whisper_pattern_rot_min_opportunity` (50) decisions logged since it last
   fired, or the opportunity guard correctly stays silent.
5. Run `run_decay` and confirm the `pattern` proposals survive (the `decay_manager.py:20-24` trap).

## Out of scope

The LLM miner (slice 2); wiring the orphaned `ReviewQueue` (#82); editing the user's `.env`; auto-applying patterns. Also out of scope, though found while exploring — each deserves its own issue: the unguarded `DELETE` in `decay_manager.py:20-24`, the fragile `"\n---\n"` split at `routes_agent.py:353`, and `ResolveProposalRequest` accepting `pending` (`proposals.py:36`).

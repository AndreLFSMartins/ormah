# Review Relevance Is Not Confirmed Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each task lives in its own file; an implementer receives this overview plus their one task file. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a relevance judgement on a memory that was never surfaced from reinforcing that memory's lifecycle.

**Architecture:** Gate the confirmed-use claim on `was_injected = 1` inside `_claim_confirmed_use`'s own INSERT, turning `INSERT ... VALUES` into `INSERT ... SELECT` over `whisper_log`. `SELECT changes()` stays the verdict. Two of the three callers already satisfy the precondition, so only the session-start review path changes behaviour.

**Tech Stack:** Python 3.12, SQLite (`sqlite3`), pytest (`asyncio_mode = auto`), ruff.

**Spec:** `docs/superpowers/specs/2026-08-16-review-relevance-not-confirmed-use-design.md`

## Tasks

| # | File | Deliverable |
|---|---|---|
| 1 | `01-gate-the-claim.md` | Contract 11 test, the SQL gate, and the docstring that states it |
| 2 | `02-pin-legacy-fallback.md` | Contract 11a, pinning the loss Task 1 introduces in the legacy fallback |

Task 2 consumes a helper Task 1 creates, so run them in order.

## Global Constraints

- **Work in the worktree**: `/Users/andre/Documents/GitHub/Tools/ormah-wt-220`, branch `fix/220-confirmed-use`. Never `git checkout` inside `Tools/ormah` (Golden rule 1, `FORK-WORKFLOW.md`).
- **Interpreter**: always `./.venv/bin/python -m pytest`. **Never** bare `python -m pytest` and **never** `make test` — both resolve to the `Tools/ormah` venv and measure `local-main`. Verify before trusting any number: `./.venv/bin/python -c "import ormah; print(ormah.__file__)"` must print a path under `ormah-wt-220/src/`.
- **Do not push and do not open a PR.** Push to `fork` is not authorised; PR #229 still declares `Closes #220-#223`.
- **Nothing under `docs/` may enter this branch** (Golden rule 5). This plan and its spec live on `local-main` in `Tools/ormah`.
- `make lint` (`ruff check src/ tests/`) passes before each commit. Line length 100.
- Baseline measured 2026-08-16 before any change: `tests/test_engine/test_confirmed_use_contract.py` → **25 passed**.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/ormah/engine/memory_engine.py` | `_claim_confirmed_use` — the single writer of `confirmed_use_claims` | Modify the INSERT (L2556-2563) and the docstring's fail-closed clause (L2546-2547) |
| `tests/test_engine/test_confirmed_use_contract.py` | Contract tests for issue #220; asserts lifecycle from **both** markdown and SQLite | Add one helper and two tests |

No new source files. Contracts continue the existing numbering: the file ends at 10f/7c, so the new ones are **11** and **11a**.

The spec lists four tests; two of them are already in the file and must **not** be rewritten:

- The **control** (an injected event still confirms) is `test_qualified_positive_feedback_confirms_use`, already parametrised over `explicit`/`implicit`/`auto_llm_judge`. It seeds through `_seed_whisper_log` → `recall_search` → `_log_feedback_candidates`, which hardcodes `was_injected = 1`, so it exercises exactly the positive side of the new gate.
- The **neighbour regression** check is the existing suite: contracts 7a, 8, 10b, 10e and 10f each need a claim to still be taken for injected events. They are re-run, not rewritten.

## After both tasks

1. Re-invoke `/council-pr` from **inside the worktree** (it runs from `cwd`), as a fresh round 1.
2. Still unauthorised, do not do these without asking: push `fix/220-confirmed-use` to `fork`; open a PR (#229 still declares the `Closes`).
3. Carry into the PR body when it opens: the refutation of Codex finding #2 (the at-most-once contract), so the next human reviewer does not reopen it.

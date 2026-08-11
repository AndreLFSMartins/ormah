# Frozen-Prefix Cursor Loss — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each task lives in its own file; a worker gets THIS overview plus ONE task file.

**Goal:** Stop `SessionHandler` from advancing the durable byte cursor over transcript bytes that were never ingested.

**Revision 2.** Revision 1 was rejected by `/council` on 2026-08-09 — Cursor and Codex both no-ship, convergent, on the same root: `requeue(failure_class="external")` converts a bounded dead-letter into an unbounded hot queue. They were right, and the cost model was wrong by two orders of magnitude. Both peers then proposed a durable *park* state. This revision goes the other way, on a measurement neither peer had. See "Why deletion, not a park" below.

**Architecture:** Delete BOTH `_mark_frozen_prefix_consumed` and `_idle_with_unsafe_tail`, and let the `NO_PROGRESS` path fall through to `complete(job)`. No new failure class, no new persisted field, no park token. Suppression of re-selection is not replaced — it is **abandoned**, because its cost was measured and is negligible.

## Why deletion, not a park

Every mechanism ADR-0004 has tried — force-close, watermark, park token, prefix digest, and Revision 1's `requeue` — exists to satisfy ONE requirement: stop `reconcile` re-selecting a frozen transcript. That is a **cost** requirement, not a correctness one, and across 56 council rounds it was never measured.

Measured 2026-08-09:

| | |
|---|---|
| `complete()` does | `os.unlink` on the job — it disappears, nothing accumulates |
| `reconcile` enqueues | **max 50 per tick** (`session_watcher_reconcile_max_per_tick`), every 5 min, oldest-first |
| worst-case tick (50 largest live dead-lettered transcripts) | **151.4 MB** |
| time to parse those 50 | **0.50 s** |
| duty cycle | **0.17%** |

229 live transcripts sit in that condition, but the per-tick cap makes the cost independent of the population. Half a second every five minutes.

Two peer objections dissolve rather than being answered:

- The `claim_next` pending→running→pending thrash (Cursor) is **specific to `requeue`** — jobs persisting in `pending/`. With `complete()` the job is unlinked and does not exist.
- Stranding on acceptance-only roots (the reason Revision 1 rejected `complete()`) is covered by the Observer: `on_modified` → `spool.enqueue`, independent of `reconcile`. Both roots run `observer=True`.

**Why the five mechanisms never converged:** all were fail-CLOSED — if wrong, they suppressed selection and lost data, so each needed exact identity (generation, inode, digest) and exact ordering, and each new guarantee created the next failure surface. Deletion is fail-OPEN: if wrong, it re-selects (0.5 s / 5 min) and never loses. That asymmetry is the difference.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), ruff (line-length 100, py311).

**Spec:** `docs/superpowers/specs/2026-08-09-frozen-prefix-cursor-loss-design.md`

## The defect in one paragraph

An idle transcript whose accepted bytes close no user→assistant pair had its cursor advanced past that prefix, so `reconcile` would stop re-selecting it. But the prefix *begins with a prompt*. Once the cursor jumped it, the response that later closed could never be paired with its prompt. Production on 2026-08-09 held **49 state entries** carrying the signature of this loss — an entry with only `end_offset` and no `hash`/`node_ids`. Measured, the cursor stopped 1.5 KB–8 KB short of the first close.

## Global Constraints

Every task's requirements implicitly include this section.

- Target branch: a worktree cut from **`local-main`**, NOT `upstream/main`. The code being fixed does not exist upstream (verified: 0 occurrences of all three symbols); it entered via `adbec81`, for which no PR was ever opened.
- **NEVER `git checkout` inside `/Users/andre/Documents/GitHub/Tools/ormah`.** That working tree is what the running Beta (launchd `com.ormah.server.dev`) serves live. FORK-WORKFLOW Golden rule 1.
- `docs/superpowers/` is gitignored (`.gitignore:94,121`). Never `git add` anything under it, never `git add -f`.
- Lint gate: `ruff check src/ tests/` must pass, line-length 100.
- Every commit must leave the suite green. Obsolete tests are updated in the SAME task that breaks them.
- Do NOT touch `.session_watcher_state`, the Codex parser, or the 24 orphaned entries. Out of scope.
- **`/council-pr` is mandatory before the merge** (`INSTRUCTIONS.md:15` — "Merge to main only via `/council-pr`"). Revision 1 skipped it; Codex caught that. Task 4 now gates on it.
- All test helpers referenced by the tasks (`_make_jsonl`, `_partial_unterminated`, `_mark_idle`, `_drain_all`, `_handler_with_spool`, `_LLM_PATCH`, `_LLM_RESPONSE`) already exist in `tests/test_background/test_session_watcher.py`. Do not redefine them.

## Setup — run once, before Task 1

- [ ] **Create the worktree from `local-main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree add -b fix/frozen-prefix-cursor-loss ../ormah-wt-frozen-prefix local-main
```

- [ ] **Verify the Beta's working tree was NOT switched**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah branch --show-current
```

Expected: `local-main` (unchanged). Anything else means the live server's code was swapped — STOP.

- [ ] **Confirm the defect is present in the worktree**

```bash
grep -c "_mark_frozen_prefix_consumed" ../ormah-wt-frozen-prefix/src/ormah/background/session_watcher.py
```

Expected: `2`

**All tasks run inside `../ormah-wt-frozen-prefix`.**

## Tasks

| # | file | deliverable |
|---|---|---|
| 1 | `01-cost-guard.md` | Characterization test pinning that a fully consumed file completes instead of requeueing. Green before AND after the fix. |
| 2 | `02-the-fix.md` | The fix itself: two failing tests, the `_run_job` change, the deletion, and the four existing tests it invalidates. |
| 3 | `03-prove-recovery.md` | Proof of the payoff: the prompt survives and is paired once the response closes. |
| 4 | `04-land-in-beta.md` | Full suite, merge into `local-main`, restart the Beta, confirm the orphan set stopped growing. |

Run them in order. Task 1 exists before Task 2 on purpose: it is the guard that stops the fix from turning every benign no-op into an endless retry loop.

## Interfaces that cross task boundaries

- `IngestSpool.complete(job)` — `os.unlink` on the claimed job file. Idempotent. Nothing is persisted, nothing accumulates.
- `IngestSpool.requeue(job, failure_class="external")` stays in use for the `shrink_pending` gate ONLY. Revision 2 does not extend it to any new caller.
- After Task 2, BOTH `SessionHandler._mark_frozen_prefix_consumed` and `SessionHandler._idle_with_unsafe_tail` **cease to exist**, and `failure_class="no_safe_boundary"` is gone from the codebase. Later tasks must not reference any of the three.

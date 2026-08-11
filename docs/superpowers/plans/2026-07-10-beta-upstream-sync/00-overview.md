# Beta ↔ Upstream Sync — Implementation Plan (overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline — recommended for this plan) or superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. One file per task in this directory.

**Goal:** Re-sync the Beta (Tools/ormah, `local-main`) with upstream r-spade/ormah by rebasing the 6 open PRs onto current `upstream/main`, folding the unpushed council hardening into PR #79, and assembling the new Beta = upstream + sum of rebased PRs — losing zero Beta-only commits.

**Architecture:** All rebase/assembly work happens in the dev clone (`ormah-dev`); the Beta clone only receives the final assembly by MERGE (its rule). Old `local-main` is the composition reference for how the features coexist. Every history rewrite is preceded by a backup tag; every push is `--force-with-lease`; every test run overrides the leaking global `~/.config/ormah/.env`.

**Tech stack:** git (rebase, merge, cherry/patch-id, merge-tree), gh CLI, pytest, launchd.

## Decisions (André, 2026-07-10)

1. Strategy (a): rebase the 6 PRs onto `upstream/main`; Beta = sum of rebased PRs.
2. Unpushed council-pr hardening (H1/H2/I2/I3 + lint, 07-08/07-09) goes INTO PR #79 during its rebase.
3. Scope: full sync in one pass (upstream tip `2e76b5b`, 0.13.5 + 2 commits, verified 2026-07-10).
4. #79 is destined to merge upstream → the claude_cli delta is temporary; keep every PR review-ready.

## Clone / remote map (do not confuse)

| Clone | Path | Remotes | Role |
|---|---|---|---|
| dev | `/Users/andre/Documents/GitHub/ormah-dev` | `upstream`=r-spade, `origin`=fork (AndreLFSMartins) | ALL rebases/assembly here |
| Beta | `/Users/andre/Documents/GitHub/Tools/ormah` | `origin`=r-spade, `fork`=AndreLFSMartins | runtime `local-main`; receives final MERGE only (Task 6) |

launchd `com.ormah.server` (port 8787) serves from the Beta working tree — stopped only during Task 6.

## Council review (2026-07-10, cursor+codex, R1) — 8 fixes folded in

APPROVED WITH CAVEATS. Strategy (a) endorsed by both peers over the single-merge; both returned "do not execute as-is". All 8 accepted findings are now embedded in the tasks below (see `.council/council-result.md`):

- **C1 (crit)** — zero-loss gate checks ancestry, not surviving CONTENT → content-preservation manifest (`range-diff`/patch-id + core-path diff vs `refs/tmp/beta-local`) before restart. Tasks 5–6.
- **C2 (crit)** — no data-store backup before new-code migrations (0.13.3–0.13.5) touch the SQLite/markdown store; `git reset` won't undo a migration → back up the data dir + verify restore before merge. Task 6.
- **I1** — `/council-pr` on the assembly is MANDATORY before touching `local-main` (INSTRUCTIONS rule 3), not optional. Task 6.
- **I2** — #92 was rebased 07-09 over the then-current upstream; upstream moved 2 commits since → re-verify #92's base, re-rebase if stale. Task 1.
- **I3** — `make install` does NOT rebuild `ui_dist` served by launchd → build UI + asset smoke. Tasks 6–7.
- **I4** — Tasks 2–4 suite gates were manual (`tail -3`) → automated `diff` vs `baseline-failures.txt`, block push on any new failure. Tasks 2–4.
- **I5** — hardening cherry-pick after #79 rebase may duplicate already-absorbed logic → patch-id dedup, skip empty picks. Task 3.
- **M1** — `claude_cli` integration test excluded from gates → run `pytest -m integration -k claude` once before Beta merge. Tasks 3/7.

**Structural change (Cursor suggestion, adopted):** Task 6 merges into a **staging branch `local-main-next`**, fully validates the runtime there, and only then promotes to `local-main` — instant rollback without ever touching the live runtime branch.

## Tasks

| # | File | What | Gate |
|---|---|---|---|
| 1 | `01-preflight-inventory.md` | Fetches, PR head/review-activity audit + **#92 base re-verify (I2)**, test baselines, Beta-delta manifest (patch-id) | CHECKPOINT: André approves the `to-pr79` commit list |
| 2 | `02-rebase-small-prs.md` | Rebase #57 → #60 → #68 → #38 → #31, each green + pushed + PR comment | **automated** suite gate per PR (I4) |
| 3 | `03-rebase-pr79-with-hardening.md` | Rebase #79 + cherry-pick hardening (**patch-id dedup, I5**), green, push | suite gate + `-m integration -k claude` (M1) |
| 4 | `04-pr87-open.md` | Re-rebase `feat/87-pair-batching`, open the PR upstream | **automated** suite gate + PR created (I4) |
| 5 | `05-assembly-branch.md` | `integration/beta-sync-20260710` = upstream/main + all PR branches, full suite + **content-preservation manifest (C1)** | suite gate + range-diff review |
| 6 | `06-merge-into-beta.md` | **Store backup (C2)**, stop runtime, merge assembly → **`local-main-next`**, UI build (I3), suite, **`/council-pr` (I1)**, content check (C1), promote → `local-main`, restart | CHECKPOINT + `/council-pr` gate + suite gate |
| 7 | `07-runtime-verify-close.md` | Health/MCP/functional + **UI asset smoke (I3)**, PR mergeable sweep, memories, cleanup, session close | health 200 + no pydantic errors + fresh bundle |

Already done (2026-07-09, do not redo): #92/`feat/90-maintenance-observability` rebased+pushed (tip `5c63ed2`); `feat/87-pair-batching` rebased (tip `8a2f474`); backups `backup/feat-90-pre-rebase`, `backup/feat-87-pre-rebase`.

## Global rules (apply to every task)

- **Test command (always with env overrides** — global `.env` sets `ORMAH_LLM_PROVIDER=claude_cli`, invalid outside #79, breaks collection):
  `ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none .venv/bin/python -m pytest tests/ -q --tb=no`
- **Suite gate** = the `FAILED` set is a subset of the recorded baseline (Task 1). Any NEW failure → stop, use superpowers:systematic-debugging; never push red.
- **Backup tag before any rewrite:** `backup/<slug>-pre-rebase-20260710`. Keep all tags until Task 7 + 1 week.
- **Push:** always `--force-with-lease`, never `--force`. Before force-pushing a PR, re-check the review-activity gate (Task 1 step 2) — #92 and #31 showed activity TODAY.
- **Absolute paths / subshells only** — never bare `cd`. Two-strikes: an identical failing command is diagnosed, not retried a third time.
- **Conflict authority:** upstream structure (whisper-waves refactors) wins the skeleton; PR logic is re-applied on top. Composition reference = old `local-main` (`refs/tmp/beta-local`). Sleep-cycle conflict patterns: ormah memory `d0e0e874` + `ormah-dev/HANDOFF-sleep-cycle-issues.md`.
- **STOP conditions:** r-spade review/comment dated ≥ 2026-07-09 on a PR you are about to force-push → ask André. A PR whose commits are ALL already upstream after rebase (`git cherry upstream/main <branch>` shows no `+`) → propose closing it instead. Upstream/main moves mid-work → re-fetch, re-baseline, continue.

## Known baseline facts (verified 2026-07-10 unless noted)

- Beta own commits: 259; upstream-only: 38 (handoff said 62 — 38 is the measured number today).
- Clean `upstream/main` suite: ~5 environmental failures (handoff, 07-09 — re-measure in Task 1).
- Beta `local-main` suite: ~9 pre-existing environmental failures (memory pr79 — re-measure in Task 1).
- Expected `to-pr79` hardening commits: ≈ `b395c1f`, `2d37ca9`, `ecfd65d`, `d0d71da`, `d39b2de` (confirm via manifest).

## Risks

- `mergeable: UNKNOWN` on all PRs (GitHub lazy) — resolves after pushes; re-check in Task 7, don't poll forever.
- #92/#31 activity today is unexplained — Task 1 investigates before any force-push.
- `make restart` internals unverified for the booted-out launchd case — Task 6 has a bootstrap fallback.
- Task 6 merges ~100 commits into the live runtime branch — mitigated by backup tag + stopped server + suite gate + checkpoint.

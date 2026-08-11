# Task 2 — Rebase the 5 small PRs (#57 → #60 → #68 → #38 → #31)

**Where:** `/Users/andre/Documents/GitHub/ormah-dev` only. No files created; deliverable = 5 rebased branches pushed, PRs commented.

Run the procedure below once per PR, IN THIS ORDER (session_watcher PRs first, resolved consistently):

| N | branch (B) | slug | note |
|---|---|---|---|
| 57 | `fix/exclude-subagent-transcripts` | pr57 | session_watcher domain |
| 60 | `fix/session-watcher-reconcile-upstream` | pr60 | session_watcher domain |
| 68 | `fix/session-watcher-catchup-off-bind-path` | pr68 | commits already ancestors of Beta local-main; rebase is for UPSTREAM mergeability |
| 38 | `fix/embedding-delta-backfill` | pr38 | check overlap with upstream #88 vec-reuse (merged) — parts may be upstreamed |
| 31 | `feat/bounded-forgetting` | pr31 | had activity 2026-07-10 → re-run the review gate (Task 1 Step 2) before force-push |

## Procedure (substitute N, B, slug; example values show #57)

- [ ] **Step 1: Checkout the PR branch**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && gh pr checkout 57 --repo r-spade/ormah )
```

Expected: local branch `fix/exclude-subagent-transcripts` checked out, tracking the PR head (push target auto-configured by gh).

- [ ] **Step 2: Backup tag**

```bash
git -C /Users/andre/Documents/GitHub/ormah-dev tag backup/pr57-pre-rebase-20260710
```

- [ ] **Step 3: Containment check (is the PR already upstreamed?)**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git cherry upstream/main HEAD | grep -c '^+' )
```

Expected: > 0 (commits still missing upstream). If 0 → STOP: this PR's content is fully upstream; propose to André closing the PR with a comment instead of rebasing.

- [ ] **Step 4: Rebase onto upstream/main**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git rebase upstream/main )
```

Conflicts: upstream structure (whisper-waves refactors, 0.13.3–0.13.5) wins the skeleton; re-apply the PR's logic on top. Consult `git -C /Users/andre/Documents/GitHub/ormah-dev show refs/tmp/beta-local:src/ormah/<file>` for how the feature composes on the Beta (fetch of `refs/tmp/beta-local` happens in Task 3 Step 1 — run it early if needed here). Resolve session_watcher conflicts the SAME way across #57/#60/#68. If a rebase goes wrong: `git rebase --abort` and re-plan; never resolve by guesswork.

- [ ] **Step 5: Suite gate (I4 — automated diff vs baseline, not eyeballed)**

```bash
P=/Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync
( cd /Users/andre/Documents/GitHub/ormah-dev && .venv/bin/pip install -q -e ".[dev]" \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | grep -E '^FAILED' | sort > /tmp/pr-fail.txt )
# NEW failures = in this run but not in baseline. Must be EMPTY.
comm -23 /tmp/pr-fail.txt <(sort $P/baseline-failures.txt) > /tmp/pr-new-fail.txt
if [ -s /tmp/pr-new-fail.txt ]; then echo "NEW FAILURES — DO NOT PUSH:"; cat /tmp/pr-new-fail.txt; else echo "GATE PASS: FAILED ⊆ baseline"; fi
```

Gate: `/tmp/pr-new-fail.txt` MUST be empty (FAILED set ⊆ `baseline-failures.txt`, Task 1 Step 3). Any line printed → superpowers:systematic-debugging; do NOT run Step 6.

- [ ] **Step 6: Push (force-with-lease) — after re-checking the review gate for this PR**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git push --force-with-lease )
```

Expected: accepted (lease holds). Rejected lease → someone moved the branch → STOP, fetch and diff before anything else.

- [ ] **Step 7: PR comment**

```bash
gh pr comment 57 --repo r-spade/ormah --body "Rebased onto main @ $(git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short upstream/main). Local suite green (same environmental failures as clean main)."
```

- [ ] **Step 8: Mergeable check (max 2 attempts, then move on)**

```bash
gh pr view 57 --repo r-spade/ormah --json mergeable --jq .mergeable
```

Expected: `MERGEABLE` (may stay `UNKNOWN` for minutes — re-check happens in Task 7; don't poll).

- [ ] **Repeat Steps 1–8 for #60, #68, #38, #31 with their branch/slug values from the table.**

# Task 1 — Preflight + Beta-delta inventory

**Files:**
- Create: `docs/superpowers/plans/2026-07-10-beta-upstream-sync/baseline-failures.txt` (upstream baseline)
- Create: `docs/superpowers/plans/2026-07-10-beta-upstream-sync/beta-baseline-failures.txt` (Beta baseline)
- Create: `docs/superpowers/plans/2026-07-10-beta-upstream-sync/delta-manifest.md` (commit classification)

No repo commits in this task (all outputs are gitignored plan artifacts).

- [ ] **Step 1: Fetch everything, confirm upstream tip**

```bash
git -C /Users/andre/Documents/GitHub/ormah-dev fetch upstream --prune
git -C /Users/andre/Documents/GitHub/ormah-dev fetch origin --prune
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch origin --prune
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch fork --prune
git -C /Users/andre/Documents/GitHub/ormah-dev log --oneline -1 upstream/main
```

Expected: `2e76b5b test(setup): isolate uninstall tests from real home`. If upstream moved, note the new tip and use it consistently everywhere this plan says `2e76b5b`.

- [ ] **Step 2: PR audit — head repo + review-activity gate**

```bash
for n in 31 38 57 60 68 79 92; do
  gh pr view $n --repo r-spade/ormah \
    --json number,headRefName,headRepositoryOwner,mergeable,reviews,comments,updatedAt \
    --jq '{n:.number, head:.headRefName, owner:.headRepositoryOwner.login, mergeable:.mergeable,
           reviews:[.reviews[]|{a:.author.login,at:.submittedAt}],
           lastComments:[.comments[-3:][]?|{a:.author.login,at:.createdAt}], updated:.updatedAt}'
done
```

Expected: heads owned by `AndreLFSMartins`, EXCEPT #92 on `r-spade`. GATE: any review/comment by r-spade dated ≥ 2026-07-09 on a PR → STOP and report to André before force-pushing THAT PR (#92 and #31 showed `updatedAt` 2026-07-10 — explain why before proceeding).

- [ ] **Step 3: Upstream test baseline (ormah-dev, detached upstream/main)**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git checkout --detach upstream/main \
  && .venv/bin/pip install -q -e ".[dev]" \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tee /dev/stderr \
     | grep -E '^FAILED' > /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync/baseline-failures.txt )
wc -l /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync/baseline-failures.txt
```

Expected: ~5 environmental failures (handoff 07-09), rest passed. This file is THE baseline for every suite gate in Tasks 2–5.

- [ ] **Step 4: Beta test baseline (Tools/ormah, local-main, no checkout)**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tee /dev/stderr \
     | grep -E '^FAILED' > docs/superpowers/plans/2026-07-10-beta-upstream-sync/beta-baseline-failures.txt )
```

Expected: ~9 pre-existing environmental failures (memory pr79). Baseline for Task 6's gate. Do NOT mask failures with extra env vars (memory: ormah-test-suite-env-leak).

- [ ] **Step 5: Fetch all PR branches into Beta clone as temp refs**

Adjust the remote if Step 2 showed a different owner for any head.

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch fork \
  'refs/heads/feat/bounded-forgetting:refs/tmp/pr31' \
  'refs/heads/fix/embedding-delta-backfill:refs/tmp/pr38' \
  'refs/heads/fix/exclude-subagent-transcripts:refs/tmp/pr57' \
  'refs/heads/fix/session-watcher-reconcile-upstream:refs/tmp/pr60' \
  'refs/heads/fix/session-watcher-catchup-off-bind-path:refs/tmp/pr68' \
  'refs/heads/feat/ingest-claude-cli-extraction:refs/tmp/pr79'
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch /Users/andre/Documents/GitHub/ormah-dev \
  'refs/heads/feat/87-pair-batching:refs/tmp/pr87' \
  'refs/heads/feat/90-maintenance-observability:refs/tmp/pr90'
```

Expected: 8 refs created; `git -C /Users/andre/Documents/GitHub/Tools/ormah for-each-ref refs/tmp` lists them (pr79 = `a15bcad`, pr87 = `8a2f474`, pr90 = `5c63ed2`).

- [ ] **Step 5b (I2): Re-verify #92 / feat/90 base against CURRENT upstream tip**

#92 and feat/87 were rebased 2026-07-09 over the then-current upstream (`bf5917d`); upstream has moved since. The assembly (Task 5) assumes ALL branches share the same pinned base — a stale base produces hidden cross-base conflicts or leaves #92 CONFLICTING after merge.

```bash
D=/Users/andre/Documents/GitHub/ormah-dev
git -C $D merge-base --is-ancestor upstream/main refs/tmp/pr90 && echo "pr90 base CURRENT" || echo "pr90 base STALE — re-rebase in Task 2"
git -C $D merge-base --is-ancestor upstream/main refs/tmp/pr87 && echo "pr87 base CURRENT" || echo "pr87 base STALE — re-rebase in Task 4"
```

Note: `--is-ancestor upstream/main <branch>` is true only when the branch already contains every current upstream commit (i.e. was rebased onto THIS tip). If STALE, the re-rebase is already scheduled — Task 4 re-rebases feat/87; add feat/90 to Task 2's loop under the same backup/force-with-lease/review-gate rules. Record the result in `delta-manifest.md` under `## base-status`.

- [ ] **Step 6: Build the Beta-only manifest (patch-id classification)**

```bash
B=/Users/andre/Documents/GitHub/Tools/ormah
P=$B/docs/superpowers/plans/2026-07-10-beta-upstream-sync
( cd $B \
  && for r in pr31 pr38 pr57 pr60 pr68 pr79 pr87 pr90; do
       git cherry refs/tmp/$r local-main | awk '$1=="-"{print $2}'; done | sort -u > $P/covered.txt \
  && git rev-list --no-merges origin/main..local-main | sort > $P/all-beta.txt \
  && comm -23 $P/all-beta.txt $P/covered.txt > $P/beta-only.txt \
  && wc -l $P/all-beta.txt $P/covered.txt $P/beta-only.txt )
( cd $B && while read s; do git show -s --format='%h %ad %s' --date=short $s; \
    git show --name-only --format= $s | sed 's/^/    /'; done < $P/beta-only.txt > $P/delta-manifest.md )
```

Expected: `beta-only.txt` ≪ 259 lines (most of the 259 are covered by PRs or are merge commits).

- [ ] **Step 7: Classify beta-only commits into two lists inside `delta-manifest.md`**

Edit `delta-manifest.md`, adding at the top:
- `## to-pr79` — commits touching the ingest domain (`session_watcher`, `ingest`, `cleanup`, `llm`/claude_cli, their tests), ordered OLDEST→NEWEST. Expected ≈ `b395c1f`, `2d37ca9`, `ecfd65d`, `d0d71da`, `d39b2de`.
- `## beta-keep` — everything else (UI/galaxy, council docs, local config). These must survive Task 6 untouched.

- [ ] **Step 8: CHECKPOINT — show André the counts + both lists; wait for approval before Task 2**

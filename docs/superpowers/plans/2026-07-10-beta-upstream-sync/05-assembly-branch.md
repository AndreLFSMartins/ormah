# Task 5 — Build the assembly branch (upstream + all rebased PRs)

**Where:** `/Users/andre/Documents/GitHub/ormah-dev`. Deliverable: branch `integration/beta-sync-20260710`, full suite green. This branch IS the future content of the Beta.

Precondition: Tasks 2–4 done (all branches rebased onto the same `upstream/main` tip — so every merge below shares that base; conflicts only where PRs touch the same files).

- [ ] **Step 1: Create the assembly branch**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git checkout -b integration/beta-sync-20260710 upstream/main )
```

- [ ] **Step 2: Merge the PR branches, one by one, IN THIS ORDER (#79 LAST — it owns the ingest domain and its resolutions win there)**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev \
  && git merge --no-ff feat/90-maintenance-observability \
  && git merge --no-ff feat/87-pair-batching \
  && git merge --no-ff fix/exclude-subagent-transcripts \
  && git merge --no-ff fix/session-watcher-reconcile-upstream \
  && git merge --no-ff fix/session-watcher-catchup-off-bind-path \
  && git merge --no-ff fix/embedding-delta-backfill \
  && git merge --no-ff feat/bounded-forgetting \
  && git merge --no-ff feat/ingest-claude-cli-extraction )
```

The chain stops at the first conflict — resolve it, `git commit`, then re-run the REMAINING merges only (never re-merge what already landed). Cross-PR conflicts are expected mainly in `session_watcher`, background jobs, `config.py`. Composition reference: the old Beta already runs ALL these features together — consult `git show refs/tmp/beta-local:src/ormah/<file>` (fetched in Task 3 Step 1) for intent; adapt to the new upstream skeleton, don't copy bytes.

- [ ] **Step 3: Full suite gate**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && .venv/bin/pip install -q -e ".[dev]" \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tee /dev/stderr | grep -E '^FAILED' \
     > /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync/assembly-failures.txt )
diff /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync/baseline-failures.txt \
     /Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync/assembly-failures.txt
```

Gate: `diff` empty or assembly ⊂ baseline. New failure → superpowers:systematic-debugging on the offending merge; never proceed red. (claude_cli tests: also run `-k "claude"` as in Task 3 Step 5.)

- [ ] **Step 4: Sanity — nothing PR-covered got lost**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && for b in feat/90-maintenance-observability feat/87-pair-batching \
    fix/exclude-subagent-transcripts fix/session-watcher-reconcile-upstream fix/session-watcher-catchup-off-bind-path \
    fix/embedding-delta-backfill feat/bounded-forgetting feat/ingest-claude-cli-extraction; do \
    echo "$b: $(git rev-list --count integration/beta-sync-20260710..$b) commits NOT in assembly"; done )
```

Expected: `0 commits NOT in assembly` for every branch.

- [ ] **Step 5 (C1): Content-preservation manifest — assembly vs the old live Beta**

The zero-loss claim must be proven at the CONTENT level, not just ancestry (council C1). The old `local-main` (`refs/tmp/beta-local`) already ran ALL these features composed together; the assembly rebuilt that composition on a new upstream skeleton. Verify no `beta-keep` change silently vanished:

```bash
D=/Users/andre/Documents/GitHub/ormah-dev
P=/Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync
# a) structural diff of the two trees, core paths — expect ONLY intended upstream-skeleton changes, no lost beta logic
git -C $D diff --stat refs/tmp/beta-local integration/beta-sync-20260710 -- \
  src/ormah/transcript src/ormah/engine src/ormah/background src/ormah/index src/ormah/config.py \
  src/ormah/ui_dist ui/ > $P/content-diff.txt
# b) per beta-keep commit: is its patch represented in the assembly? (patch-id, correct direction)
: > $P/beta-keep-audit.txt
while read s; do
  if git -C $D cherry integration/beta-sync-20260710 $s 2>/dev/null | grep -q '^-'; then st=PRESENT; else st=CHECK; fi
  echo "$st $(git -C $D show -s --format='%h %s' $s)" >> $P/beta-keep-audit.txt
done < <(awk '/^## beta-keep/{f=1;next}/^## /{f=0}f&&/^[0-9a-f]/{print $1}' $P/delta-manifest.md)
grep -c '^CHECK' $P/beta-keep-audit.txt | xargs echo "beta-keep commits needing manual confirmation:"
```

Gate: every `CHECK` line in `beta-keep-audit.txt` is manually explained — either the change IS in the assembly under a refactored shape (open the file and confirm), or it is a deliberate drop (upstream superseded it). ZERO unexplained drops before Task 6. A `beta-keep` commit whose logic is genuinely missing → cherry-pick it into the assembly and re-run Step 3.

- [ ] **Step 6: Record the assembly tip in `delta-manifest.md` under `## new-tips`**

```bash
git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short integration/beta-sync-20260710
```

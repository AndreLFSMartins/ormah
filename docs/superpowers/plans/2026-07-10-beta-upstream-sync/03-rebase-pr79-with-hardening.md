# Task 3 — Rebase #79 (claude_cli) + fold in the unpushed hardening

**Where:** `/Users/andre/Documents/GitHub/ormah-dev`. The heaviest task: ~50 commits, conflicts expected in `session_watcher.py`, `memory_engine.py`, `config.py`, background jobs, `tests/conftest.py`.

Precondition: Task 1 CHECKPOINT approved (the `to-pr79` list in `delta-manifest.md` is final).

- [ ] **Step 1: Make Beta local-main reachable in ormah-dev (composition reference + cherry-pick source)**

```bash
git -C /Users/andre/Documents/GitHub/ormah-dev fetch /Users/andre/Documents/GitHub/Tools/ormah \
  'refs/heads/local-main:refs/tmp/beta-local'
```

Expected: `refs/tmp/beta-local` created (Beta tip, `d39b2de` or newer).

- [ ] **Step 2: Checkout PR #79 + backup tag**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && gh pr checkout 79 --repo r-spade/ormah )
git -C /Users/andre/Documents/GitHub/ormah-dev tag backup/pr79-pre-rebase-20260710
git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short HEAD
```

Expected: HEAD = `a15bcad` (tip pushed 2026-07-07). If different → someone moved the branch → STOP, investigate.

- [ ] **Step 3: Rebase onto upstream/main**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git rebase upstream/main )
```

Conflict authority: upstream skeleton wins (whisper waves #74–#78, eval #80, vec-reuse #88, consolidator settings #89, sleep-cycle #92/#93/#94); claude_cli logic re-applied on top. Reference for intended final composition: `git show refs/tmp/beta-local:src/ormah/<file>` (the Beta already runs claude_cli integrated — but on the OLD upstream base, so copy intent, not bytes). Documented conflict patterns: ormah memory `d0e0e874`, `/Users/andre/Documents/GitHub/ormah-dev/HANDOFF-sleep-cycle-issues.md`. If the rebase derails (>2 confused conflicts in a row): `git rebase --abort`, report, re-plan — consider `git rebase --rebase-merges` or squashing parity commits first, WITH André.

- [ ] **Step 4 (I5): Dedup the `to-pr79` list against the rebased branch, THEN cherry-pick**

**Task 1 finding (2026-07-10, verified):** `to-pr79` is EMPTY. The 5 hardening commits (`b395c1f 2d37ca9 ecfd65d d0d71da d39b2de`, dated 2026-07-05) are ALREADY in #79 at tip `a15bcad` by patch-id (`git cherry refs/tmp/pr79 local-main` marks them `-`). The handoff's "unpushed hardening" premise was wrong. **So this step is a no-op** — the dedup filter below will print `SKIP` for all 5. Run it only as a confirmation; do NOT cherry-pick anything unless a commit unexpectedly shows `PICK`.

The rebase (Step 3) may otherwise have absorbed part of the hardening while resolving conflicts. Cherry-picking an already-present patch → empty commit or duplicated logic. So the filter stands:

```bash
D=/Users/andre/Documents/GitHub/ormah-dev
# git cherry <upstream> <head> marks with '-' the to-pr79 commits already present (by patch-id) on HEAD.
for s in b395c1f 2d37ca9 ecfd65d d0d71da d39b2de; do
  if git -C $D cherry HEAD $s 2>/dev/null | grep -q '^-'; then echo "SKIP $s (already on branch)"; \
  else echo "PICK $s"; fi
done
```

Cherry-pick ONLY the `PICK` commits, OLDEST→NEWEST, one at a time, inspecting each:

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git cherry-pick <sha> && git show --stat HEAD | head -20 )
```

If a cherry-pick reports "empty" (`The previous cherry-pick is now empty`) → `git cherry-pick --skip` (the patch was already there — do NOT `--allow-empty`). Use the EXACT list from `delta-manifest.md` (`## to-pr79`); the SHAs above are the expected set, not the authority. These commits are reachable via `refs/tmp/beta-local` (Step 1). Record which were SKIP vs PICK in `delta-manifest.md`.

- [ ] **Step 5: Suite gate**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && .venv/bin/pip install -q -e ".[dev]" \
  && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
     .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tail -3 )
```

Gate: FAILED ⊆ `baseline-failures.txt`. Additionally run the claude_cli-specific tests explicitly (they must exist and pass on this branch):

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
  .venv/bin/python -m pytest tests/ -q -k "claude" --tb=short 2>&1 | tail -5 )
```

Note (M1): the default run excludes `@pytest.mark.integration` (`pyproject.toml` addopts), so the real `claude -p` extraction test (`test_real_claude_cli_extraction_...`) does NOT run here — it runs once on the staged branch in Task 6 (between Steps 6 and 8, before `/council-pr`), with `claude` installed:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
  .venv/bin/python -m pytest tests/ -q -m integration -k claude --tb=short 2>&1 | tail -8 )
```

- [ ] **Step 6: Push (force-with-lease) + PR comment**

```bash
( cd /Users/andre/Documents/GitHub/ormah-dev && git push --force-with-lease )
gh pr comment 79 --repo r-spade/ormah --body "Rebased onto main @ $(git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short upstream/main) and folded in 5 hardening commits from local testing (council-review fixes H1/H2/I2/I3 + lint: extraction-failure capping, edge-indexing surfacing, transient-retry semantics, cleanup guards). Local suite green."
```

Adjust the count/description to the final `to-pr79` list. Note: fork branch `fix/ingest-stability-hardening` stays stale at `a15bcad` on purpose — cleanup in Task 7.

- [ ] **Step 7: Record the new tip**

```bash
git -C /Users/andre/Documents/GitHub/ormah-dev rev-parse --short HEAD
```

Write it into `delta-manifest.md` under `## new-tips` (needed by Task 5 and by the memory update in Task 7).

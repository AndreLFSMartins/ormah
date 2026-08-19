# Task 0: Worktree + known-red baseline

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:**
- Create: worktree at `/Users/andre/Documents/GitHub/Tools/ormah-wt-222`
- Create: `/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah/d2ee42ce-ab3c-43a2-a623-88137f26d08e/scratchpad/222-baseline.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: a clean working directory at `../ormah-wt-222` on branch `fix/222-retrievability-only-decay`, and a recorded baseline of pre-existing test failures.

- [ ] **Step 1: Cut the worktree from `upstream/main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/222-retrievability-only-decay ../ormah-wt-222 upstream/main
```

Expected: `Preparing worktree (new branch 'fix/222-retrievability-only-decay')` followed by `HEAD is now at <sha> ...`.

- [ ] **Step 2: Confirm the branch base is upstream, not local-main**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git rev-parse HEAD && git rev-parse upstream/main
```

Expected: the two SHAs are identical. If they differ, STOP — the branch was cut from the wrong base.

- [ ] **Step 3: Record the known-red baseline for the two suites this plan touches**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_decay_manager.py tests/test_background/test_importance_scorer.py -v \
  2>&1 | tee "/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah/d2ee42ce-ab3c-43a2-a623-88137f26d08e/scratchpad/222-baseline.txt" | tail -20
```

Expected: a pass/fail summary line. Record it. Every later "tests pass" claim in this plan means "same failures as this baseline, plus the new tests passing".

- [ ] **Step 4: No commit** — Task 0 produces no repo changes.

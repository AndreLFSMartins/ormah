# Task 1: Isolated worktree and the recorded red baseline

**Files:**
- Create: `../ormah-wt-220/` (git worktree, outside the repo directory)
- Create: `/private/tmp/claude-501/.../scratchpad/220-baseline.txt` (or any path outside the repo — this file is evidence, not a deliverable, and must not be committed)

**Interfaces:**
- Consumes: nothing.
- Produces: a working tree at `../ormah-wt-220` on branch `fix/220-confirmed-use`, and a recorded list of test IDs that already fail before any change.

This task has no TDD cycle — it establishes the measurement every later task compares against.

- [ ] **Step 1: Cut the worktree from `upstream/main`**

**Never** `git checkout` a contribution branch inside `Tools/ormah` — that directory is what the running Beta serves, and switching its branch swaps the live server's code under it.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/220-confirmed-use ../ormah-wt-220 upstream/main
```

Expected: `Preparing worktree (new branch 'fix/220-confirmed-use')` followed by `HEAD is now at <sha> ...`.

- [ ] **Step 2: Verify the branch base is `upstream/main` and carries nothing local**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git rev-parse --abbrev-ref HEAD && \
  git log --oneline upstream/main..HEAD | wc -l )
```

Expected: `fix/220-confirmed-use` then `0`. A non-zero count means the branch was cut from the wrong base — delete it and redo Step 1.

- [ ] **Step 3: Install the package into the worktree**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && pip install -e ".[dev]" )
```

Expected: ends with `Successfully installed ormah-...`.

- [ ] **Step 4: Record the baseline**

The default run excludes `integration`-marked tests (`addopts = -m 'not integration'`), which is the gate this plan uses throughout.

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | tail -40 > /tmp/220-baseline.txt ); cat /tmp/220-baseline.txt
```

Expected: a summary line such as `N failed, M passed in Xs`. Record the exact number of failures and the full list of failing test IDs.

- [ ] **Step 5: Extract the failing test IDs into a comparable list**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/220-baseline-ids.txt ); \
  wc -l /tmp/220-baseline-ids.txt; cat /tmp/220-baseline-ids.txt
```

Expected: a sorted list of `FAILED tests/...::test_name` lines. This file is the yardstick — every later task's "tests pass" step means *no test ID outside this list fails*.

- [ ] **Step 6: Report the baseline before proceeding**

State plainly: how many tests fail on clean `upstream/main`, and whether they match the `vec0 knn` failures PR #229 described. If the baseline is fully green, say so — that also contradicts #229's claim and is worth knowing.

Do not commit anything in this task. The worktree is set up; no source file has changed.

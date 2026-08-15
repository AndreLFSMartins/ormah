# Task 4: Verify and publish the branch

Read `00-overview.md` first — its Global Constraints apply here.

Runs only after Tasks 2 and 3 are both committed.

**Files:** none modified. This task verifies and publishes.

**Interfaces:**
- Consumes: `/tmp/setup-iso-baseline-ids.txt` from Task 1.

- [ ] **Step 1: Full suite, compared by ID against the Task 1 baseline**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso
PY="/Users/andre/Documents/GitHub/Tools/ormah-wt-220/.venv/bin/python"
export PYTHONPATH="$PWD/src"
$PY -m pytest tests/ -q > /tmp/setup-iso-final.txt 2>&1; echo "exit=$?"
grep -c 'Fatal Python error' /tmp/setup-iso-final.txt
grep '^FAILED' /tmp/setup-iso-final.txt | awk '{print $2}' | sort > /tmp/setup-iso-final-ids.txt
diff /tmp/setup-iso-baseline-ids.txt /tmp/setup-iso-final-ids.txt
```

Expected: exactly 6 `<` lines — the 3 `TestConfigureCodexMcp` plus the 3 `TestRemoveFastembedCache` IDs — and **zero `>` lines**.

Survivors should be the 5 group-A IDs (2 `test_config`, 1 `test_consolidator`, 2 `test_session_watcher`), plus `test_hippocampus` when it flakes.

Check the segfault count and exit code before reading the diff. Exit 139 or a non-zero `Fatal Python error` count means the suite aborted and the ID list is truncated — every missing ID would read as a fix. Re-run.

- [ ] **Step 2: Lint**

```bash
$PY -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 3: Prove no runtime file was touched**

```bash
git diff upstream/main --stat
git diff upstream/main --name-only | grep -v '^tests/' && echo "VIOLATION: non-test file changed" || echo "OK: tests/ only"
```

Expected: 3 files — `tests/conftest.py`, `tests/test_settings_isolation.py`, `tests/test_setup.py` — and `OK: tests/ only`.

- [ ] **Step 4: Confirm the commits are the expected two**

```bash
git log --oneline upstream/main..HEAD
```

Expected: exactly 2 commits, one per task, in order.

- [ ] **Step 5: Push to the fork**

```bash
git push fork fix/setup-test-env-isolation
```

`fork`, never `upstream`. The `.git/hooks/pre-push` hook rejects any push whose three-dot diff against `upstream/main` touches a protected path (`docs/`, `CLAUDE.md`, `graphify-out/`, …). If it fires here, a protected file got into a commit by mistake — fix the commit, never reach for `--no-verify`.

- [ ] **Step 6: Stop before opening the PR**

Do **not** run `gh pr create`. Report the result and hand the decision to André:

- there is no issue yet for groups B and C (the #106/#128 pair covers only group A), and whether to open one first is his call;
- the #220 cluster has an unresolved blocking question about draft PR #229 that may bear on PR sequencing;
- PR #128 touches `tests/conftest.py` too, so whichever lands second will need a trivial additive merge — worth saying in the PR body.

Report: the diff of failure IDs, the lint result, the file list, and the pushed SHA.

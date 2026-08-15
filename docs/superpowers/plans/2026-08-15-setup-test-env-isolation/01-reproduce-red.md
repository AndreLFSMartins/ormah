# Task 1: Reproduce the red on this branch

Read `00-overview.md` first — its Global Constraints apply here.

The red was measured on a different worktree (`ormah-wt-220`). An unreproduced failure is not a failure. Establish it here before anything changes.

**Files:** none modified. This task only measures.

**Interfaces:**
- Produces: `/tmp/setup-iso-baseline-ids.txt`, the sorted list of 12 failing test IDs. Tasks 2 and 4 diff against it.

- [ ] **Step 1: Confirm the interpreter resolves to this worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso
PY="/Users/andre/Documents/GitHub/Tools/ormah-wt-220/.venv/bin/python"
export PYTHONPATH="$PWD/src"
$PY -c "import ormah;print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-setup-iso/src/ormah/__init__.py`. Anything else — stop. The run would measure the Beta's code, and every later comparison would be meaningless.

- [ ] **Step 2: Run the 6 target tests and confirm all 6 fail**

```bash
$PY -m pytest tests/test_setup.py::TestConfigureCodexMcp tests/test_setup.py::TestRemoveFastembedCache -p no:randomly
```

Expected: `6 failed, 4 passed` (the two classes hold 5 tests each). Of the 6 failures: three read `AssertionError: Expected 'run' to not have been called. Called 1 times.`, three assert that a model cache dir still exists.

If fewer than 6 fail, the machine's `~/.config/ormah/.env` no longer carries the polluting keys, or codex was uninstalled — this plan's premise is gone. Stop and report; do not "fix" tests that already pass.

- [ ] **Step 3: Capture the full-suite baseline**

```bash
$PY -m pytest tests/ -q > /tmp/setup-iso-baseline.txt 2>&1; echo "exit=$?"
grep -c 'Fatal Python error' /tmp/setup-iso-baseline.txt
grep '^FAILED' /tmp/setup-iso-baseline.txt | awk '{print $2}' | sort > /tmp/setup-iso-baseline-ids.txt
wc -l < /tmp/setup-iso-baseline-ids.txt
cat /tmp/setup-iso-baseline-ids.txt
```

Expected: `exit=1` (**not** 139), `0` occurrences of `Fatal Python error`, and 12 IDs. The run takes roughly 7 minutes.

If exit is 139 or the segfault count is non-zero, the suite aborted early and the ID list is truncated — re-run before continuing. A short list here would make Task 4's diff show phantom fixes.

- [ ] **Step 4: Report the baseline**

No commit — nothing changed. Report the 12 IDs and confirm they are the expected 4 groups: 3 `TestConfigureCodexMcp`, 3 `TestRemoveFastembedCache`, 2 `test_config`, 1 `test_consolidator`, 2 `test_session_watcher`, 1 `test_hippocampus`.

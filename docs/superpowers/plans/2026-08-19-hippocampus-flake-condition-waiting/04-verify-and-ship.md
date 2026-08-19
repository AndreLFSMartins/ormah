### Task 4: Verify against the baseline and ship

**Files:**
- No new edits. Verification and publication only.

- [ ] **Step 1: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 2: Full suite, both gate halves**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
tail -25 out.txt
```

Expected: 12 failed (down from the measured baseline of 13), with `test_new_file_triggers_ingestion` absent from the list.

This count corroborates; it does not prove. The baseline itself contains this 50/50 flake, so one run could reach 12 by luck. **The proof is Task 2 Step 4 and Task 3 Step 4** — the converted tests passing under injected latency that breaks the old ones, and still failing when the behaviour is genuinely broken. Report the count and the injected-latency results together, never the count alone.

- [ ] **Step 3: Confirm the island stayed clean**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
git log --oneline upstream/main..HEAD
git diff --stat upstream/main...HEAD
```

Expected: exactly the two commits from Tasks 2 and 3, and one file changed — `tests/test_background/test_hippocampus.py`. Any `src/` path or any commit you did not write means STOP.

- [ ] **Step 4: Push to the fork**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
git push fork fix/hippocampus-test-flake
```

The pre-push hook is fail-closed on `PROTECTED` paths. A block here means something local-only rode along — read the hook's output rather than reaching for `--no-verify`.

- [ ] **Step 5: Open the PR through the council gate**

Run `/council-pr`. Base `r-spade:main`, head `fork:fix/hippocampus-test-flake`.

The PR body must carry the evidence that this is a test defect, not a product change: the two CI run IDs (32254168112 on the doc-only PR #247, 32160547915 on the unrelated PR #234), the 0.136s measured latency against the 0.5s budget, and the note that PR #234 — the head of the lifecycle landing order — is currently red on this flake.

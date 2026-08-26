### Task 3: Full-suite verification and island gates

**Files:** none modified — this task only runs commands and reports their output.

**Interfaces:**
- Consumes: the two commits from Tasks 1 and 2.
- Produces: the evidence quoted in the PR body.

- [ ] **Step 1: Prove which tree is being imported**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-259/`. Anything else — STOP; the numbers below would belong to another tree.

- [ ] **Step 2: Run the full suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > /tmp/full.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/full.txt
tail -20 /tmp/full.txt
```

Expected: `PYTEST_EXIT=0`. If anything fails, compare against a baseline run on `upstream/main` before assuming this change caused it.

- [ ] **Step 3: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 4: Prove the island is clean**

```bash
git log --oneline upstream/main..HEAD
git diff --stat upstream/main..HEAD
```

Expected: exactly the two commits from Tasks 1 and 2, and a diff touching only `src/ormah/engine/memory_engine.py`, `src/ormah/background/consolidator.py`, `tests/test_background/test_run_maintenance.py`, `tests/test_background/test_consolidator.py`. Any other path — especially anything under `docs/` — means the island was cut wrong; rebuild it before pushing.

- [ ] **Step 5: Check for collision with PR #260**

```bash
git log --oneline upstream/main..fix/192-consolidator-full-content -- src/ormah/background/consolidator.py
```

PR #260 (issue #192) also edits `consolidator.py`. Report whether its commits touch lines 38-40 or 77-80; if they do, note the likely merge conflict in the PR body rather than resolving it here.

- [ ] **Step 6: Push the branch to the fork**

```bash
git push fork fix/259-maintenance-full-content
```

Expected: the pre-push hook passes (no `PROTECTED` path in the three-dot diff). If it blocks, do NOT use `--no-verify` — read what it lists and remove that path from the branch.

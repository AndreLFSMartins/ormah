### Task 5: Full-suite verification and island gates

**Files:** none modified — this task only runs commands and reports their output.

**Interfaces:**
- Consumes: the four commits from Tasks 1-4.
- Produces: the evidence quoted in the PR body.

- [ ] **Step 1: Prove which tree is being imported**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-259/`. Anything else — STOP; every number below would
belong to another tree.

- [ ] **Step 2: Run the full suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > /tmp/full.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/full.txt
tail -20 /tmp/full.txt
```

Expected: `PYTEST_EXIT=0`. If anything fails, get a baseline on `upstream/main` before assuming
this change caused it:

```bash
git stash && git checkout upstream/main -- . 2>/dev/null
# ... baseline run ...
```

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

Expected: exactly the four commits from Tasks 1-4, touching only:
`src/ormah/config.py`, `src/ormah/engine/memory_engine.py`, `src/ormah/adapters/mcp_adapter.py`,
`src/ormah/background/consolidator.py`, `tests/test_background/test_run_maintenance.py`,
`tests/test_background/test_consolidator.py`, `tests/test_adapters/test_mcp_adapter.py`.

Any other path — especially anything under `docs/` — means the island was cut wrong or a
document leaked in; remove it before pushing.

- [ ] **Step 5: Check for collisions with the two open PRs on the same files**

```bash
# PR #260 (issue #192) — consolidator budget
git log --oneline upstream/main..fix/192-consolidator-full-content -- src/ormah/background/consolidator.py
# PR #263 (issue #261) — _NOT_CONSOLIDATED on the same SELECT lines Task 4 edits
git log --oneline upstream/main..fix/261-consolidated-nodes-are-terminal -- src/ormah/background/consolidator.py
git diff upstream/main fix/261-consolidated-nodes-are-terminal -- src/ormah/background/consolidator.py | head -40
```

Report whether either touches the lines Task 4 edited. Do **not** resolve anything here — note
the likely conflict in the PR body and leave the decision to André. A merge order matters:
if #263 lands first, the `type` column must sit alongside `_NOT_CONSOLIDATED`, not replace it.

- [ ] **Step 6: Push the branch to the fork**

```bash
git push fork fix/259-maintenance-full-content
```

Expected: the pre-push hook passes (no `PROTECTED` path in the three-dot diff). If it blocks, do
**not** use `--no-verify` — read the paths it lists and remove them from the branch.

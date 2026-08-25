> Plan overview: [00-overview.md](00-overview.md)

### Task 1: Clean island + import gate

**Files:** none in the repo (worktree + venv only).

**Interfaces:**
- Produces: worktree `/Users/andre/Documents/GitHub/Tools/ormah-wt-261` on branch `fix/261-consolidated-nodes-are-terminal`, with its own `.venv`; the absolute paths every later task uses.

- [ ] **Step 1: Cut the island from upstream/main**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/261-consolidated-nodes-are-terminal ../ormah-wt-261 upstream/main
```
Expected: `Preparing worktree (new branch 'fix/261-consolidated-nodes-are-terminal')`.

- [ ] **Step 2: Own venv + dev install**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-261
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -q -e ".[dev]"
```

- [ ] **Step 3: Import gate — prove which tree the interpreter imports**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```
Expected: a path containing `ormah-wt-261/`. Any other path → STOP, the island is not isolated.

- [ ] **Step 4: Baseline — the existing consolidator tests are green on upstream/main**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_background/test_consolidator.py -q > /tmp/t1.txt 2>&1; echo "PYTEST_EXIT=$?" >> /tmp/t1.txt; cat /tmp/t1.txt
```
Expected: all passed, `PYTEST_EXIT=0`. (First run downloads the fastembed model into the test cache; allow a few minutes.)

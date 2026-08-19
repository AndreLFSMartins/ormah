### Task 1: Build the clean island

**Files:**
- Create: worktree `../ormah-wt-hippocampus-flake` on branch `fix/hippocampus-test-flake`

**Interfaces:**
- Produces: an island whose `git log upstream/main..HEAD` is empty, and a venv whose `ormah.__file__` resolves inside the island.

- [ ] **Step 1: Cut the island from `upstream/main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/hippocampus-test-flake \
  /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake upstream/main
```

- [ ] **Step 2: Prove the island is clean**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
git log --oneline upstream/main..HEAD
```

Expected: no output. Any line here means the branch was cut from the wrong base — delete the worktree and redo Step 1.

- [ ] **Step 3: Give the island its own venv**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 4: Run the import gate**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-hippocampus-flake/`. If it points at `Tools/ormah/src`, STOP — the shell's `VIRTUAL_ENV` leaked and every test number from this island would describe `local-main` instead.

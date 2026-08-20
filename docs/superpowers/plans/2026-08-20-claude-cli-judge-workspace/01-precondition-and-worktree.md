### Task 0: Isolated worktree, own venv, green baseline

**Goal:** create a workspace where the adapter can be edited without the live daemon ever serving
the change, and prove the suite baseline before a single line changes.

**Files:**
- Create: worktree at `/Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws` on branch
  `feat/judge-workspace`
- Modify: none

**Interfaces:**
- Consumes: nothing.
- Produces: an absolute worktree path that every later task runs inside, and a verified baseline
  string `1 failed, 2628 passed, 12 deselected`.

---

- [ ] **Step 1: Confirm the live tree is on `local-main` and clean of source changes**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git rev-parse --abbrev-ref HEAD
git status --porcelain -- src tests
```

Expected: `local-main`, and the second command prints **nothing**. If it prints anything, stop —
someone has uncommitted source work and this plan would build on top of it.

- [ ] **Step 2: Create the worktree from the current `local-main` tip**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree add -b feat/judge-workspace \
  /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws local-main
```

Expected: `Preparing worktree (new branch 'feat/judge-workspace')` and a `HEAD is now at …` line.

The base is `local-main`, **not** `upstream/main`: this is Beta work that merges back into
`local-main`, matching how `34c41cd` landed. If the overview's "Landing" section was overridden and
this must become an upstream PR, do not run this step — rebuild per FORK-WORKFLOW Recipe A instead.

- [ ] **Step 3: Give the worktree its own venv and install the package**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]" 2>&1 | tail -3
```

Expected: a `Successfully installed ormah-…` line. FORK-WORKFLOW requires a per-island venv so a
test number from this worktree cannot silently come from the main tree's install.

- [ ] **Step 4: Run the import gate — prove the tests import THIS worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -c "import ormah, pathlib; print(pathlib.Path(ormah.__file__).resolve())"
```

Expected: a path under `/Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws/src/ormah/`.
If it points at `/Users/andre/Documents/GitHub/Tools/ormah/src/…`, the venv is not active for this
call — every test number after this would describe the wrong tree. Stop and fix before continuing.

- [ ] **Step 5: Re-derive the suite baseline inside the worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected, exactly: `1 failed, 2628 passed, 12 deselected` with the single failure being
`tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports`.

Note: **four** test files are untracked — `.git/info/exclude` lines 53–57 list them, and a fresh
worktree contains none of them. Together they are worth 13 tests, so without them the worktree
returns `1 failed, 2616 passed, 11 deselected` and every later number is incomparable. Copy all
four, not just the failing one:

```bash
for f in test_conflict_claims_investigation.py test_conflict_edge_rebuild_survival.py \
         test_proposal_claims_investigation.py test_whisper_claims_investigation.py; do
  cp "/Users/andre/Documents/GitHub/Tools/ormah/tests/$f" \
     "/Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws/tests/$f"
done
```

Verify by diff rather than by count — a count matching for the wrong reason is the failure mode:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && find tests -name '*.py' | sort ) > /tmp/live.txt
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws && find tests -name '*.py' | sort ) > /tmp/wt.txt
diff /tmp/live.txt /tmp/wt.txt && echo "same test files"
```

`.git/info/exclude` is shared with worktrees, so the copies do not dirty `git status`.
Re-run the suite after copying and confirm `1 failed, 2628 passed, 12 deselected`.

- [ ] **Step 6: Confirm ruff is clean in the worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 7: Confirm the live daemon is untouched and still serving**

```bash
launchctl list | grep com.ormah.server.dev
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://localhost:8787/
```

Expected: a line with exit status `0`, and `200`. This is the proof that the isolation strategy is
working — the daemon is alive and serving the old, known-good code while work proceeds elsewhere.

No commit in this task: nothing was changed.

# Task 5: Full verification and the PR

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:** none modified. This task only measures and publishes.

**Interfaces:**
- Consumes: tasks 1-4, all committed on `fix/123-reindex-preserves-incoming-edges`.
- Produces: a PR against `r-spade/ormah:main`.

## The rule this task exists to enforce

No claim of "it works" without the command and its output. A green suite from the wrong tree, or a
run whose exit code was swallowed by a pipe, is not evidence.

- [ ] **Step 1: Re-prove the import gate**

Commits since task 1 could have been made from the wrong directory.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-123/`. Anything else invalidates every number below.

- [ ] **Step 2: Full suite, clean HOME, exit code captured**

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)   # resolve the symlink — see the overview's constraints
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest tests/ -q > final.txt 2>&1
echo "PYTEST_EXIT=$?" >> final.txt
tail -6 final.txt
```

Expected: **`3 failed, 1955 passed, 1 deselected`** and `PYTEST_EXIT=1`.

**`PYTEST_EXIT=1` is the correct outcome here, and the three failures must be exactly the three
`tests/test_setup.py::TestConfigureCodexMcp` failures the pristine island already had** (see the
overview: they patch `ormah.setup.shutil.which` while `configure_codex_mcp` calls
`_find_binary("codex")`, so they fail on any machine with the `codex` CLI installed). Diff the
`FAILED` lines of `final.txt` against `baseline.txt` — the sets must be identical. A fourth
failure, or a different one, is a regression and blocks the PR.

The passed count is task 1's baseline (**1949**) **plus 6**:

| Task | New tests |
|---|---|
| 1 | 3 — `index_single` reindex, `touch_updated`, `incremental_update` |
| 3 | 2 — over-correction guard, canonicalisation guard |
| 4 | 1 — `D -> kept` survives the merge |

A different delta means tests were added or lost somewhere unplanned — account for every one
before continuing.

- [ ] **Step 3: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 4: Prove the island is clean**

```bash
git log --oneline upstream/main..HEAD
```

Expected: exactly the four commits from tasks 1-4 and nothing else. **Any commit you did not write
means the branch was cut from the wrong base** — rebuild the island rather than pushing.

- [ ] **Step 5: Prove no local-only path is in the diff**

```bash
git diff --name-only upstream/main...HEAD
```

Expected: exactly two paths — `src/ormah/index/builder.py`, `src/ormah/engine/memory_engine.py` —
plus `tests/test_index/test_builder.py`. Nothing under `docs/`, `graphify-out/`, `.council/`, and no
`CLAUDE.md` / `INSTRUCTIONS.md` / `SESSION_LOG.md` / `FORK-WORKFLOW.md`. The pre-push hook rejects
those fail-closed; seeing it here first is cheaper than being blocked at push.

Also confirm none of the four excluded investigation files rode along:

```bash
git diff --name-only upstream/main...HEAD | grep "claims_investigation\|edge_rebuild_survival" \
  && echo "STOP: an excluded investigation file is in the diff" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 6: Push to the fork**

Branches go to `fork`, never to `upstream` — you have no write access there.

```bash
git push fork fix/123-reindex-preserves-incoming-edges
```

If the pre-push hook blocks, do **not** reach for `--no-verify`: re-read step 5's output and remove
the offending path from the branch.

- [ ] **Step 7: Open the PR**

```bash
/council-pr
```

Base `r-spade:main`, head `fork:fix/123-reindex-preserves-incoming-edges`. If council refuses with
`origin-is-upstream — refusing to push to a repo you do not own`, that guard is council's, not
git's; step 6's explicit `git push fork` already bypassed it.

The PR body must carry, in this order:

1. `Fixes #123`.
2. The three destruction paths as a table — the explicit bidirectional `DELETE`, the `DELETE FROM
   nodes` cascade, and the `INSERT OR REPLACE` cascade — with the note that fixing only the first
   changes nothing.
3. The measured cascade table (sqlite 3.53.1): `INSERT OR REPLACE` 1 -> 0, `DELETE FROM nodes`
   1 -> 0, `INSERT ... ON CONFLICT(id) DO UPDATE` 1 -> 1.
4. The canonicalisation consequence from task 3, stated as a deliberate change: the surviving
   direction moves from "last reindexed wins" to "incumbent wins", i.e. deterministic instead of
   order-dependent. Reviewers will otherwise read it as a regression.
5. The four new tests and what each one catches — in particular that
   `test_removing_a_node_still_drops_its_incoming_edges` is what stops the naive over-correction.
6. Why no background job changes: `auto_linker` (`:235`), `conflict_detector` (`:167`) and
   `duplicate_merger` (`:193`) all skip a pair already recorded in `auto_link_checked`, and on
   this branch **nothing ever invalidates those rows** — which is why the loss was permanent:
   the edge died on reindex and the cached verdict kept every job from re-proposing it. Once
   nothing destroys the edges, nothing needs to recreate them. `consolidator` keys on
   `consolidation_checked` by signature and is unaffected. A reviewer will ask; answer it in the
   body rather than in a comment thread.

Do **not** cite the Beta's index numbers (32k edges, the 221.7 s rebuild) as evidence in the PR.
`~/.local/share/ormah/memory/index.db` is a product of `local-main`, which runs ~729 commits and
several unlanded PRs ahead of `upstream/main`. Those numbers describe a different tree.

- [ ] **Step 8: Report back, then stop**

Report: the `PYTEST_EXIT` line, the passed count **and the FAILED-line diff against
`baseline.txt`** from step 2, the ruff line, the commit list from step 4, and the PR URL.

Task 6 may run at any time after this — it writes no code and opens no PR. **Task 7 may not
start until this PR is merged into `r-spade/ormah:main`**, proved by
`git merge-base --is-ancestor`; a review is not a merge.

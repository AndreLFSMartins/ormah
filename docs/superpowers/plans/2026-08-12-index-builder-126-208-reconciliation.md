# #126/#208 Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `git merge upstream/main` in the sync worktree so that #126's pair-verdict
invalidation and #208's lock-order hoist both survive, unblocking the 4-commit upstream sync.

**Architecture:** The two changes are orthogonal and coexist. `file_hash` (#208) comes from
`FileStore`, which takes `L_mem`, so it is read *before* the write transaction. `prior` and
`prior_fingerprints` (#126) come from `SELECT`, already under `L_db`, so they stay *inside* it.
Final signatures: `_index_file(path, file_hash, prior=None)` and
`_index_file_nodes_only(path, file_hash, prior=None, prior_fingerprints=None)`.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode = auto`), sqlite3, ruff.

**Design:** `docs/superpowers/specs/2026-08-12-index-builder-126-208-reconciliation-design.md`

## Global Constraints

- **Work only in `/Users/andre/Documents/GitHub/Tools/ormah-wt-sync`.** Never `git checkout` inside
  `Tools/ormah` — that working tree is what the launchd Beta (`com.ormah.server.dev`) serves live.
- **Every `pytest` run needs `PYTHONPATH=$PWD/src`.** The worktree has no `.venv`, and the main
  repo's venv has ormah installed editable pointing at the main repo. Without it you test the wrong
  checkout and get a perfect green over untouched code.
- **Never pipe pytest into `tail`** — the exit status becomes `tail`'s. Capture `rc` first.
- Baseline suite is red: 7 pre-existing failures (`test_setup.py` ×6, `test_cloud_settings.py` ×1),
  identical by name on `local-main`. Zero *new* failures is the bar, not zero failures.
- `graphify-out/` regenerates constantly; `git stash push -u graphify-out/` before merging.

---

### Task 1: Merge and prove the deadlock test discriminates

Resolves both conflicts, then deliberately leaves `builder.py` **without** the #208 hoist to confirm
the threaded test fails as a *hang*. A test that fails with `AttributeError` is passing vacuously —
the exact false green from session 4. Nothing is committed in this task.

**Files:**
- Modify: `tests/test_index/test_builder.py` (2 conflict hunks)
- Modify: `src/ormah/index/builder.py` (4 conflict hunks, resolved to HEAD for now)

**Interfaces:**
- Produces: a merge in progress with conflicts resolved in the test file only.

- [ ] **Step 1: Prove the interpreter resolves to the worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-sync
export PY=/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python
PYTHONPATH=$PWD/src $PY -c "import ormah; print(ormah.__file__)"
```

Expected: a path under `ormah-wt-sync/src/`. If it prints `Tools/ormah`, STOP — everything after
this describes the wrong checkout.

- [ ] **Step 2: Stash graphify and start the merge**

```bash
git stash push -u graphify-out/
git merge upstream/main
```

Expected: `CONFLICT (content)` in exactly `src/ormah/index/builder.py` and
`tests/test_index/test_builder.py`. A third conflicting file means the merge base moved — stop and
re-plan.

- [ ] **Step 3: Resolve the test conflicts — keep both sides**

Both hunks are purely additive. HEAD contributes the #126 and abort-on-partial tests; upstream
contributes the lock-order tests. Replace the first conflict block with both imports:

```python
import threading

import pytest
```

For the second block, delete the `<<<<<<<`, `=======` and `>>>>>>>` markers and keep **both** bodies
in sequence.

- [ ] **Step 4: Update the three monkeypatches for the new signature**

`_index_file_nodes_only` gains a positional `file_hash`, so the HEAD monkeypatches no longer match.
In `test_full_rebuild_aborts_and_preserves_data_on_total_failure`:

```python
    def boom(_path, _file_hash, prior=None, prior_fingerprints=None):
        raise OSError(24, "Too many open files")
```

In **both** `test_full_rebuild_aborts_and_preserves_data_on_partial_failure` and
`test_full_rebuild_allow_partial_accepts_incomplete_pass`:

```python
    def flaky(path, file_hash, prior=None, prior_fingerprints=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(path, file_hash)
        raise OSError(24, "Too many open files")
```

`flaky_edges(path)` in `test_full_rebuild_edge_failure_does_not_abort_but_is_surfaced` is unchanged —
`_index_file_edges` keeps its signature.

- [ ] **Step 5: Resolve builder.py to HEAD only — the deliberate red state**

```bash
git checkout --ours src/ormah/index/builder.py
```

This is `integration/upstream-sync`'s version: #126 present, #208 absent, `file_hash` read inside the
transaction. This is the state the test must catch.

- [ ] **Step 6: Run the threaded test and confirm it hangs**

```bash
PYTHONPATH=$PWD/src $PY -m pytest \
  tests/test_index/test_builder.py::test_incremental_update_does_not_deadlock_against_a_memory_job \
  -v; echo "rc=$?"
```

Expected: FAIL on `assert not builder_thread.is_alive()` — the thread is still alive after the 10s
join, i.e. a hang. **If it fails with `AttributeError` or errors before the asserts, the test is
vacuous — stop and fix the test before going further.**

- [ ] **Step 7: Run the structural test and confirm it reports violations**

```bash
PYTHONPATH=$PWD/src $PY -m pytest \
  tests/test_index/test_builder.py::test_builder_never_takes_file_lock_inside_write_transaction \
  -v; echo "rc=$?"
```

Expected: FAIL with `FileStore lock acquired inside db.transaction(): [1]` (a non-empty list).

---

### Task 2: Apply the reconciliation

**Files:**
- Modify: `src/ormah/index/builder.py`

**Interfaces:**
- Consumes: the merge-in-progress from Task 1.
- Produces: `_index_file(path, file_hash, prior=None)` and
  `_index_file_nodes_only(path, file_hash, prior=None, prior_fingerprints=None)`.

- [ ] **Step 1: Hoist the hashes in `full_rebuild`**

Immediately after `paths = list(self.file_store.list_paths())` and before `count = 0`, insert:

```python
        # FileStore calls take L_mem. Complete them before the write transaction so no builder
        # path requests L_mem while holding L_db, the reverse of the order used by memory jobs.
        hashes: dict[Path, str] = {}
        for path in paths:
            try:
                hashes[path] = self.file_store.file_hash(path)
            except Exception as e:
                logger.warning("Failed to hash %s: %s", path, e)
```

Then, in the node-indexing loop, replace the body with:

```python
            for path in paths:
                if path not in hashes:
                    continue  # hashing failed above; already logged
                try:
                    self._index_file_nodes_only(path, hashes[path], prior_fingerprints=prior_fps)
                    count += 1
                except Exception as e:
                    logger.warning("Failed to index %s: %s", path, e)
```

Leave the `prior_fps` capture, the DELETEs, and the abort-on-partial guard untouched. A skipped path
means `count` misses an increment, which trips `count != len(paths)` and rolls the whole transaction
back — fail-closed with no extra code.

- [ ] **Step 2: Hoist the hashes in `incremental_update`**

Step 5 of Task 1 restored `builder.py` to HEAD in full, so nothing from upstream survives here —
apply the whole hoist. Replace from `indexed_ids = set(...)` down to the end of the per-path loop
with:

```python
        indexed_ids = set(indexed.keys())
        disk_ids: set[str] = set()

        # FileStore calls take L_mem. Complete them before the write transaction so no builder
        # path requests L_mem while holding L_db, the reverse of the order used by memory jobs.
        paths = list(self.file_store.list_paths())
        hashes: dict[Path, str] = {}
        for path in paths:
            try:
                hashes[path] = self.file_store.file_hash(path)
            except Exception as e:
                # A file removed between listing and hashing. This used to be swallowed by the
                # per-path try inside the loop; keep it non-fatal rather than killing the job.
                logger.warning("Failed to hash %s: %s", path, e)

        with self.db.transaction():
            for path in paths:
                if path not in hashes:
                    continue  # hashing failed above; already logged
                try:
                    file_hash = hashes[path]
                    node = parse_node(path.read_text(encoding="utf-8"))
                    disk_ids.add(node.id)

                    if node.id not in indexed:
                        self._index_file(path, file_hash)
                        added += 1
                    elif indexed[node.id] != file_hash:
                        prior = self._prior_row(node.id)  # read BEFORE the delete (#126)
                        self._remove_node(node.id, keep_vectors=True)
                        self._index_file(path, file_hash, prior)
                        updated += 1
                except Exception as e:
                    logger.warning("Failed to process %s: %s", path, e)
```

Leave the trailing `removed_ids` block and `return added, updated` untouched.

`paths` is wrapped in `list()` deliberately. Upstream binds the bare `list_paths()` return and
iterates it twice; that is safe only because `list_paths` returns `sorted(...)`. Were it ever made a
generator, the second loop would see nothing, `disk_ids` would stay empty, and
`removed_ids = indexed_ids - disk_ids` would delete every node in the index.

- [ ] **Step 3: Hoist the hash in `index_single` and widen the two helpers**

```python
    def index_single(self, path: Path) -> None:
        """Index or re-index a single file."""
        node = parse_node(path.read_text(encoding="utf-8"))
        file_hash = self.file_store.file_hash(path)
        with self.db.transaction():
            prior = self._prior_row(node.id)  # read BEFORE the delete (#126)
            # The vector is still valid exactly when the content fingerprint is: title and
            # content are what feed the embedding. Dropping it on an unchanged-content
            # reindex is permanent loss — nothing re-embeds it — and the node would sit
            # behind the watermark with no vector, invisible to the linker and unable to be
            # anyone else's semantic candidate. mark_outdated() (valid_until only) walks
            # exactly this path.
            unchanged = prior is not None and prior["content_fingerprint"] == content_fingerprint(
                node.title, node.content, node.type.value, node.space
            )
            self._remove_node(node.id, keep_vectors=unchanged)
            self._index_file(path, file_hash, prior)

    def _index_file(
        self, path: Path, file_hash: str, prior: sqlite3.Row | None = None
    ) -> None:
        """Index a single markdown file into the database (nodes + edges)."""
        self._index_file_nodes_only(path, file_hash, prior)
        self._index_file_edges(path)

    def _index_file_nodes_only(
        self,
        path: Path,
        file_hash: str,
        prior: sqlite3.Row | None = None,
        prior_fingerprints: dict[str, str | None] | None = None,
    ) -> None:
```

Keep `_index_file_nodes_only`'s existing docstring, then **delete the line
`file_hash = self.file_store.file_hash(path)` from its body** — eliminating that call is the entire
point of #208, and Task 1 Step 5 restored it along with the rest of HEAD. The body now starts:

```python
        text = path.read_text(encoding="utf-8")
        node = parse_node(text)
        conn = self.db.conn
```

Verify: `grep -n "file_store.file_hash" src/ormah/index/builder.py` must return exactly three hits —
one each in `full_rebuild`, `incremental_update` and `index_single`, all outside a transaction.

- [ ] **Step 4: Run both lock-order tests — expect PASS**

```bash
PYTHONPATH=$PWD/src $PY -m pytest tests/test_index/test_builder.py -v; echo "rc=$?"
```

Expected: `rc=0`, every test in the file passing — the #126 tests, the abort-on-partial tests and the
two lock-order tests together.

- [ ] **Step 5: Commit the merge**

```bash
git add src/ormah/index/builder.py tests/test_index/test_builder.py
git commit --no-edit
```

---

### Task 3: Verify against the baseline and restore the worktree

**Files:** none modified.

- [ ] **Step 1: Full suite, compared by name to the baseline**

```bash
PYTHONPATH=$PWD/src $PY -m pytest tests/ -q > /tmp/sync-suite.txt 2>&1; echo "rc=$?"
grep -E "^(FAILED|ERROR)" /tmp/sync-suite.txt
```

Expected: exactly the 7 baseline failures by name (`test_setup.py` ×6, `test_cloud_settings.py` ×1)
and nothing else. Any eighth name is a regression — do not proceed.

- [ ] **Step 2: Ruff**

```bash
$PY -m ruff check src/ tests/; echo "rc=$?"
```

Expected: no new error in `src/ormah/index/builder.py` or `tests/test_index/test_builder.py`.
Pre-existing errors elsewhere are the baseline (5 on the main repo).

- [ ] **Step 3: Restore graphify**

```bash
git stash pop
git status --short
```

Expected: only `graphify-out/` modified.

- [ ] **Step 4: Report, do not merge to local-main**

Integrating into `local-main` and restarting the Beta is a separate decision for André. Restarting is
`launchctl kickstart -k "gui/$(id -u)/com.ormah.server.dev"` — **not** `make restart`, which prints
"Server restarted", returns 0, and touches nothing.

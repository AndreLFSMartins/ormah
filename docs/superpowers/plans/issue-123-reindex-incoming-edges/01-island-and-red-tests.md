# Task 1: Island setup + the three failing tests

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Create: worktree `../ormah-wt-123` on branch `fix/123-reindex-preserves-incoming-edges`
- Modify: `tests/test_index/test_builder.py` — **append at the end of the file.** On the island
  this file is 152 lines and holds four tests (`test_full_rebuild`, `test_incremental_update`,
  `test_incremental_update_does_not_deadlock_against_a_memory_job`,
  `test_builder_never_takes_file_lock_inside_write_transaction`).
  `test_reindex_preserves_the_edge_reason` is a `local-main` test and **does not exist here** —
  do not look for it.

**Interfaces:**
- Consumes: nothing.
- Produces: three failing tests, `test_reindex_preserves_incoming_edges`,
  `test_touch_updated_does_not_drop_incoming_edges` and
  `test_incremental_update_preserves_incoming_edges`. Task 2 makes them pass; task 3 adds
  siblings that reuse the same `engine` fixture and the same `Connection(...)` setup idiom.

## Background the implementer needs

`edges.source_id` and `edges.target_id` are both `REFERENCES nodes(id) ON DELETE CASCADE`, and
`db.py:38` sets `PRAGMA foreign_keys=ON`. The connection `A -> B` is written in **A's** markdown
file. Reindexing B cannot read A's file, so it cannot rebuild that row — but today it deletes it
three separate ways. That is issue #123.

The `engine` fixture (`tests/conftest.py:118`) gives a started `MemoryEngine` with a temp memory
dir. `engine.builder.index_single` takes a `Path`, never an id; the only helper that maps a node
to its file is `engine.file_store._path_for(node)`, which takes the `MemoryNode`.

**`Connection` on the island has no `reason` field.** It carries only `target`, `edge` and
`weight` (`models/node.py:42-45`), and `_index_file_edges` (`builder.py:216-222`) inserts
`(source_id, target_id, edge_type, weight, created)` — the `edges.reason` column exists in the
schema but nothing ever populates it. Row identity is therefore pinned with `weight`, whose value
in each test is deliberately different from the 0.5 default. Do not add a `reason` field to make
the plan's original assertions work; that is a separate change, not part of #123.

**`_remove_node` has THREE call sites, not one** (council round 1, Cursor — verified against
`builder.py`):

| Line | Caller | Role |
|---|---|---|
| `builder.py:104` | `incremental_update` | **the production trigger** — the index updater every 60s |
| `builder.py:113` | `incremental_update` | genuine removal of a node gone from disk |
| `builder.py:122` | `index_single` | single-file reindex |

Steps 5 and 6 drive `index_single` only. A fix applied to `index_single` alone turns those two
green while `builder.py:104` keeps eating the graph every minute. Step 6b closes that hole: it is
the only one of the three tests that exercises the path production actually takes.

> **Steps 1-4 are already done** — the controller built and measured the island on 2026-08-21
> before dispatching this task. Verify each one with the command given (they are cheap); only
> rebuild if a check fails.

- [x] **Step 1: Build the island** — done, `../ormah-wt-123` on
  `fix/123-reindex-preserves-incoming-edges` at `9a7c524`. Verify with
  `git -C /Users/andre/Documents/GitHub/Tools/ormah-wt-123 log --oneline -1`.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/123-reindex-preserves-incoming-edges ../ormah-wt-123 upstream/main
```

- [x] **Step 2: Give the island its own venv** — done, `.venv` installed with `-e ".[dev]"`.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
```

- [x] **Step 3: Prove the import gate** — done. Printed
  `/Users/andre/Documents/GitHub/Tools/ormah-wt-123/src/ormah/__init__.py`. **Re-run it yourself
  before your first test run** — this is the one check worth repeating.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-123/`. If it does not, **STOP** — every number after this
point would describe the wrong tree. This has already produced one retracted test result.

- [x] **Step 4: Establish the island's baseline** — done, and it is **not** zero failures.

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)   # resolve the symlink — see Global Constraints
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest tests/ -q > baseline.txt 2>&1
echo "PYTEST_EXIT=$?" >> baseline.txt
tail -6 baseline.txt
```

Measured on the pristine island: **3 failed, 1949 passed, 1 deselected** in 48s, `PYTEST_EXIT=1`. All three are
`tests/test_setup.py::TestConfigureCodexMcp` — a pre-existing upstream test bug (they patch
`ormah.setup.shutil.which`, but `configure_codex_mcp` calls `_find_binary("codex")`), triggered
only on a machine with the `codex` CLI installed. Not a #123 regression, out of scope, and the
number task 5 compares against. `baseline.txt` is already on the island; do not commit it.

- [ ] **Step 5: Write the first failing test**

Append at the **end** of `tests/test_index/test_builder.py`, after
`test_builder_never_takes_file_lock_inside_write_transaction`:

```python
def test_reindex_preserves_incoming_edges(engine):
    """Reindexing a node must not destroy the edges that point AT it (#123).

    The connection A -> B lives in A's markdown file. Reindexing B has no access to that
    file and therefore no way to reconstruct the row, so it must not delete it.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, edge_type, weight FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before B is reindexed"

    # Reindex the TARGET through index_single. (The 60s updater takes a different call
    # site — that one is covered by test_incremental_update_preserves_incoming_edges.)
    node_b = engine.file_store.load(id_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = incoming()
    assert len(rows) == 1, "incoming edge destroyed by reindexing the target (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["edge_type"] == "supports"
    assert rows[0]["weight"] == 0.9, "weight 0.9 (not the 0.5 default) proves this is A's row"
```

- [ ] **Step 6: Write the second failing test**

Append immediately after it:

```python
def test_touch_updated_does_not_drop_incoming_edges(engine):
    """The real-world trigger: file_hash changes, content fingerprint does not (#123).

    `_invalidate_checked_pairs` only fires when the CONTENT fingerprint changes, but the
    reindex fires on any file_hash change. `touch_updated()` moves only `updated`, so the
    edge dies while the cached pair verdict survives — and auto_linker, conflict_detector
    and duplicate_merger all skip a pair already recorded in `auto_link_checked`. Nothing
    ever recreates the edge; the loss stands until a full rebuild.

    Self-feeding on the Beta: the auto-linker touches the node before saving, so creating
    any new link on a node destroys that node's own incoming edges. The same shape drives
    the importance scorer, which touched 5,216 nodes in one pass on 2026-08-21 and cost
    ~13,800 edges in 54 minutes.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.7)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming_count():
        return engine.db.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
        ).fetchone()[0]

    assert incoming_count() == 1, "sanity: the edge must exist before the touch"

    # The only delta is `updated`: file_hash changes, content fingerprint does not.
    node_b = engine.file_store.load(id_b)
    node_b.touch_updated()
    engine.file_store.save(node_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    assert incoming_count() == 1, "touch_updated() destroyed the incoming edge (#123)"
```

- [ ] **Step 6b: Write the third failing test — the production path**

Append immediately after it. `index_single` is NOT what runs in production; the index updater
calls `incremental_update`, which reaches `_remove_node` through a different line
(`builder.py:104`). Without this test, a fix confined to `index_single` looks complete and is not.

```python
def test_incremental_update_preserves_incoming_edges(engine):
    """The path production actually takes: the 60s index updater (#123).

    `index_single` is not the production trigger. `incremental_update` is — it walks the
    store, sees B's file_hash changed, and calls `_remove_node(id, keep_vectors=True)` at
    builder.py:104, a DIFFERENT call site from the one index_single uses (:122). A fix
    applied only to index_single leaves this path destroying incoming edges once a minute.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.6)
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, weight FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before the updater runs"

    # Change B's file so the updater sees a new file_hash, then run the REAL trigger.
    node_b = engine.file_store.load(id_b)
    node_b.touch_updated()
    engine.file_store.save(node_b)
    added, updated = engine.builder.incremental_update()

    assert updated == 1, "sanity: the updater must have seen B as changed"
    rows = incoming()
    assert len(rows) == 1, "incremental_update destroyed the incoming edge (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["weight"] == 0.6, "weight 0.6 (not the 0.5 default) proves this is A's row"
```

**Falsifier for this test** (run it in task 2 before declaring the fix done): revert *only* the
`incremental_update` call site to the old `_remove_node` and keep the `index_single` fix. This
test must go red on its own. If it stays green, it is not testing what it claims.

- [ ] **Step 7: Run all three and verify they FAIL**

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k "incoming_edges" > red.txt 2>&1
echo "PYTEST_EXIT=$?" >> red.txt
cat red.txt
```

Expected: **3 failed**, each on its post-reindex assertion (`assert len(rows) == 1`,
`assert incoming_count() == 1`, and `assert len(rows) == 1` again), never on a sanity assertion
above it. A failure on a *sanity* line — including `assert updated == 1` in the third test — means
the fixture is wrong, not the code. Fix the test before going further.

- [ ] **Step 8: Commit the red tests**

```bash
git add tests/test_index/test_builder.py
git commit -m "test(index): pin the incoming-edge invariant for #123 (red)

A row in \`edges\` is owned by the markdown of its source node. Reindexing the
TARGET has no access to that file and cannot rebuild the row, so it must not
delete it. All three tests fail today.

The second one is the trigger that makes the loss permanent: touch_updated()
changes file_hash without changing the content fingerprint, so the edge dies
while the cached pair verdict survives and no job ever recreates it.

The third one covers the path production actually takes. _remove_node has three
call sites; index_single (:122) is not the one the 60s index updater uses
(:104). A fix confined to index_single passes the first two and keeps losing
edges once a minute."
```

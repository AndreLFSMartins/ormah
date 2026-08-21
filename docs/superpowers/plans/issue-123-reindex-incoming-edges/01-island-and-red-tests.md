# Task 1: Island setup + the two failing tests

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Create: worktree `../ormah-wt-123` on branch `fix/123-reindex-preserves-incoming-edges`
- Modify: `tests/test_index/test_builder.py` (append after `test_reindex_preserves_the_edge_reason`,
  which currently ends at line 216)

**Interfaces:**
- Consumes: nothing.
- Produces: two failing tests, `test_reindex_preserves_incoming_edges` and
  `test_touch_updated_does_not_drop_incoming_edges`. Task 2 makes them pass; task 3 adds
  siblings that reuse the same `engine` fixture and the same `Connection(...)` setup idiom.

## Background the implementer needs

`edges.source_id` and `edges.target_id` are both `REFERENCES nodes(id) ON DELETE CASCADE`, and
`db.py:38` sets `PRAGMA foreign_keys=ON`. The connection `A -> B` is written in **A's** markdown
file. Reindexing B cannot read A's file, so it cannot rebuild that row — but today it deletes it
three separate ways. That is issue #123.

The `engine` fixture (`tests/conftest.py:172`) gives a started `MemoryEngine` with a temp memory
dir. `engine.builder.index_single` takes a `Path`, never an id; the only helper that maps a node
to its file is `engine.file_store._path_for(node)`, which takes the `MemoryNode`.

- [ ] **Step 1: Build the island**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/123-reindex-preserves-incoming-edges ../ormah-wt-123 upstream/main
```

- [ ] **Step 2: Give the island its own venv**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 3: Prove the import gate**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path containing `ormah-wt-123/`. If it does not, **STOP** — every number after this
point would describe the wrong tree. This has already produced one retracted test result.

- [ ] **Step 4: Establish the island's baseline**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > baseline.txt 2>&1
echo "PYTEST_EXIT=$?" >> baseline.txt
tail -3 baseline.txt
```

Expected: `PYTEST_EXIT=0` and no failures. Record the passed count — task 5 compares against it.
Do not commit `baseline.txt`.

- [ ] **Step 5: Write the first failing test**

Append to `tests/test_index/test_builder.py`, immediately after
`test_reindex_preserves_the_edge_reason`:

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
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="because X")
    )
    engine.file_store.save(node_a)
    engine.builder.index_single(engine.file_store._path_for(node_a))

    def incoming():
        return engine.db.conn.execute(
            "SELECT source_id, weight, reason FROM edges WHERE target_id = ?", (id_b,)
        ).fetchall()

    assert len(incoming()) == 1, "sanity: the edge must exist before B is reindexed"

    # Reindex the TARGET — what the index updater does after any change to B's own file.
    node_b = engine.file_store.load(id_b)
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = incoming()
    assert len(rows) == 1, "incoming edge destroyed by reindexing the target (#123)"
    assert rows[0]["source_id"] == id_a
    assert rows[0]["reason"] == "because X"
    assert rows[0]["weight"] == 0.9
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

    Self-feeding: `auto_linker._apply_edge` calls `touch_updated()` before saving
    (auto_linker.py:361), so creating any new link on a node destroys that node's own
    incoming edges.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.7, reason="mechanism")
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

- [ ] **Step 7: Run both and verify they FAIL**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k "incoming_edges" > red.txt 2>&1
echo "PYTEST_EXIT=$?" >> red.txt
cat red.txt
```

Expected: **2 failed**, both on the post-reindex assertion (`assert len(rows) == 1` and
`assert incoming_count() == 1`), not on the sanity assertion above it. A failure on the *sanity*
line means the fixture is wrong, not the code — fix the test before going further.

- [ ] **Step 8: Commit the red tests**

```bash
git add tests/test_index/test_builder.py
git commit -m "test(index): pin the incoming-edge invariant for #123 (red)

A row in \`edges\` is owned by the markdown of its source node. Reindexing the
TARGET has no access to that file and cannot rebuild the row, so it must not
delete it. Both tests fail today.

The second one is the trigger that makes the loss permanent: touch_updated()
changes file_hash without changing the content fingerprint, so the edge dies
while the cached pair verdict survives and no job ever recreates it."
```

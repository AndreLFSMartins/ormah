# Task 3: Guard tests — over-correction, and the canonicalisation consequence

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Modify: `tests/test_index/test_builder.py` (append after
  `test_touch_updated_does_not_drop_incoming_edges` from task 1)

**Interfaces:**
- Consumes: `_clear_derived` / `_remove_node` behaviour from task 2, exercised only through the
  public `index_single` and `incremental_update`.
- Produces: nothing later tasks depend on.

## What these two tests are for

Task 1's tests all pass under a naive "never delete incoming edges anywhere" change, which would be
wrong — it would leave orphan rows violating the foreign key. Test 1 here is the mirror that makes
the fix honest.

Test 2 pins a real behaviour change that a reviewer will otherwise read as a regression.
`_index_file_edges` skips inserting `A -> B` when the reverse `B -> A` already exists with the same
edge type (`builder.py:352`, "avoid bidirectional duplicates"). Before the fix, reindexing B
destroyed both directions, so B's own declaration was reinserted and the surviving direction was
whichever node was reindexed **last**. After the fix, the incumbent row survives and B's
declaration is skipped. Both choices are arbitrary; the fix makes the outcome deterministic instead
of a function of reindex order.

- [ ] **Step 1: Write the over-correction guard**

```python
def test_removing_a_node_still_drops_its_incoming_edges(engine):
    """When the file is really gone, incoming edges MUST die (the mirror of #123).

    `edges.target_id` is `REFERENCES nodes(id) ON DELETE CASCADE`: an edge pointing at a
    node that no longer exists is a foreign-key violation. A fix that simply never deleted
    incoming edges would pass every other test in this file and leave orphan rows behind.
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

    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
    ).fetchone()[0] == 1, "sanity: the edge must exist before B's file is deleted"

    # B genuinely leaves the store: its markdown file is gone from disk.
    path_b = engine.file_store._path_for(engine.file_store.load(id_b))
    path_b.unlink()
    engine.builder.incremental_update()

    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id = ?", (id_b,)
    ).fetchone()[0] == 0, "the removed node must be gone from the index"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id = ?", (id_b,)
    ).fetchone()[0] == 0, "orphan edge survived the removal of its target"
```

- [ ] **Step 2: Write the canonicalisation guard**

```python
def test_reindex_keeps_the_incumbent_canonical_direction(engine):
    """When both files declare the same link, the incumbent row wins — stably.

    `_index_file_edges` skips inserting A -> B when the reverse B -> A already exists with
    the same edge type (builder.py:352). Before #123 was fixed, reindexing B destroyed both
    directions, so B's own declaration was reinserted and the surviving direction was
    whichever node happened to be reindexed last. Now the incumbent survives and B's
    declaration is skipped: deterministic, and NOT a regression.
    """
    from ormah.models.node import Connection, CreateNodeRequest, EdgeType, NodeType

    id_a, _ = engine.remember(
        CreateNodeRequest(content="A fact.", type=NodeType.fact), agent_id="t")
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Another fact.", type=NodeType.fact), agent_id="t")

    node_a = engine.file_store.load(id_a)
    node_a.connections.append(
        Connection(target=id_b, edge=EdgeType.supports, weight=0.9, reason="from A")
    )
    engine.file_store.save(node_a)

    node_b = engine.file_store.load(id_b)
    node_b.connections.append(
        Connection(target=id_a, edge=EdgeType.supports, weight=0.2, reason="from B")
    )
    engine.file_store.save(node_b)

    # A is indexed first, so A -> B becomes the incumbent row.
    engine.builder.index_single(engine.file_store._path_for(node_a))
    engine.builder.index_single(engine.file_store._path_for(node_b))

    rows = engine.db.conn.execute(
        "SELECT source_id, reason FROM edges "
        "WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)",
        (id_a, id_b, id_b, id_a),
    ).fetchall()

    assert len(rows) == 1, "the pair must be represented by exactly one canonical row"
    assert rows[0]["source_id"] == id_a, "reindexing B flipped the canonical direction"
    assert rows[0]["reason"] == "from A", "the incumbent's metadata must be the one kept"
```

- [ ] **Step 3: Run both**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q \
  -k "still_drops_its_incoming or incumbent_canonical" > guards.txt 2>&1
echo "PYTEST_EXIT=$?" >> guards.txt
cat guards.txt
```

Expected: `2 passed`, `PYTEST_EXIT=0`.

If `test_removing_a_node_still_drops_its_incoming_edges` fails, task 2's `_clear_derived` was wired
into the `pending_removal` loop by mistake — `builder.py:176` must still call `_remove_node`.

If `test_reindex_keeps_the_incumbent_canonical_direction` fails with two rows, the reverse-edge
skip in `_index_file_edges` was altered; it must be left exactly as it was.

- [ ] **Step 4: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tests/test_index/test_builder.py
git commit -m "test(index): guard against over-correcting #123, and pin the canonical direction

The first test is the mirror of the fix: when a node's file is really gone, its
incoming edges must still die, or the foreign key is violated. Every other test
in this file passes under a naive 'never delete incoming edges' change; this one
does not.

The second pins a real consequence. The reverse-edge skip means the surviving
direction used to be whichever node was reindexed last; it is now the incumbent.
Deterministic rather than order-dependent — worth a test so it does not read as
a regression."
```

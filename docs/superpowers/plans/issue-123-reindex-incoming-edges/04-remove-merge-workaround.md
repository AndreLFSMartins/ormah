# Task 4: Remove the merge workaround that #123 forced

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — two blocks inside the merge path
- Test: `tests/test_engine/test_merge_undo.py` — **one new test first** (step 0), then the
  existing suite

**Interfaces:**
- Consumes: the non-destructive reindex from task 2. This task is only correct *after* it.
- Produces: nothing later tasks depend on.

## ⚠️ Line numbers differ on the island

This file diverges sharply between `local-main` and `upstream/main`: the block below sits at
`:2009` on the Beta and at `:1548` on `upstream/main`. **Locate both blocks by their comment text,
never by line number:**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
grep -n "Capture incoming edges for the kept node\|Restore incoming edges for the kept node" \
  src/ormah/engine/memory_engine.py
```

## Why this is the second, independent proof — and why it does not hold yet

`merge_nodes` calls `index_single(kept)` and then hand-restores the incoming edges that call
destroyed. With task 2 in place nothing destroys them, so both the capture and the restore are dead
code. If `test_merge_undo.py` stays green **without** them, the fix demonstrably works through a
code path that never mentions `_clear_derived`. If it goes red, task 2 is incomplete — fix task 2,
do not reinstate the workaround.

**The existing suite cannot deliver that proof.** Council round 1 caught this, both peers
independently, and it was verified against the code:

- `test_merge_remaps_edges` (`:84`) creates only `B -> C` — an edge *out of* the removed node —
  and asserts it was remapped to `A -> C`. `test_merge_skips_self_loop_edges` creates `B -> A`.
  Neither creates a **third party pointing at the kept node** (`D -> kept`).
- `original_edges` (`memory_engine.py`, `SELECT ... WHERE source_id = ? OR target_id = ?` with
  `removed.id` on both sides) captures only edges that touch the *removed* node. `D -> kept` was
  never in it — it existed solely because the `kept_incoming` block put it back.

So deleting the workaround **without** task 2 loses exactly `D -> kept` and the merge suite still
passes. Step 0 fixes that before anything is deleted.

- [ ] **Step 0: Add the test that gives step 5 its teeth**

Write this BEFORE deleting anything. With task 2 landed and the workaround still present it must
pass; after the deletion it must still pass. That is the whole proof.

The edge must carry a `reason`, and `ConnectRequest` has no `reason` field — only `Connection`
does. So `D -> kept` is built through **D's markdown**, the same idiom task 1 uses, not through
`engine.connect()`.

Append to `tests/test_engine/test_merge_undo.py`:

```python
def test_merge_preserves_third_party_incoming_edge(engine):
    """A third node pointing AT the kept node must survive the merge (#123).

    The merge path calls index_single(kept). Before #123 that destroyed every edge pointing
    at kept, and merge_nodes hand-restored them. This test is what makes deleting that
    workaround a proof rather than an assumption: no existing merge test creates D -> kept,
    so the suite could stay green while exactly this edge was lost.
    """
    from ormah.models.node import Connection

    id_a, _ = _create_node(engine, title="Kept", content="This node will be kept because longer")
    id_b, _ = _create_node(engine, title="Removed", content="Shorter content")
    id_d, _ = _create_node(engine, title="Third", content="An unrelated third node")

    # D -> kept, declared in D's own markdown so it carries a reason.
    node_d = engine.file_store.load(id_d)
    node_d.connections.append(
        Connection(target=id_a, edge=EdgeType.supports, weight=0.8, reason="third party")
    )
    engine.file_store.save(node_d)
    engine.builder.index_single(engine.file_store._path_for(node_d))

    def third_party():
        return engine.db.conn.execute(
            "SELECT source_id, target_id, edge_type, weight, reason, created FROM edges "
            "WHERE source_id = ? AND target_id = ?",
            (id_d, id_a),
        ).fetchall()

    before = third_party()
    assert len(before) == 1, "sanity: D -> kept must exist before the merge"

    engine.execute_merge(id_a, id_b)

    after = third_party()
    assert len(after) == 1, "merge destroyed the third-party incoming edge (#123)"
    assert after[0]["edge_type"] == "supports"
    assert after[0]["weight"] == 0.8
    assert after[0]["reason"] == "third party"
    assert after[0]["created"] == before[0]["created"], "the row was recreated, not preserved"
```

Run it with the workaround still in place:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_merge_undo.py -q -k third_party > merge-teeth.txt 2>&1
echo "PYTEST_EXIT=$?" >> merge-teeth.txt
cat merge-teeth.txt
```

Expected: `1 passed`. If it fails **here**, task 2 is incomplete — stop and fix task 2.

**Prove the test has teeth before trusting it.** Temporarily revert task 2's builder change (keep
the workaround deleted in a scratch commit, or stash task 2) and re-run: this test must go red. A
test that cannot fail proves nothing. Restore task 2 afterwards.

- [ ] **Step 1: Delete the capture block**

Remove these lines in full (the comment, the query, and the list comprehension), leaving the blank
line that separates it from the "Merge tags from removed into kept" block:

```python
        # Capture incoming edges for the kept node that aren't in its markdown.
        # index_single calls _remove_node which wipes ALL edges (including
        # incoming ones like self→kept "defines").  We need to restore these.
        kept_incoming = self.db.conn.execute(
            "SELECT source_id, target_id, edge_type, weight, created FROM edges "
            "WHERE target_id = ? AND source_id != ?",
            (kept.id, removed.id),
        ).fetchall()
        kept_incoming_edges = [dict(r) for r in kept_incoming]
```

- [ ] **Step 2: Delete the restore block**

Remove the whole `for edge in kept_incoming_edges:` loop together with its comment — from
`# Restore incoming edges for the kept node that were wiped by index_single` down to and including
the closing `)` of the `conn.execute("INSERT INTO edges ...")` inside it. Stop before the next
comment, `# Clean up auto-linker checked pairs:`.

- [ ] **Step 3: Correct the stale ordering comment**

Immediately above `for edge in original_edges:` the comment reads:

```python
            # Done AFTER index_single since that wipes and rebuilds edges for kept node.
```

Change it to:

```python
            # Done AFTER index_single since that rebuilds the kept node's OWN edges. Since #123
            # it no longer touches the edges pointing AT the kept node, so those need no rescue.
```

- [ ] **Step 4: Confirm both names are gone**

```bash
grep -n "kept_incoming" src/ormah/engine/memory_engine.py
```

Expected: no output. Any hit means one of the two blocks was only partly removed, and ruff will
flag the leftover as unused.

- [ ] **Step 5: Run the merge suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/test_merge_undo.py -q > merge.txt 2>&1
echo "PYTEST_EXIT=$?" >> merge.txt
cat merge.txt
```

Expected: `PYTEST_EXIT=0`, all passed — in particular `test_merge_remaps_edges` (`:84`) and the
new `test_merge_preserves_third_party_incoming_edge` from step 0. The new one is the load-bearing
assertion: the pre-existing tests would pass even if the fix were absent.

A failure here is a **task 2 defect, not a task 4 defect.** Do not restore the deleted blocks to go
green; diagnose why `index_single` is still destroying incoming edges.

- [ ] **Step 6: Run the whole engine suite**

The merge path touches undo, tags and checked-pair cleanup, so the narrow file is not enough:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_engine/ -q > engine.txt 2>&1
echo "PYTEST_EXIT=$?" >> engine.txt
tail -3 engine.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 7: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_merge_undo.py
git commit -m "refactor(engine): drop the merge workaround that #123 forced

merge_nodes captured the kept node's incoming edges before index_single and
restored them by hand afterwards, because index_single destroyed them. It no
longer does, so both blocks are dead code.

Removing them is the second, independent proof that the builder fix landed:
test_merge_undo.py stays green through a path that never mentions
_clear_derived.

That proof needed a test the suite did not have. No existing merge test builds
a third node pointing AT the kept node, and original_edges only captures edges
touching the REMOVED node — so D -> kept existed only because the deleted block
put it back, and the suite would have stayed green while losing it."
```

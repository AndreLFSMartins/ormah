# Task 4: Remove the merge workaround that #123 forced

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — two blocks inside the merge path
- Test: `tests/test_engine/test_merge_undo.py` (existing; no new tests)

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

## Why this is the second, independent proof

`merge_nodes` calls `index_single(kept)` and then hand-restores the incoming edges that call
destroyed. With task 2 in place nothing destroys them, so both the capture and the restore are dead
code. If `test_merge_undo.py` stays green **without** them, the fix demonstrably works through a
code path that never mentions `_clear_derived`. If it goes red, task 2 is incomplete — fix task 2,
do not reinstate the workaround.

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

Expected: `PYTEST_EXIT=0`, all passed — in particular `test_merge_remaps_edges` (`:84`).

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
git add src/ormah/engine/memory_engine.py
git commit -m "refactor(engine): drop the merge workaround that #123 forced

merge_nodes captured the kept node's incoming edges before index_single and
restored them by hand afterwards, because index_single destroyed them. It no
longer does, so both blocks are dead code.

Removing them is the second, independent proof that the builder fix landed:
test_merge_undo.py stays green through a path that never mentions
_clear_derived."
```

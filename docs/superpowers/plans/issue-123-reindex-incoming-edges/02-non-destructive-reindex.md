# Task 2: Make the reindex non-destructive

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Modify: `src/ormah/index/builder.py` — `_remove_node` (`:368-390`), its three call sites
  (`:161`, `:176`, `:200`), the `INSERT OR REPLACE INTO nodes` in `_index_file_nodes_only`
  (`:238-270`), and two stale comments (`:169-172`, `:204`)
- Test: `tests/test_index/test_builder.py` (the two tests from task 1)

**Interfaces:**
- Consumes: the two failing tests from task 1.
- Produces: `IndexBuilder._clear_derived(node_id: str, *, drop_vector: bool = False) -> None`
  and `IndexBuilder._remove_node(node_id: str) -> None` (the `keep_vectors` keyword is gone).
  Task 3's tests call neither directly — they go through `index_single` and `incremental_update`.

## Why both changes are in one task

Three independent statements destroy incoming edges on every reindex. Fixing fewer than all three
leaves the tests red:

| # | Location | Statement |
|---|---|---|
| 1 | `builder.py:381` | `DELETE FROM edges WHERE source_id = ? OR target_id = ?` |
| 2 | `builder.py:384` | `DELETE FROM nodes WHERE id = ?` — cascade |
| 3 | `builder.py:240` | `INSERT OR REPLACE INTO nodes` — REPLACE is DELETE+INSERT, cascade again |

Measured on sqlite 3.53.1 against an existing incoming edge: `INSERT OR REPLACE` 1 -> 0,
`DELETE FROM nodes` 1 -> 0, `INSERT ... ON CONFLICT(id) DO UPDATE` 1 -> **1**. The true upsert is
the only node write that leaves incoming edges standing.

- [ ] **Step 1: Replace `_remove_node` with the two split methods**

In `src/ormah/index/builder.py`, replace the whole of `_remove_node` (from
`def _remove_node(self, node_id: str, *, keep_vectors: bool = False) -> None:` through the
trailing `pass`) with:

```python
    def _clear_derived(self, node_id: str, *, drop_vector: bool = False) -> None:
        """Clear what this node's own markdown produces, keeping the node row itself (#123).

        This is the REINDEX path. The `nodes` row must survive: `edges.target_id` is
        `REFERENCES nodes(id) ON DELETE CASCADE`, so deleting it — or writing it with
        `INSERT OR REPLACE`, which is a delete underneath — destroys every edge pointing AT
        this node. Those rows are declared in OTHER nodes' markdown files, which a reindex of
        this node never reads and cannot reconstruct.

        Only `source_id` edges are cleared. A row in `edges` belongs to the markdown file of
        its source, and `_index_file_edges` reinserts exactly that set.

        Args:
            drop_vector: delete the `node_vectors` row so the embedding is regenerated. True
                only when the content fingerprint changed — dropping it on an unchanged-content
                reindex is permanent loss, because nothing re-embeds it.
        """
        conn = self.db.conn
        conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
        conn.execute("DELETE FROM edges WHERE source_id = ?", (node_id,))
        conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        if drop_vector:
            try:
                conn.execute("DELETE FROM node_vectors WHERE id = ?", (node_id,))
            except Exception:
                pass

    def _remove_node(self, node_id: str) -> None:
        """Remove a node and everything derived from it — the file is gone from disk.

        The `ON DELETE CASCADE` on `edges` is correct here: an edge pointing at a node that no
        longer exists is a foreign-key violation. For the REINDEX path, where the node survives,
        use `_clear_derived` instead (#123).
        """
        conn = self.db.conn
        conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
        conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)
        )
        conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        # Vector cleanup if table exists
        try:
            conn.execute("DELETE FROM node_vectors WHERE id = ?", (node_id,))
        except Exception:
            pass
```

- [ ] **Step 2: Point the two reindex call sites at `_clear_derived`**

`builder.py:161`, inside `incremental_update`'s update branch. Change:

```python
                        self._remove_node(node.id, keep_vectors=True)
```

to:

```python
                        self._clear_derived(node.id)
```

`builder.py:200`, inside `index_single`. Change:

```python
            self._remove_node(node.id, keep_vectors=unchanged)
```

to:

```python
            self._clear_derived(node.id, drop_vector=not unchanged)
```

Leave `builder.py:176` (`self._remove_node(node_id)` in the `pending_removal` loop) exactly as it
is — that is the genuine-removal path, and it now calls a method with no keyword at all.

- [ ] **Step 3: Convert the node write to a true upsert**

In `_index_file_nodes_only`, change the statement that begins `INSERT OR REPLACE INTO nodes`. Keep
the parameter tuple below it byte-for-byte unchanged — only the SQL string changes:

```python
        conn.execute(
            """
            INSERT INTO nodes
            (id, type, tier, source, space, space_locked, title, content, created, updated,
             last_accessed, access_count, confidence, importance,
             valid_until, stability, last_review, archived_at, file_path, file_hash,
             content_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                tier = excluded.tier,
                source = excluded.source,
                space = excluded.space,
                space_locked = excluded.space_locked,
                title = excluded.title,
                content = excluded.content,
                created = excluded.created,
                updated = excluded.updated,
                last_accessed = excluded.last_accessed,
                access_count = excluded.access_count,
                confidence = excluded.confidence,
                importance = excluded.importance,
                valid_until = excluded.valid_until,
                stability = excluded.stability,
                last_review = excluded.last_review,
                archived_at = excluded.archived_at,
                file_path = excluded.file_path,
                file_hash = excluded.file_hash,
                content_fingerprint = excluded.content_fingerprint
            """,
```

`nodes` has 22 columns: the 21 written here plus `seq`, which the block immediately below assigns
with its own `UPDATE`. `id` is the conflict key, so 20 columns are updated. There is no column
outside that set, so nothing that `REPLACE` used to reset to its default is now silently preserved.

- [ ] **Step 4: Fix the two comments that now describe the wrong method**

`builder.py:169-172`, in the `pending_removal` guard. Replace the sentence
`_remove_node here runs with keep_vectors=False, so a node dropped on a transient read error loses
its vector permanently` with:

```python
            # Only a COMPLETE scan proves absence. _remove_node here deletes the node row and its
            # vector, so a node dropped on a transient read error loses its vector permanently —
            # nothing re-embeds it — and _remove_node does not clear the checked-pair tables, so
            # the node would come back as new (prior=None) carrying stale verdicts, defeating #126.
```

`builder.py:204`, the `_prior_row` docstring first line. Change
`read BEFORE _remove_node deletes the row` to:

```python
        """The stored fingerprint + seq, read BEFORE the upsert overwrites the row.
```

- [ ] **Step 5: Run the two tests and verify they PASS**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k "incoming_edges" > green.txt 2>&1
echo "PYTEST_EXIT=$?" >> green.txt
cat green.txt
```

Expected: `2 passed`, `PYTEST_EXIT=0`.

- [ ] **Step 6: Run the whole builder + index suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_index/ -q > index.txt 2>&1
echo "PYTEST_EXIT=$?" >> index.txt
tail -3 index.txt
```

Expected: `PYTEST_EXIT=0`. `test_reindex_preserves_the_edge_reason` (`:190`) must still pass — it
covers the outgoing direction and is the sibling of the new tests.

- [ ] **Step 7: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/ormah/index/builder.py
git commit -m "fix(index): reindexing a node no longer destroys its incoming edges (#123)

A row in \`edges\` is owned by the markdown file of its source node. The reindex
path destroyed the incoming ones three separate ways: the explicit bidirectional
DELETE, the DELETE of the \`nodes\` row, and INSERT OR REPLACE on \`nodes\` — the
last two both firing ON DELETE CASCADE, the third even with the first two fixed,
because REPLACE is a delete underneath.

Split \`_remove_node\` into \`_clear_derived\` (reindex: leaves the node row alone
and clears only \`source_id\` edges) and \`_remove_node\` (genuine removal: full
delete, where the cascade is correct), and make the node write a true upsert.

\`keep_vectors\` inverts into \`drop_vector\` rather than disappearing: index_single
legitimately drops the vector when the content fingerprint changed, so the
embedding is regenerated."
```

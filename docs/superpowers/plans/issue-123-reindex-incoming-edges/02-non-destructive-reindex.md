# Task 2: Make the reindex non-destructive

Read `00-overview.md` first — its Global Constraints apply to every step here.

**Files:**
- Modify: `src/ormah/index/builder.py` — `_remove_node` (`:224-247`), two of its three call sites
  (`:104` and `:122`; `:113` stays), and the `INSERT OR REPLACE INTO nodes` in
  `_index_file_nodes_only` (`:135-155`)
- **Do not touch** `src/ormah/engine/memory_engine.py:1137` or `:1573`. Both call
  `self.builder._remove_node(<id>)` with no keyword, both are genuine removals (a deleted node and
  a merged-away node), and both stay correct once the `keep_vectors` keyword is gone.
- Test: `tests/test_index/test_builder.py` (the three tests from task 1)

**Interfaces:**
- Consumes: the three failing tests from task 1.
- Produces: `IndexBuilder._clear_derived(node_id: str, *, drop_vector: bool = False) -> None`
  and `IndexBuilder._remove_node(node_id: str) -> None` (the `keep_vectors` keyword is gone).
  Nothing outside `builder.py` passes `keep_vectors` — verified by
  `grep -rn keep_vectors src/ tests/` on the island.
  Task 3's tests call neither directly — they go through `index_single` and `incremental_update`.

## Why both changes are in one task

Three independent statements destroy incoming edges on every reindex. Fixing fewer than all three
leaves the tests red:

| # | Location | Statement |
|---|---|---|
| 1 | `builder.py:236-238` | `DELETE FROM edges WHERE source_id = ? OR target_id = ?` |
| 2 | `builder.py:240` | `DELETE FROM nodes WHERE id = ?` — cascade |
| 3 | `builder.py:135` | `INSERT OR REPLACE INTO nodes` — REPLACE is DELETE+INSERT, cascade again |

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
            drop_vector: delete the `node_vectors` row so the embedding is regenerated. The
                two callers keep exactly today's behaviour: `incremental_update` leaves it
                False (it used `keep_vectors=True`, and it never re-embeds — dropping the
                vector there is permanent loss), and `index_single` passes True (it used the
                `keep_vectors=False` default, and its callers re-embed afterwards).
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

Both, not one. `:104` is the production path (the 60 s index updater) and `:122` is the
single-file reindex; `:113` stays on the genuine-removal `_remove_node`. Changing only `:122`
is the failure mode task 1's third test exists to catch.

`builder.py:104`, inside `incremental_update`'s update branch. Change:

```python
                        self._remove_node(node.id, keep_vectors=True)
```

to:

```python
                        self._clear_derived(node.id)
```

`builder.py:122`, inside `index_single`. Change:

```python
            self._remove_node(node.id)
```

to:

```python
            self._clear_derived(node.id, drop_vector=True)
```

`drop_vector=True` is not an arbitrary choice: `index_single` reached `_remove_node` through the
`keep_vectors=False` default, so it has always dropped the vector. Passing True keeps that
behaviour byte-for-byte. (On `local-main` this call site carries a `keep_vectors=unchanged`
argument driven by a content fingerprint; that machinery does not exist on `upstream/main`, so
there is no `unchanged` in scope here. Do not invent one.)

Leave `builder.py:113` (`self._remove_node(node_id)`, in the loop over `removed_ids`) exactly as
it is — that is the genuine-removal path, and it now calls a method with no keyword at all.

- [ ] **Step 3: Convert the node write to a true upsert**

In `_index_file_nodes_only` (`builder.py:130`), change the statement that begins
`INSERT OR REPLACE INTO nodes`. Keep the parameter tuple below it byte-for-byte unchanged — only
the SQL string changes:

```python
        conn.execute(
            """
            INSERT INTO nodes
            (id, type, tier, source, space, title, content, created, updated,
             last_accessed, access_count, confidence, importance,
             valid_until, stability, last_review, file_path, file_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                tier = excluded.tier,
                source = excluded.source,
                space = excluded.space,
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
                file_path = excluded.file_path,
                file_hash = excluded.file_hash
            """,
```

`nodes` has 19 columns (`schema.sql:3-23`): the 18 written here plus `seq`, which the block
immediately below assigns with its own `UPDATE`. `id` is the conflict key, so 17 columns are
updated. There is no column outside that set, so nothing that `REPLACE` used to reset to its
default is now silently preserved. `seq` is the one column whose pre-write value differs between
the two forms — `REPLACE` reset it to 0, the upsert keeps the old value — and it does not matter,
because the `UPDATE nodes SET seq = ?` two statements later overwrites it either way.

- [x] **Step 4: DROPPED on re-anchor — nothing to fix here**

This step told you to rewrite two comments citing `_prior_row` and a `pending_removal` guard.
Neither symbol exists on `upstream/main` (`grep -n "_prior_row\|pending_removal\|content_fingerprint"
src/ormah/index/builder.py` returns nothing on the island) — they are `local-main` code. Skip it.
The one comment that does mention the old behaviour is `_remove_node`'s own docstring, and step 1
replaces that wholesale.

- [ ] **Step 5: Run the three tests and verify they PASS**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-123
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest \
  tests/test_index/test_builder.py -q -k "incoming_edges" > green.txt 2>&1
echo "PYTEST_EXIT=$?" >> green.txt
cat green.txt
```

Expected: `3 passed`, `PYTEST_EXIT=0`.

**Then prove each test has teeth, one call site at a time.** All three go green together, which
hides whether each is actually pinning its own path. Revert `builder.py:104` alone to the old
`_remove_node(node.id, keep_vectors=True)` and re-run: only
`test_incremental_update_preserves_incoming_edges` may go red. Restore it, revert `:122` alone
to `_remove_node(node.id)`: only the other two may go red. A test that stays green through the revert of the line it claims to
cover is not testing that line. This is why task 1 has three tests and not two — the original pair
went through `index_single` only, and `:104` is what runs in production every 60 s.

- [ ] **Step 6: Run the whole builder + index suite**

```bash
H=$(mktemp -d); H=$(cd "$H" && pwd -P)
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest \
  tests/test_index/ -q > index.txt 2>&1
echo "PYTEST_EXIT=$?" >> index.txt
tail -3 index.txt
```

Expected: `PYTEST_EXIT=0`. `test_full_rebuild` and `test_incremental_update` must still pass —
they are the existing coverage of the paths this task changes.

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

\`keep_vectors\` inverts into \`drop_vector\` rather than disappearing, with both
call sites keeping today's behaviour exactly: incremental_update never
re-embeds, so it keeps the vector; index_single already dropped it via the
old default, and its callers re-embed afterwards."
```

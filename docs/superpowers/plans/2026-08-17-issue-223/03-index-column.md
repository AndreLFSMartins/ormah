# Task 3: `superseded_by` in schema, migration and reindex

**Files:**
- Modify: `src/ormah/index/schema.sql` (table `nodes`)
- Modify: `src/ormah/index/db.py` (symbol: `Database._migrate`, list `enrichment_migrations`)
- Modify: `src/ormah/index/builder.py` (symbol: `IndexBuilder._index_file_nodes_only`)
- Test: `tests/test_index/test_migration_superseded.py` (create)
- Test: `tests/test_index/test_builder.py`

**Interfaces:**
- Consumes: `MemoryNode.superseded_by` from Task 2.
- Produces: a `superseded_by TEXT` column on `nodes` that survives a reindex, read by Task 6's test and by #209 later.

**The builder change is the load-bearing half.** `_index_file_nodes_only` runs `INSERT OR REPLACE INTO nodes` with an explicit column list. In SQLite `REPLACE` is DELETE + INSERT, so a column absent from that list is recreated at its `DEFAULT` — `NULL`. Task 6's consolidator marks the node and then calls `update_node(tier=archival)`, which calls `builder.index_single`; without this change the marker is wiped from the index within the same loop iteration that wrote it.

---

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_index/test_migration_superseded.py`:

```python
"""Tests for the nodes.superseded_by column migration (#223)."""

from __future__ import annotations


def test_migration_adds_superseded_by_and_leaves_existing_rows_null(tmp_path):
    from ormah.index.db import Database

    db = Database(tmp_path / "legacy.db")
    try:
        with db.transaction() as conn:
            conn.execute(
                "CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, tier TEXT, space TEXT, "
                "title TEXT, content TEXT, created TEXT NOT NULL)"
            )
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "INSERT INTO nodes (id, type, tier, space, title, content, created) "
                "VALUES ('old', 'fact', 'working', NULL, 't', 'c', '2020-01-01')"
            )

        db.init_schema()  # must not raise

        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        assert "superseded_by" in cols
        row = db.conn.execute(
            "SELECT superseded_by FROM nodes WHERE id = 'old'"
        ).fetchone()
        assert row[0] is None
    finally:
        db.close()


def test_migration_is_idempotent(tmp_path):
    """PRAGMA-guarded: running init_schema twice must not raise 'duplicate column'."""
    from ormah.index.db import Database

    db = Database(tmp_path / "twice.db")
    try:
        db.init_schema()
        db.init_schema()
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        assert cols.count("superseded_by") == 1
    finally:
        db.close()
```

Match `tests/test_index/test_migration_seq.py` for the `Database` lifecycle — if it closes the db differently from `db.close()`, copy that file's `finally` block verbatim.

- [ ] **Step 2: Write the failing reindex-survival test**

Append to `tests/test_index/test_builder.py`:

```python
def test_reindex_preserves_superseded_by(engine):
    """INSERT OR REPLACE drops omitted columns to their DEFAULT — the marker must be
    in the column list, or the consolidator's own update_node wipes it (#223)."""
    from ormah.models.node import CreateNodeRequest

    node_id, _ = engine.remember(CreateNodeRequest(content="a source about to be superseded"))

    node = engine.file_store.load(node_id)
    node.superseded_by = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    engine.builder.index_single(engine.file_store.save(node))

    row = engine.db.conn.execute(
        "SELECT superseded_by FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["superseded_by"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

- [ ] **Step 3: Run both to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_index/test_migration_superseded.py tests/test_index/test_builder.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. `assert 'superseded_by' in cols` fails, and the builder test fails with `sqlite3.OperationalError: no such column: superseded_by`.

- [ ] **Step 4: Add the column to the fresh-store schema**

In `src/ormah/index/schema.sql`, inside `CREATE TABLE IF NOT EXISTS nodes`, add immediately after `last_review TEXT,`:

```sql
    superseded_by TEXT,
```

- [ ] **Step 5: Add the migration entry**

In `src/ormah/index/db.py`, inside `_migrate`, append one pair to `enrichment_migrations`:

```python
                ("last_review", "ALTER TABLE nodes ADD COLUMN last_review TEXT"),
                ("superseded_by", "ALTER TABLE nodes ADD COLUMN superseded_by TEXT"),
```

The surrounding `for col_name, ddl in enrichment_migrations:` loop is already `PRAGMA table_info`-guarded, so this is idempotent and existing rows stay `NULL`. Add nothing else.

- [ ] **Step 6: Carry the column through reindex**

In `src/ormah/index/builder.py`, in `_index_file_nodes_only`, add `superseded_by` to the column list, add one `?` to the VALUES tuple, and add the value in the same position:

```python
        conn.execute(
            """
            INSERT OR REPLACE INTO nodes
            (id, type, tier, source, space, title, content, created, updated,
             last_accessed, access_count, confidence, importance,
             valid_until, stability, last_review, superseded_by, file_path, file_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.type.value,
                node.tier.value,
                node.source,
                node.space,
                node.title,
                node.content,
                node.created.isoformat(),
                node.updated.isoformat(),
                node.last_accessed.isoformat(),
                node.access_count,
                node.confidence,
                node.importance,
                node.valid_until.isoformat() if node.valid_until else None,
                node.stability,
                node.last_review.isoformat() if node.last_review else None,
                node.superseded_by,
                str(path),
                file_hash,
            ),
        )
```

Count them before running: 19 column names, 19 `?`, 19 values. A mismatch raises `sqlite3.ProgrammingError`.

- [ ] **Step 7: Run both to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_index/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 8: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/ormah/index/schema.sql src/ormah/index/db.py src/ormah/index/builder.py \
        tests/test_index/test_migration_superseded.py tests/test_index/test_builder.py
git commit -m "feat(index): superseded_by column, migration, and reindex survival (#223)"
git show --stat HEAD
```

Expected: exactly five files.

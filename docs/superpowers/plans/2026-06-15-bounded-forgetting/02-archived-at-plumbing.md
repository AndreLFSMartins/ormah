# Task 02: `archived_at` plumbing

`archived_at` is a node timestamp: when a node entered the `archival` tier. The SQLite
index is *derived* from the markdown files and rebuilt on restore, so the value must live in
the frontmatter (source of truth) and be mirrored into a `nodes.archived_at` column.

**Files:**
- Modify: `src/ormah/models/node.py` (add field)
- Modify: `src/ormah/store/markdown.py` (serialize/parse)
- Modify: `src/ormah/index/schema.sql` (column for fresh DBs)
- Modify: `src/ormah/index/db.py` (migration for legacy DBs)
- Modify: `src/ormah/index/builder.py` (index the column)
- Test: `tests/test_store/test_markdown.py`, `tests/test_index/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store/test_markdown.py` (create the file if absent, with the imports
from the sibling tests):

```python
from datetime import datetime, timezone

from ormah.models.node import MemoryNode, NodeType, Tier
from ormah.store.markdown import parse_node, serialize_node


def test_archived_at_round_trips_through_frontmatter():
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    node = MemoryNode(type=NodeType.fact, tier=Tier.archival,
                      content="x", archived_at=when)
    parsed = parse_node(serialize_node(node))
    assert parsed.archived_at == when


def test_archived_at_absent_when_none():
    node = MemoryNode(type=NodeType.fact, content="x")
    assert "archived_at" not in serialize_node(node)
    assert parse_node(serialize_node(node)).archived_at is None
```

Create `tests/test_index/test_migrations.py`:

```python
from ormah.index.db import Database


def test_migrate_adds_archived_at_and_backfills(tmp_path):
    # Build a legacy-shaped DB: nodes table without archived_at, one archival row.
    db = Database(tmp_path / "index.db")
    db.init_schema()
    db.conn.execute("ALTER TABLE nodes DROP COLUMN archived_at")
    db.conn.execute(
        "INSERT INTO nodes (id, type, tier, source, created, updated, last_accessed, "
        "file_path, file_hash) VALUES "
        "('n1','fact','archival','agent:test','2026-01-01T00:00:00Z','2026-02-01T00:00:00Z',"
        "'2026-02-01T00:00:00Z','/x.md','abc')"
    )
    db.conn.commit()

    db._migrate()

    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(nodes)").fetchall()]
    assert "archived_at" in cols
    row = db.conn.execute("SELECT archived_at FROM nodes WHERE id='n1'").fetchone()
    assert row["archived_at"] == "2026-02-01T00:00:00Z"  # backfilled from updated
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store/test_markdown.py tests/test_index/test_migrations.py -v`
Expected: FAIL (`archived_at` not a field / column).

- [ ] **Step 3: Add the model field**

In `src/ormah/models/node.py`, inside `MemoryNode`, add right after the `last_review` line:

```python
    archived_at: datetime | None = None  # when the node entered the archival tier (#28)
```

- [ ] **Step 4: Serialize/parse the frontmatter**

In `src/ormah/store/markdown.py`:

In `parse_node`, add to the `MemoryNode(...)` constructor args (next to `last_review`):

```python
        archived_at=_parse_dt(meta["archived_at"]) if meta.get("archived_at") else None,
```

In `serialize_node`, add after the `last_review` block:

```python
    if node.archived_at is not None:
        meta["archived_at"] = _format_dt(node.archived_at)
```

- [ ] **Step 5: Add the schema column (fresh DBs)**

In `src/ormah/index/schema.sql`, add to the `nodes` table after `last_review TEXT,`:

```sql
    archived_at TEXT,
```

- [ ] **Step 6: Add the migration (legacy DBs)**

In `src/ormah/index/db.py` `_migrate`, add to the `enrichment_migrations` list:

```python
                ("archived_at", "ALTER TABLE nodes ADD COLUMN archived_at TEXT"),
```

Then, immediately after the `for col_name, ddl in enrichment_migrations:` loop, backfill:

```python
            if "archived_at" not in node_cols:
                # Newly added: seed existing archival rows with their `updated` time, the
                # best proxy for when they were demoted. Non-archival rows stay NULL.
                conn.execute(
                    "UPDATE nodes SET archived_at = updated "
                    "WHERE tier = 'archival' AND archived_at IS NULL"
                )
```

- [ ] **Step 7: Index the column**

In `src/ormah/index/builder.py` `_index_file_nodes_only`, update the INSERT:

Column list — change `... last_review, file_path, file_hash)` to
`... last_review, archived_at, file_path, file_hash)` and add one `?` to the VALUES tuple.

Add this value right before `str(path),`:

```python
                node.archived_at.isoformat() if node.archived_at else None,
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store/test_markdown.py tests/test_index/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 9: Full regression on touched subsystems**

Run: `.venv/bin/python -m pytest tests/test_index tests/test_store -v`
Expected: PASS (no regressions from the new column).

- [ ] **Step 10: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/models/node.py src/ormah/store/markdown.py src/ormah/index/db.py src/ormah/index/builder.py
git add src/ormah/models/node.py src/ormah/store/markdown.py src/ormah/index/schema.sql src/ormah/index/db.py src/ormah/index/builder.py tests/test_store/test_markdown.py tests/test_index/test_migrations.py
git commit -m "feat(index): add archived_at timestamp to nodes (#28)"
```

> **Note for executor:** if `ALTER TABLE ... DROP COLUMN` is unsupported on the installed
> SQLite, replace Step 1's `DROP COLUMN` setup by creating the DB, then asserting the column
> exists after `init_schema()` (fresh DBs get it from schema.sql) and testing backfill by
> inserting an archival row with NULL `archived_at` and calling the backfill UPDATE directly.

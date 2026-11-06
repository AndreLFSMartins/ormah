> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 1: `full_rebuild` clears the lifecycle keys

**Files:**
- Modify: `src/ormah/index/builder.py:34-36`
- Test: `tests/test_index/test_builder.py`

**Interfaces:**
- Produces: after `IndexBuilder.full_rebuild()`, `meta` contains none of `auto_link_watermark`, `fsrs_migrated`, `lifecycle_model_version`. Task 2 relies on this so `_migrate_fsrs` gets to run on the rebuilt graph.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_index/test_builder.py`:

```python
def test_full_rebuild_clears_lifecycle_keys(db, file_store):
    """#236: the index is derived state, so a rebuild must invalidate the
    lifecycle-migration markers the same way it already invalidates the
    auto-link watermark. Otherwise a restore onto an existing index finds
    'already migrated' and never seeds pre-FSRS nodes."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('fsrs_migrated', '1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_model_version', '2')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('auto_link_watermark', '7')"
        )
        # An unrelated key must survive: rebuild invalidates lifecycle state, not all of meta.
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('user_node_id', 'keep-me')"
        )

    IndexBuilder(db, file_store).full_rebuild()

    keys = {
        row["key"] for row in db.conn.execute("SELECT key FROM meta").fetchall()
    }
    assert "fsrs_migrated" not in keys
    assert "lifecycle_model_version" not in keys
    assert "auto_link_watermark" not in keys
    assert "user_node_id" in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index/test_builder.py::test_full_rebuild_clears_lifecycle_keys -v`
Expected: FAIL on `assert "fsrs_migrated" not in keys`.

- [ ] **Step 3: Write minimal implementation**

In `src/ormah/index/builder.py`, replace lines 34-36:

```python
        # Mass reindex re-allocates seq from the durable counter; clear the watermark so the
        # rebuilt store is reprocessed even if the counter was also reset (wiped meta).
        self.db.conn.execute("DELETE FROM meta WHERE key = 'auto_link_watermark'")
```

with:

```python
        # Mass reindex re-allocates seq from the durable counter; clear the watermark so the
        # rebuilt store is reprocessed even if the counter was also reset (wiped meta).
        # The lifecycle markers are derived state too (#236): index.db is excluded from
        # backups, so a restore onto an existing index must re-evaluate the FSRS migration
        # instead of trusting a marker written for the previous graph.
        self.db.conn.execute(
            "DELETE FROM meta WHERE key IN "
            "('auto_link_watermark', 'fsrs_migrated', 'lifecycle_model_version')"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index/test_builder.py tests/test_background/test_auto_linker.py -v`
Expected: all PASS (the auto-linker suite exercises the watermark deletion and must stay green).

- [ ] **Step 5: Commit**

```bash
git add src/ormah/index/builder.py tests/test_index/test_builder.py
git commit -m "fix(index): full_rebuild clears the lifecycle migration keys (#236)"
```

---


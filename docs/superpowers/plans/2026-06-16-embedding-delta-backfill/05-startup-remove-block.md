# Task 05: Remove the synchronous embed block from `startup()`

`startup()` currently blocks the uvicorn port bind on a full re-embed whenever any vector is
missing. Delete that block — recovery (delta + schema bump) now lives in `backfill_embeddings`
(Task 03), driven by the background job (Task 06/07). After this, `startup()` never touches the
encoder, so the port binds immediately.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`startup()` ~L121-138)
- Test: `tests/test_engine/test_startup_no_embedding.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine/test_startup_no_embedding.py`:

```python
"""startup() must not embed synchronously anymore (#32)."""
from __future__ import annotations

from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine


def test_startup_does_not_call_reindex(tmp_memory_dir, monkeypatch):
    called = {"reindex": False, "embed_rows": False}

    monkeypatch.setattr(
        MemoryEngine, "_reindex_all_embeddings",
        lambda self: called.__setitem__("reindex", True),
    )
    monkeypatch.setattr(
        MemoryEngine, "_embed_node_rows",
        lambda self, nodes: (called.__setitem__("embed_rows", True), (0, 0))[1],
    )

    eng = MemoryEngine(Settings(memory_dir=tmp_memory_dir))
    eng.startup()
    try:
        assert called["reindex"] is False
        assert called["embed_rows"] is False
    finally:
        eng.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine/test_startup_no_embedding.py -v`
Expected: FAIL — `startup()` currently calls `_reindex_all_embeddings()` on a fresh store
(empty `node_vectors`, `stored_version 0 < 2`), so `called["reindex"]` is True.

- [ ] **Step 3: Remove the embed block**

In `src/ormah/engine/memory_engine.py`, delete the entire block (~L121-138) that begins with
the comment `# Re-embed nodes if the vector store is missing entries or schema version changed`
and ends with the `embedding_schema_version` meta write — i.e. remove:

```python
        # Re-embed nodes if the vector store is missing entries or schema version changed
        vec_count = self.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
        stored_version_row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
        ).fetchone()
        stored_version = int(stored_version_row["value"]) if stored_version_row else 0
        needs_reindex = (count > 0 and vec_count < count) or stored_version < _EMBEDDING_SCHEMA_VERSION

        if needs_reindex:
            reason = "schema version change" if stored_version < _EMBEDDING_SCHEMA_VERSION else "missing entries"
            logger.info("Re-indexing embeddings (%s): vec=%d, nodes=%d, schema v%d→v%d",
                        reason, vec_count, count, stored_version, _EMBEDDING_SCHEMA_VERSION)
            self._reindex_all_embeddings()
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_schema_version', ?)",
                    (str(_EMBEDDING_SCHEMA_VERSION),),
                )
```

Leave the surrounding blocks intact: the `count == 0 → full_rebuild` block above and the
`_migrate_fsrs()` / `_ensure_self_node()` / warmup calls below. The schema-version detection
and bump now happen in `backfill_embeddings` (Task 03).

- [ ] **Step 4: Run the test + the broader engine suite**

Run: `.venv/bin/python -m pytest tests/test_engine/ -v`
Expected: PASS — including the new test (`startup()` no longer reindexes) and Tasks 02-04 tests.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_startup_no_embedding.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_startup_no_embedding.py
git commit -m "perf(engine): stop blocking startup on full re-embed; recovery moves to job (#32)"
```

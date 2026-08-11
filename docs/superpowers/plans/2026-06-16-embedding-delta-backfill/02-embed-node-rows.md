# Task 02: Extract `_embed_node_rows` from `_reindex_all_embeddings`

Pure refactor: pull the build-embeddings → chunked-upsert → verify loop into a reusable
`_embed_node_rows(nodes) -> (embedded_ids, failed_ids)` method that operates on an explicit row
list and reports **which** ids succeeded/failed (Task 03's reconciliation needs the ids — it
deletes the stale vector of any node that fails to re-embed — not just counts).
`_reindex_all_embeddings()` becomes a thin wrapper, so the public reindex path is
unchanged. The `vec_count` discrepancy warning from the original is preserved.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`_reindex_all_embeddings` ~L1063-1115)
- Test: `tests/test_engine/test_embed_node_rows.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine/test_embed_node_rows.py`:

```python
"""Tests for MemoryEngine._embed_node_rows (extracted embedding core, #32)."""
from __future__ import annotations

from ormah.models.node import CreateNodeRequest


def test_embed_node_rows_returns_embedded_ids(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Alpha", content="hello world"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    rows = engine.db.conn.execute(
        "SELECT id, title, content FROM nodes WHERE id = ?", (nid,)
    ).fetchall()

    embedded_ids, failed_ids = engine._embed_node_rows(rows)

    assert embedded_ids == [nid]
    assert failed_ids == []
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_embed_node_rows_reports_failed_ids(engine, monkeypatch):
    nid, _ = engine.remember(CreateNodeRequest(title="Boom", content="payload"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    rows = engine.db.conn.execute(
        "SELECT id, title, content FROM nodes WHERE id = ?", (nid,)
    ).fetchall()

    class _DeadEncoder:
        def encode(self, text):
            raise RuntimeError("encoder down")

    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda settings: _DeadEncoder())

    embedded_ids, failed_ids = engine._embed_node_rows(rows)

    assert embedded_ids == []
    assert failed_ids == [nid]


def test_embed_node_rows_empty_list_is_noop(engine):
    embedded_ids, failed_ids = engine._embed_node_rows([])
    assert embedded_ids == []
    assert failed_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embed_node_rows.py -v`
Expected: FAIL — `AttributeError: 'MemoryEngine' object has no attribute '_embed_node_rows'`.

- [ ] **Step 3: Implement the extraction**

Replace the body of `_reindex_all_embeddings` (~L1063-1115) with a thin wrapper, and add the
new method directly above it:

```python
    def _embed_node_rows(self, nodes) -> tuple[list[str], list[str]]:
        """Embed the given node rows into the vector store.

        Builds embeddings, then upserts in chunks of 100 with a WAL checkpoint
        between chunks (sqlite-vec vec0 can silently drop rows in large
        transactions). Returns (embedded_ids, failed_ids). Nodes whose embedding
        text is empty are skipped (in neither list). Logs a warning if the final
        vec_count is below the number upserted (possible silent vec0 drop).
        """
        from ormah.embeddings.vector_store import VectorStore
        from ormah.embeddings.encoder import get_encoder

        total = len(nodes)
        if total == 0:
            return [], []

        encoder = get_encoder(self.settings)
        vec_store = VectorStore(self.db)
        max_chars = self.settings.embedding_max_content_chars
        log_every = max(1, total // 10)

        all_items: list[tuple[str, Any]] = []
        failed_ids: list[str] = []
        for idx, n in enumerate(nodes):
            text = _embedding_text(n["title"], n["content"], max_chars)
            if text:
                try:
                    embedding = encoder.encode(text)
                    all_items.append((n["id"], embedding))
                except Exception as e:
                    logger.warning("Failed to embed node %s: %s", n["id"][:8], e)
                    failed_ids.append(n["id"])
            done = idx + 1
            if done % log_every == 0 or done == total:
                logger.info("Embedding memories: %d/%d", done, total)

        chunk_size = 100
        for i in range(0, len(all_items), chunk_size):
            chunk = all_items[i : i + chunk_size]
            vec_store.upsert_batch(chunk)
            self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        embedded_ids = [item[0] for item in all_items]
        vec_count = self.db.conn.execute(
            "SELECT count(*) FROM node_vectors"
        ).fetchone()[0]
        logger.info(
            "Embedded %d/%d nodes (vec_count=%d, failed=%d)",
            len(embedded_ids), total, vec_count, len(failed_ids),
        )
        return embedded_ids, failed_ids

    def _reindex_all_embeddings(self) -> None:
        """Re-embed all nodes in the index."""
        try:
            nodes = self.db.conn.execute(
                "SELECT id, title, content FROM nodes"
            ).fetchall()
            self._embed_node_rows(nodes)
        except Exception as e:
            logger.warning("Failed to reindex embeddings: %s", e)
```

Note: `Any` is already imported in `memory_engine.py`. If a lint error says otherwise, add
`from typing import Any`.

- [ ] **Step 4: Run new + existing embedding tests**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embed_node_rows.py tests/test_embeddings/ -v`
Expected: PASS (new tests + existing embedding/reindex tests stay green).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_embed_node_rows.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_embed_node_rows.py
git commit -m "refactor(engine): extract _embed_node_rows returning embedded/failed ids (#32)"
```

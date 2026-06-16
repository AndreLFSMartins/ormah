# Task 03: `backfill_embeddings()` — delta + schema-bump modes

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (add method near `_reindex_all_embeddings`)
- Test: `tests/test_engine/test_backfill_embeddings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_backfill_embeddings.py`:

```python
"""Tests for MemoryEngine.backfill_embeddings (delta + schema-bump, #32)."""
from __future__ import annotations

from ormah.models.node import CreateNodeRequest


def _set_schema_version(engine, version: int) -> None:
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES "
            "('embedding_schema_version', ?)",
            (str(version),),
        )


def test_backfill_delta_closes_the_gap(engine):
    from ormah.engine.memory_engine import _EMBEDDING_SCHEMA_VERSION
    ids = []
    for i in range(3):
        nid, _ = engine.remember(CreateNodeRequest(title=f"N{i}", content=f"content {i}"))
        ids.append(nid)
    # store is already on the current embedding schema → delta mode (not schema bump)
    _set_schema_version(engine, _EMBEDDING_SCHEMA_VERSION)
    # create a 1-node gap
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (ids[0],))

    result = engine.backfill_embeddings()

    assert result["mode"] == "delta"
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (ids[0],)
    ).fetchone()[0] == 1


def test_backfill_delta_is_noop_when_full(engine):
    from ormah.engine.memory_engine import _EMBEDDING_SCHEMA_VERSION
    engine.remember(CreateNodeRequest(title="Solo", content="content"))
    _set_schema_version(engine, _EMBEDDING_SCHEMA_VERSION)
    # first delta pass settles any startup-created node (e.g. the self node)
    engine.backfill_embeddings()

    result = engine.backfill_embeddings()

    assert result["mode"] == "delta"
    assert result["embedded"] == 0


def test_backfill_schema_bump_reembeds_all_and_bumps_version(engine):
    engine.remember(CreateNodeRequest(title="A", content="alpha"))
    engine.remember(CreateNodeRequest(title="B", content="beta"))
    _set_schema_version(engine, 1)  # below _EMBEDDING_SCHEMA_VERSION (2)
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    result = engine.backfill_embeddings()

    from ormah.engine.memory_engine import _EMBEDDING_SCHEMA_VERSION
    assert result["mode"] == "schema"
    stored = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
    ).fetchone()["value"]
    assert int(stored) == _EMBEDDING_SCHEMA_VERSION


def test_backfill_schema_bump_does_not_bump_version_on_failure(engine, monkeypatch):
    engine.remember(CreateNodeRequest(title="A", content="alpha"))
    _set_schema_version(engine, 1)

    class _BoomEncoder:
        def encode(self, text):
            raise RuntimeError("encoder down")

    monkeypatch.setattr(
        "ormah.embeddings.encoder.get_encoder", lambda settings: _BoomEncoder()
    )

    result = engine.backfill_embeddings()

    assert result["mode"] == "schema"
    stored = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
    ).fetchone()["value"]
    assert int(stored) == 1  # NOT bumped — re-embed failed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: FAIL — `AttributeError: ... 'backfill_embeddings'`.

- [ ] **Step 3: Implement `backfill_embeddings`**

In `src/ormah/engine/memory_engine.py`, add this method immediately after `_embed_node_rows`
(from Task 02):

```python
    def backfill_embeddings(self) -> dict:
        """Reconcile the vector store. On an embedding-schema bump, re-embed all
        nodes (bumping the stored version only on full success). Otherwise embed
        only nodes missing a vector (delta). Safe to run repeatedly; a no-op when
        the store is already consistent. Returns a summary dict."""
        count = self.db.conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        stored_version_row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
        ).fetchone()
        stored_version = int(stored_version_row["value"]) if stored_version_row else 0

        if stored_version < _EMBEDDING_SCHEMA_VERSION:
            nodes = self.db.conn.execute(
                "SELECT id, title, content FROM nodes"
            ).fetchall()
            logger.info(
                "Embedding backfill (schema v%d→v%d): re-embedding %d nodes",
                stored_version, _EMBEDDING_SCHEMA_VERSION, len(nodes),
            )
            embedded, failed = self._embed_node_rows(nodes)
            if failed == 0:
                with self.db.transaction() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES "
                        "('embedding_schema_version', ?)",
                        (str(_EMBEDDING_SCHEMA_VERSION),),
                    )
            mode = "schema"
        else:
            nodes = self.db.conn.execute(
                "SELECT id, title, content FROM nodes "
                "WHERE id NOT IN (SELECT id FROM node_vectors_rowids)"
            ).fetchall()
            if nodes:
                logger.info(
                    "Embedding backfill (delta): embedding %d missing nodes", len(nodes)
                )
            embedded, failed = self._embed_node_rows(nodes)
            mode = "delta"

        vec_count = self.db.conn.execute(
            "SELECT count(*) FROM node_vectors"
        ).fetchone()[0]
        return {
            "mode": mode,
            "embedded": embedded,
            "failed": failed,
            "vec_count": vec_count,
            "node_count": count,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git commit -m "feat(engine): add backfill_embeddings delta + schema-bump recovery (#32)"
```

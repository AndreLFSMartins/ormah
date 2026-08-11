# Task 03: `_missing_embeddable_count()` + `backfill_embeddings()`

Implements the council-revised recovery (**R2: quarantine dropped**): two modes (delta /
schema-bump) with **no quarantine** and **no fail-count meta**. A schema bump re-embeds all
embeddable nodes once, deletes the stale vector of any node that fails to encode (so it
becomes genuinely missing), and advances the version **unconditionally** after the pass.
Delta mode embeds only the nodes missing from the vector store (anti-join, O(gap)). A
permanently-failing ("poison") node stays visible in `missing` and is retried every tick —
never dropped, never masked.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (add `_EMBEDDABLE_SQL` + `_missing_embeddable_count` + `backfill_embeddings` near `_embed_node_rows`)
- Test: `tests/test_engine/test_backfill_embeddings.py`

## Concepts

- **embeddable** node (SQL proxy for non-empty `_embedding_text`): `COALESCE(NULLIF(TRIM(content), ''), NULLIF(TRIM(title), '')) IS NOT NULL`. There is **no** quarantine — every embeddable node is always a candidate.
- **missing** = embeddable nodes with no row in `node_vectors_rowids` (via `LEFT JOIN ... WHERE v.id IS NULL`). `_missing_embeddable_count()` takes **no arguments**; it is the honest gap.
- **schema bump** (`stored_version < _EMBEDDING_SCHEMA_VERSION`): re-embed all embeddable nodes once; for each failure, `DELETE FROM node_vectors WHERE id = ?` so the node becomes genuinely missing; advance the version unconditionally after the pass.
- **delta** (`stored_version == _EMBEDDING_SCHEMA_VERSION`): embed only the missing embeddable nodes, O(gap).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_backfill_embeddings.py`:

```python
"""Tests for MemoryEngine.backfill_embeddings (delta + schema-bump, no quarantine, #32).

Design (council R2): schema-bump re-embeds all embeddable nodes once, deletes the
stale vector of any node that fails to encode (so it becomes genuinely missing),
and advances the version unconditionally after the pass. Delta mode embeds only
nodes missing from the vector store. A permanently-failing node stays visible in
``missing`` and is retried every tick -- never dropped, never masked.
"""
from __future__ import annotations

import numpy as np

from ormah.models.node import CreateNodeRequest
from ormah.engine.memory_engine import _EMBEDDING_SCHEMA_VERSION


def _set_schema_version(engine, version: int) -> None:
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES "
            "('embedding_schema_version', ?)",
            (str(version),),
        )


def _stored_version(engine) -> int:
    return int(engine.db.conn.execute(
        "SELECT value FROM meta WHERE key='embedding_schema_version'"
    ).fetchone()["value"])


def test_backfill_delta_closes_the_gap(engine):
    ids = []
    for i in range(3):
        nid, _ = engine.remember(CreateNodeRequest(title=f"N{i}", content=f"content {i}"))
        ids.append(nid)
    _set_schema_version(engine, _EMBEDDING_SCHEMA_VERSION)  # already current -> delta mode
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (ids[0],))

    result = engine.backfill_embeddings()

    assert result["mode"] == "delta"
    assert result["missing"] == 0
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (ids[0],)
    ).fetchone()[0] == 1


def test_backfill_delta_is_noop_when_full(engine):
    engine.remember(CreateNodeRequest(title="Solo", content="content"))
    _set_schema_version(engine, _EMBEDDING_SCHEMA_VERSION)
    engine.backfill_embeddings()  # settle any startup-created node

    result = engine.backfill_embeddings()

    assert result["mode"] == "delta"
    assert result["embedded"] == 0


def test_backfill_schema_bump_reembeds_all_and_bumps_version(engine):
    engine.remember(CreateNodeRequest(title="A", content="alpha"))
    engine.remember(CreateNodeRequest(title="B", content="beta"))
    _set_schema_version(engine, 1)
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    result = engine.backfill_embeddings()

    assert result["mode"] == "schema"
    assert result["missing"] == 0
    assert _stored_version(engine) == _EMBEDDING_SCHEMA_VERSION


def test_schema_bump_poison_node_stays_visible_and_advances_version(engine, monkeypatch):
    """A node that always fails to encode stays genuinely missing (its stale vector
    is deleted) and visible in `missing`; the version still advances after the pass,
    and the next delta run retries it without re-embedding the whole store."""
    engine.remember(CreateNodeRequest(title="poison", content="POISON payload"))
    engine.remember(CreateNodeRequest(title="ok1", content="fine one"))
    engine.remember(CreateNodeRequest(title="ok2", content="fine two"))
    _set_schema_version(engine, 1)

    dim = engine.settings.embedding_dim

    class _SelectiveEncoder:
        def __init__(self):
            self.encode_calls = 0

        def encode(self, text):
            self.encode_calls += 1
            if "POISON" in text:
                raise RuntimeError("poison node")
            return np.ones(dim, dtype="float32")

    enc = _SelectiveEncoder()
    monkeypatch.setattr("ormah.embeddings.encoder.get_encoder", lambda settings: enc)

    # Schema bump: poison fails -> its stale vector is deleted -> genuinely missing.
    r1 = engine.backfill_embeddings()
    assert r1["mode"] == "schema"
    assert r1["failed"] == 1
    assert r1["missing"] == 1
    assert _stored_version(engine) == _EMBEDDING_SCHEMA_VERSION  # advances unconditionally
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = "
        "(SELECT id FROM nodes WHERE title='poison')"
    ).fetchone()[0] == 0

    # Delta run: retries ONLY the missing poison node (O(gap)), still fails.
    calls_after_schema = enc.encode_calls
    r2 = engine.backfill_embeddings()
    assert r2["mode"] == "delta"
    assert r2["embedded"] == 0
    assert r2["failed"] == 1
    assert r2["missing"] == 1
    assert enc.encode_calls == calls_after_schema + 1  # one retry, not a full re-embed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: FAIL — `AttributeError: ... 'backfill_embeddings'`.

- [ ] **Step 3: Add `_EMBEDDABLE_SQL` + `_missing_embeddable_count`**

In `src/ormah/engine/memory_engine.py`, add these near `_embed_node_rows` (Task 02):

```python
    # SQL proxy for "_embedding_text(title, content) is non-empty": a node is
    # embeddable when it has non-whitespace content OR title.
    _EMBEDDABLE_SQL = (
        "COALESCE(NULLIF(TRIM(content), ''), NULLIF(TRIM(title), '')) IS NOT NULL"
    )

    def _missing_embeddable_count(self) -> int:
        """Embeddable nodes with no row in the vector store (the honest gap)."""
        return self.db.conn.execute(
            f"SELECT count(*) FROM nodes n "
            f"LEFT JOIN node_vectors_rowids v ON n.id = v.id "
            f"WHERE v.id IS NULL AND {self._EMBEDDABLE_SQL}"
        ).fetchone()[0]
```

- [ ] **Step 4: Implement `backfill_embeddings`**

Add immediately after the helpers:

```python
    def backfill_embeddings(self) -> dict:
        """Reconcile the vector store. Idempotent; safe to run repeatedly.

        Two modes:
        - **schema bump** (stored version < current): every existing vector was
          built under an old scheme, so re-embed all embeddable nodes in a single
          pass. For each node that fails to encode, delete its stale vector so it
          becomes genuinely missing (caught by future delta runs). Advance the
          version unconditionally after the pass -- the store has been fully
          reprocessed; nodes that could not be embedded are now honestly missing.
        - **delta** (stored version == current): embed only embeddable nodes
          missing from the vector store (anti-join), O(gap).

        A permanently-failing node simply stays in ``missing`` and is retried each
        tick -- never dropped, never masked. Returns a summary dict where
        ``missing`` is the honest embedding gap after the run.
        """
        count = self.db.conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        ver_row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
        ).fetchone()
        stored_version = int(ver_row["value"]) if ver_row else 0

        if stored_version < _EMBEDDING_SCHEMA_VERSION:
            mode = "schema"
            rows = self.db.conn.execute(
                f"SELECT id, title, content FROM nodes WHERE {self._EMBEDDABLE_SQL}"
            ).fetchall()
            logger.info(
                "Embedding backfill (schema v%d->v%d): re-embedding %d nodes",
                stored_version, _EMBEDDING_SCHEMA_VERSION, len(rows),
            )
        else:
            mode = "delta"
            rows = self.db.conn.execute(
                f"SELECT n.id, n.title, n.content FROM nodes n "
                f"LEFT JOIN node_vectors_rowids v ON n.id = v.id "
                f"WHERE v.id IS NULL AND {self._EMBEDDABLE_SQL}"
            ).fetchall()
            if rows:
                logger.info("Embedding backfill (delta): embedding %d missing nodes", len(rows))

        embedded_ids, failed_ids = self._embed_node_rows(rows)

        # Schema mode: drop the stale vector of any node that failed to re-embed
        # under the new scheme, so it is genuinely missing (and retried by delta)
        # rather than silently kept with an outdated embedding.
        if mode == "schema" and failed_ids:
            with self.db.transaction() as conn:
                for nid in failed_ids:
                    conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))

        # Advance the schema version unconditionally after a full schema pass.
        if mode == "schema":
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES "
                    "('embedding_schema_version', ?)",
                    (str(_EMBEDDING_SCHEMA_VERSION),),
                )

        missing = self._missing_embeddable_count()
        vec_count = self.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
        return {
            "mode": mode,
            "embedded": len(embedded_ids),
            "failed": len(failed_ids),
            "missing": missing,
            "vec_count": vec_count,
            "node_count": count,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: PASS (4 tests, incl. the poison-node-stays-visible bound).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git commit -m "feat(engine): backfill_embeddings delta + schema-bump, delete-stale, advance-after-pass (#32)"
```

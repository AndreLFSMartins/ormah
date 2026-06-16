# Task 03: Quarantine helpers + `backfill_embeddings()`

Implements the council-revised recovery: two modes (delta / schema-bump), a **quarantine**
with a bounded retry budget so a single permanently-failing ("poison") node cannot force an
O(n) re-embed every tick (**C1**), and a **completeness** check that advances the schema
version only when the store is verified complete against `vec_count` (**I2**).

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (add helpers + `backfill_embeddings` near `_reindex_all_embeddings`)
- Test: `tests/test_engine/test_backfill_embeddings.py`

## Concepts

- `meta['embedding_quarantine']` — JSON list of node ids that failed `>= embedding_schema_max_attempts` times. Excluded from the delta and from the completeness target.
- `meta['embedding_fail_counts']` — JSON dict `{id: consecutive_fail_count}`; a success clears the entry.
- **embeddable** node (SQL proxy for non-empty `_embedding_text`): `COALESCE(NULLIF(TRIM(content),''), NULLIF(TRIM(title),'')) IS NOT NULL`, and id not quarantined.
- **missing** = embeddable nodes with no row in `node_vectors_rowids` (via `LEFT JOIN ... WHERE v.id IS NULL`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_backfill_embeddings.py`:

```python
"""Tests for MemoryEngine.backfill_embeddings (delta + schema-bump + quarantine, #32)."""
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
    stored = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
    ).fetchone()["value"]
    assert int(stored) == _EMBEDDING_SCHEMA_VERSION


def test_schema_bump_quarantines_poison_node_without_looping(engine, monkeypatch):
    """C1: a node that always fails to encode is quarantined within the retry
    budget; the version then advances and subsequent runs do NOT re-embed all N."""
    engine.settings.embedding_schema_max_attempts = 2
    engine.remember(CreateNodeRequest(title="poison", content="POISON payload"))
    engine.remember(CreateNodeRequest(title="ok1", content="fine one"))
    engine.remember(CreateNodeRequest(title="ok2", content="fine two"))
    _set_schema_version(engine, 1)
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

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

    r1 = engine.backfill_embeddings()  # poison fails (count 1) -> version stays 1
    assert r1["mode"] == "schema"
    assert int(engine.db.conn.execute(
        "SELECT value FROM meta WHERE key='embedding_schema_version'").fetchone()["value"]) == 1

    r2 = engine.backfill_embeddings()  # poison fails again (count 2) -> quarantined -> version bumps
    assert r2["mode"] == "schema"
    assert r2["quarantined"] == 1
    assert int(engine.db.conn.execute(
        "SELECT value FROM meta WHERE key='embedding_schema_version'").fetchone()["value"]) == _EMBEDDING_SCHEMA_VERSION

    calls_before = enc.encode_calls
    r3 = engine.backfill_embeddings()  # delta mode; quarantined poison excluded
    assert r3["mode"] == "delta"
    assert r3["embedded"] == 0
    assert enc.encode_calls == calls_before  # did NOT re-embed all N again
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: FAIL — `AttributeError: ... 'backfill_embeddings'`.

- [ ] **Step 3: Add quarantine + query helpers**

In `src/ormah/engine/memory_engine.py`, add these helpers near `_embed_node_rows` (Task 02).
`import json` is already present at the top of the module.

```python
    _EMBEDDABLE_SQL = (
        "COALESCE(NULLIF(TRIM(content), ''), NULLIF(TRIM(title), '')) IS NOT NULL"
    )

    def _get_meta_json(self, key: str, default):
        row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def _set_meta_json(self, key: str, value) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def _missing_embeddable_count(self, quarantine: set[str]) -> int:
        rows = self.db.conn.execute(
            f"SELECT n.id FROM nodes n "
            f"LEFT JOIN node_vectors_rowids v ON n.id = v.id "
            f"WHERE v.id IS NULL AND {self._EMBEDDABLE_SQL}"
        ).fetchall()
        return sum(1 for r in rows if r["id"] not in quarantine)
```

- [ ] **Step 4: Implement `backfill_embeddings`**

Add immediately after the helpers:

```python
    def backfill_embeddings(self) -> dict:
        """Reconcile the vector store. Schema-bump mode re-embeds all non-quarantined
        nodes and advances the version only when the store is verified complete; delta
        mode embeds only missing embeddable nodes. Persistently-failing nodes are
        quarantined (bounded retry budget) so one poison node cannot force a full
        re-embed every tick. Safe to run repeatedly. Returns a summary dict."""
        max_attempts = self.settings.embedding_schema_max_attempts
        quarantine = set(self._get_meta_json("embedding_quarantine", []))
        fail_counts = self._get_meta_json("embedding_fail_counts", {})

        count = self.db.conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        ver_row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
        ).fetchone()
        stored_version = int(ver_row["value"]) if ver_row else 0

        q_list = list(quarantine)
        placeholders = ",".join("?" * len(q_list)) if q_list else None
        not_quarantined = f"AND n.id NOT IN ({placeholders})" if placeholders else ""
        params = tuple(q_list)

        if stored_version < _EMBEDDING_SCHEMA_VERSION:
            mode = "schema"
            rows = self.db.conn.execute(
                f"SELECT n.id, n.title, n.content FROM nodes n "
                f"WHERE {self._EMBEDDABLE_SQL} {not_quarantined}",
                params,
            ).fetchall()
        else:
            mode = "delta"
            rows = self.db.conn.execute(
                f"SELECT n.id, n.title, n.content FROM nodes n "
                f"LEFT JOIN node_vectors_rowids v ON n.id = v.id "
                f"WHERE v.id IS NULL AND {self._EMBEDDABLE_SQL} {not_quarantined}",
                params,
            ).fetchall()
            if rows:
                logger.info("Embedding backfill (delta): embedding %d missing nodes", len(rows))

        embedded_ids, failed_ids = self._embed_node_rows(rows)

        # Update fail counters; quarantine nodes over the retry budget.
        for nid in embedded_ids:
            fail_counts.pop(nid, None)
        newly_quarantined = 0
        for nid in failed_ids:
            fail_counts[nid] = fail_counts.get(nid, 0) + 1
            if fail_counts[nid] >= max_attempts:
                quarantine.add(nid)
                fail_counts.pop(nid, None)
                newly_quarantined += 1
        self._set_meta_json("embedding_quarantine", sorted(quarantine))
        self._set_meta_json("embedding_fail_counts", fail_counts)

        missing = self._missing_embeddable_count(quarantine)

        if mode == "schema" and missing == 0:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES "
                    "('embedding_schema_version', ?)",
                    (str(_EMBEDDING_SCHEMA_VERSION),),
                )

        vec_count = self.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
        return {
            "mode": mode,
            "embedded": len(embedded_ids),
            "failed": len(failed_ids),
            "missing": missing,
            "quarantined": len(quarantine),
            "vec_count": vec_count,
            "node_count": count,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_backfill_embeddings.py -v`
Expected: PASS (4 tests, incl. the poison-node bound).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_backfill_embeddings.py
git commit -m "feat(engine): backfill_embeddings with quarantine + verified completeness (#32)"
```

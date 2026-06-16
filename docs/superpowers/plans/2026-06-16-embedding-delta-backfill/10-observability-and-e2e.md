# Task 10: Observability + end-to-end recovery test

Council **I3**: "vector search degraded indefinitely" is invisible without a metric, and no
task proves recovery end-to-end. Expose `embedding_gap` (embeddable nodes missing a vector)
and `embedding_schema_version` via `stats()` so the operator can see active degradation, and
add an E2E test: artificial gap → registered job heals it → gap returns to 0.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`stats()` ~L1117-1126)
- Test: `tests/test_engine/test_embedding_observability.py`

Depends on Task 03 (`_missing_embeddable_count`), Task 06
(`run_embedding_backfill`), Task 07 (job registered).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_embedding_observability.py`:

```python
"""stats() must expose the embedding gap + schema version, and recovery must
prove out end-to-end via the registered job (#32, council I3)."""
from __future__ import annotations

from ormah.engine.memory_engine import _EMBEDDING_SCHEMA_VERSION
from ormah.models.node import CreateNodeRequest


def _set_schema_current(engine):
    with engine.db.transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES "
                     "('embedding_schema_version', ?)", (str(_EMBEDDING_SCHEMA_VERSION),))


def test_stats_exposes_embedding_gap_and_version(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="x", content="y"))
    _set_schema_current(engine)
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    s = engine.stats()
    assert s["embedding_gap"] >= 1
    assert s["embedding_schema_version"] == _EMBEDDING_SCHEMA_VERSION
    assert "vec_count" in s


def test_e2e_gap_recovers_via_registered_job(engine):
    from ormah.background.scheduler import start_scheduler
    from ormah.background.embedding_backfill import run_embedding_backfill
    nid, _ = engine.remember(CreateNodeRequest(title="recover", content="me"))
    _set_schema_current(engine)
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    assert engine.stats()["embedding_gap"] >= 1
    scheduler, _t = start_scheduler(engine)
    try:
        assert scheduler.get_job("embedding_backfill") is not None
        run_embedding_backfill(engine)
    finally:
        scheduler.shutdown(wait=False)
    assert engine.stats()["embedding_gap"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embedding_observability.py -v`
Expected: FAIL — `KeyError: 'embedding_gap'` (stats doesn't expose it yet).

- [ ] **Step 3: Extend `stats()`**

In `src/ormah/engine/memory_engine.py`, replace `stats()` (~L1117-1126) with:

```python
    def stats(self) -> dict:
        """Get memory store statistics."""
        tier_counts = self.graph.count_by_tier()
        total = sum(tier_counts.values())
        edge_count = self.db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        vec_count = self.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
        ver_row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_schema_version'"
        ).fetchone()
        return {
            "total_nodes": total,
            "by_tier": tier_counts,
            "total_edges": edge_count,
            "vec_count": vec_count,
            # Embeddable nodes still missing a vector -- the honest embedding gap.
            # Stays > 0 for any node that cannot be embedded (visible, never masked).
            "embedding_gap": self._missing_embeddable_count(),
            "embedding_schema_version": int(ver_row["value"]) if ver_row else 0,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine/test_embedding_observability.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite + lint + commit**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src/ tests/
git add src/ormah/engine/memory_engine.py tests/test_engine/test_embedding_observability.py
git commit -m "feat(engine): expose embedding_gap + schema_version in stats; E2E recovery test (#32)"
```

- [ ] **Step 6: Verify the whole feature**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — no regressions; all #32 tests (Tasks 01-10) green.

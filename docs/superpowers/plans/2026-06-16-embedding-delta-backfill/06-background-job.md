# Task 06: `embedding_backfill` job module

Thin wrapper following the `run_decay(engine)` pattern, with one twist from council **I6**:
when the backfill ends **incomplete** (`missing > 0` after the run — i.e. embeddable nodes
still lack vectors), the job raises so `tracked()` records a job failure and `/admin/health`
reflects the degraded vector store instead of a false "ok". A permanently-failing ("poison")
node therefore stays visibly degraded instead of being masked — it is retried each tick by
the delta pass.

**Files:**
- Create: `src/ormah/background/embedding_backfill.py`
- Test: `tests/test_background/test_embedding_backfill.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_embedding_backfill.py`:

```python
"""Tests for the embedding_backfill reconciliation job (#32)."""
import pytest
from ormah.background.embedding_backfill import run_embedding_backfill
from ormah.models.node import CreateNodeRequest


def test_run_embedding_backfill_closes_gap(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Job", content="content"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))
    run_embedding_backfill(engine)
    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_run_embedding_backfill_raises_when_incomplete(engine, monkeypatch):
    monkeypatch.setattr(engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 1, "missing": 1,
                 "vec_count": 0, "node_count": 1})
    with pytest.raises(RuntimeError, match="incomplete"):
        run_embedding_backfill(engine)


def test_run_embedding_backfill_ok_when_complete(engine, monkeypatch):
    monkeypatch.setattr(engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 0, "missing": 0,
                 "vec_count": 1, "node_count": 1})
    run_embedding_backfill(engine)  # must NOT raise
```

The mock return dicts carry the implemented keys only — `mode`, `embedded`, `failed`,
`missing`, `vec_count`, `node_count` (no `quarantined`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_embedding_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.background.embedding_backfill'`.

- [ ] **Step 3: Create the module**

Create `src/ormah/background/embedding_backfill.py`:

```python
"""Vector-store reconciliation job: backfill missing embeddings (#32)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_embedding_backfill(engine) -> None:
    """Reconcile the vector store. Raises if the store is left incomplete.

    Unlike the other background jobs, this one does NOT swallow an incomplete
    result: when the run ends with ``missing > 0`` (embeddable nodes still lack a
    vector) it raises so ``tracked()`` records a job failure and ``/admin/health``
    reflects the degradation -- the intended health signal. A permanently-failing
    ("poison") node therefore stays visibly degraded instead of being masked.
    """
    result = engine.backfill_embeddings()
    if result.get("embedded") or result.get("missing"):
        logger.info(
            "Embedding backfill (%s): embedded=%d failed=%d missing=%d vec=%d/%d",
            result["mode"], result["embedded"], result["failed"], result["missing"],
            result["vec_count"], result["node_count"],
        )
    if result.get("missing", 0) > 0:
        raise RuntimeError(
            f"Embedding backfill incomplete: {result['missing']} embeddable nodes "
            f"still missing vectors (failed={result['failed']})"
        )
```

Note: unlike the other jobs, this one deliberately does **not** swallow the incomplete
state — `tracked()` (`job_tracker.py`) catches the raise and records a job failure, which is
the intended health signal. A genuine exception inside `backfill_embeddings` also propagates
to `tracked()` the same way.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_embedding_backfill.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/embedding_backfill.py tests/test_background/test_embedding_backfill.py
git add src/ormah/background/embedding_backfill.py tests/test_background/test_embedding_backfill.py
git commit -m "feat(background): embedding_backfill job, raises while incomplete store (#32)"
```

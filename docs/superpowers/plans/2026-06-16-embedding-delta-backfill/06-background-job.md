# Task 06: `embedding_backfill` job module

Thin wrapper following the `run_decay(engine)` pattern, with one twist from council **I4**:
when the backfill ends **incomplete** (`missing > 0` after the run — i.e. embeddable,
non-quarantined nodes still lack vectors), the job raises so `tracked()` records a job
failure and `/admin/health` reflects the degraded vector store instead of a false "ok".
A fully-quarantined / fully-embedded store (`missing == 0`) is a success even if some nodes
failed transiently this tick (they'll be retried next tick within budget).

**Files:**
- Create: `src/ormah/background/embedding_backfill.py`
- Test: `tests/test_background/test_embedding_backfill.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_embedding_backfill.py`:

```python
"""Tests for the embedding_backfill background job (#32)."""
from __future__ import annotations

import pytest

from ormah.background.embedding_backfill import run_embedding_backfill
from ormah.models.node import CreateNodeRequest


def test_run_embedding_backfill_closes_gap(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Job", content="content"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))

    run_embedding_backfill(engine)  # returns None on success, like the other jobs

    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_run_embedding_backfill_raises_when_incomplete(engine, monkeypatch):
    # Simulate a run that leaves the store incomplete.
    monkeypatch.setattr(
        engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 1, "missing": 1,
                 "quarantined": 0, "vec_count": 0, "node_count": 1},
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        run_embedding_backfill(engine)


def test_run_embedding_backfill_ok_when_complete(engine, monkeypatch):
    monkeypatch.setattr(
        engine, "backfill_embeddings",
        lambda: {"mode": "delta", "embedded": 0, "failed": 0, "missing": 0,
                 "quarantined": 0, "vec_count": 1, "node_count": 1},
    )
    run_embedding_backfill(engine)  # must NOT raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_embedding_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.background.embedding_backfill'`.

- [ ] **Step 3: Create the module**

Create `src/ormah/background/embedding_backfill.py`:

```python
"""Vector-store reconciliation job: backfill missing embeddings (#32).

Runs `engine.backfill_embeddings()` -- delta-only when the schema version matches,
a full re-embed (with quarantine) on a schema bump. Registered in the scheduler with a
post-bind `next_run_time` and included in the sleep-cycle `run-all` pass. Raises when the
store is left incomplete so the JobTracker / health surface the degradation (council I4).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_embedding_backfill(engine) -> None:
    """Reconcile the vector store. Raises if the store is left incomplete."""
    result = engine.backfill_embeddings()
    if result.get("embedded") or result.get("missing"):
        logger.info(
            "Embedding backfill (%s): embedded=%d failed=%d missing=%d quarantined=%d vec=%d/%d",
            result["mode"], result["embedded"], result["failed"], result["missing"],
            result["quarantined"], result["vec_count"], result["node_count"],
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
git commit -m "feat(background): embedding_backfill job, non-ok on incomplete store (#32)"
```

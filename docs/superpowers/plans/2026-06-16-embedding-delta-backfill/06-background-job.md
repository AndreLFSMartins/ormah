# Task 06: `embedding_backfill` job module

Thin wrapper following the `run_decay(engine)` / `run_auto_linker(engine)` pattern: call
`engine.backfill_embeddings()`, log non-empty work, swallow exceptions (background jobs never
crash the scheduler).

**Files:**
- Create: `src/ormah/background/embedding_backfill.py`
- Test: `tests/test_background/test_embedding_backfill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_background/test_embedding_backfill.py`:

```python
"""Tests for the embedding_backfill background job (#32)."""
from __future__ import annotations

from ormah.background.embedding_backfill import run_embedding_backfill
from ormah.models.node import CreateNodeRequest


def test_run_embedding_backfill_closes_gap(engine):
    nid, _ = engine.remember(CreateNodeRequest(title="Job", content="content"))
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))

    run_embedding_backfill(engine)  # returns None, like the other jobs

    assert engine.db.conn.execute(
        "SELECT count(*) FROM node_vectors_rowids WHERE id = ?", (nid,)
    ).fetchone()[0] == 1


def test_run_embedding_backfill_swallows_errors(engine, monkeypatch):
    def _boom():
        raise RuntimeError("backfill exploded")

    monkeypatch.setattr(engine, "backfill_embeddings", _boom)

    # must not raise — background jobs are fail-safe
    run_embedding_backfill(engine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_background/test_embedding_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.background.embedding_backfill'`.

- [ ] **Step 3: Create the module**

Create `src/ormah/background/embedding_backfill.py`:

```python
"""Vector-store reconciliation job: backfill missing embeddings (#32).

Runs `engine.backfill_embeddings()` — delta-only when the schema version matches,
a full re-embed on a schema bump. Registered in the scheduler with a post-bind
`next_run_time` and included in the sleep-cycle `run-all` pass.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_embedding_backfill(engine) -> None:
    """Embed any nodes missing a vector (or re-embed all on a schema bump)."""
    try:
        result = engine.backfill_embeddings()
        if result.get("embedded"):
            logger.info(
                "Embedding backfill (%s): embedded=%d failed=%d vec=%d/%d",
                result["mode"], result["embedded"], result.get("failed", 0),
                result["vec_count"], result["node_count"],
            )
    except Exception as e:
        logger.warning("Embedding backfill failed: %s", e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_embedding_backfill.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/embedding_backfill.py tests/test_background/test_embedding_backfill.py
git add src/ormah/background/embedding_backfill.py tests/test_background/test_embedding_backfill.py
git commit -m "feat(background): add embedding_backfill reconciliation job (#32)"
```

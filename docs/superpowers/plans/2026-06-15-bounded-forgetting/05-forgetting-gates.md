# Task 05: Forgetting manager — Phase A gates → soft-delete

**Depends on:** Tasks 01, 02, 03, 04.

Create the new job module. Phase A selects `archival` candidates, applies the §1 conjunction
gates, and soft-deletes the eligible ones via `engine.delete_node` (which already removes from
index, audits, and moves to `deleted/`). The whole job is a no-op when `deletion_enabled=False`.

**Files:**
- Create: `src/ormah/background/forgetting_manager.py`
- Test: `tests/test_background/test_forgetting_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_forgetting_manager.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ormah.background.forgetting_manager import run_forgetting
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier


def _exists(engine, node_id) -> bool:
    row = engine.db.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row is not None


def _make_eligible(engine, content="dead weight", days=200):
    """Create an archival node that passes every gate."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content=content, type=NodeType.fact, tier=Tier.archival, title=content))
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET tier='archival', importance=0.1, stability=1.0, "
        "last_review=?, last_accessed=?, archived_at=? WHERE id=?",
        (old, old, old, node_id))
    engine.db.conn.commit()
    return node_id


def _enable(engine):
    engine.settings.deletion_enabled = True


def test_master_switch_off_is_noop(engine):
    node_id = _make_eligible(engine)
    # default deletion_enabled is False
    run_forgetting(engine)
    assert _exists(engine, node_id) is True


def test_fully_eligible_node_is_soft_deleted(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    assert _exists(engine, node_id) is False


def test_recent_archival_is_kept(engine):
    """Fails gate #2 (sustained staleness)."""
    _enable(engine)
    node_id = _make_eligible(engine, days=5)  # archived/accessed only 5 days ago
    run_forgetting(engine)
    assert _exists(engine, node_id) is True


def test_high_importance_is_kept(engine):
    """Fails gate #4."""
    _enable(engine)
    node_id = _make_eligible(engine)
    engine.db.conn.execute("UPDATE nodes SET importance=0.9 WHERE id=?", (node_id,))
    engine.db.conn.commit()
    run_forgetting(engine)
    assert _exists(engine, node_id) is True


def test_positive_feedback_protects(engine):
    """Fails gate #5."""
    _enable(engine)
    node_id = _make_eligible(engine)
    engine.db.conn.execute(
        "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
        "VALUES (?, ?, 1, 'explicit', ?, 's1')",
        (b"\x00", node_id, datetime.now(timezone.utc).isoformat()))
    engine.db.conn.commit()
    run_forgetting(engine)
    assert _exists(engine, node_id) is True


def test_strong_edge_protects_hub(engine):
    """Fails gate #6 (strong edge)."""
    _enable(engine)
    a = _make_eligible(engine, content="hub a")
    b = _make_eligible(engine, content="hub b")
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to, weight=0.9))
    run_forgetting(engine)
    assert _exists(engine, a) is True
    assert _exists(engine, b) is True


def test_working_tier_never_touched(engine):
    """Fails gate #1."""
    _enable(engine)
    node_id, _ = engine.remember(CreateNodeRequest(
        content="active", type=NodeType.fact, tier=Tier.working, title="active"))
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET importance=0.1, stability=1.0, last_review=?, last_accessed=? WHERE id=?",
        (old, old, node_id))
    engine.db.conn.commit()
    run_forgetting(engine)
    assert _exists(engine, node_id) is True


def test_user_node_never_deleted(engine):
    _enable(engine)
    # the self node is created at startup; force it to look eligible
    uid = engine.user_node_id
    assert uid is not None
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET tier='archival', importance=0.1, stability=1.0, "
        "last_review=?, last_accessed=?, archived_at=? WHERE id=?",
        (old, old, old, uid))
    engine.db.conn.commit()
    run_forgetting(engine)
    assert _exists(engine, uid) is True


def test_idempotent_second_run_deletes_nothing(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    run_forgetting(engine)  # nothing new eligible
    assert _exists(engine, node_id) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the module**

Create `src/ormah/background/forgetting_manager.py`:

```python
"""Bounded forgetting (#28): delete dead-weight archival nodes via conjunction gates.

Two phases per run, both behind the master switch ``deletion_enabled`` (default OFF):
  A. apply §1 gates → soft-delete eligible archival nodes (+ §3 cap backstop, task 06);
  B. hard-purge tombstones past the retention window (task 07).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def run_forgetting(engine) -> None:
    """Soft-delete dead-weight archival nodes, then purge expired tombstones."""
    settings = engine.settings
    if not settings.deletion_enabled:
        return  # opt-in; the graveyard is left untouched until explicitly armed
    try:
        now = datetime.now(timezone.utc)

        eligible = _eligible_for_deletion(engine, now)
        deleted = 0
        for node_id in eligible:
            if engine.delete_node(node_id):
                deleted += 1
        if deleted:
            logger.info("Forgetting soft-deleted %d archival nodes", deleted)

        # Task 06 inserts the §3 cap backstop here.
        # Task 07 inserts Phase B (hard-purge) here.

    except Exception as e:
        logger.warning("Forgetting manager failed: %s", e)


def _eligible_for_deletion(engine, now: datetime) -> list[str]:
    """Return archival node ids that satisfy ALL §1 gates."""
    s = engine.settings
    cutoff = (now - timedelta(days=s.deletion_min_archival_days)).isoformat()

    # Cheap predicates in SQL: archival tail, low importance, sustained staleness.
    rows = engine.db.conn.execute(
        """
        SELECT id, importance, stability, last_review, last_accessed, archived_at
        FROM nodes
        WHERE tier = 'archival'
          AND COALESCE(importance, 0.5) < ?
          AND archived_at IS NOT NULL
          AND archived_at <= ?
          AND last_accessed <= ?
        """,
        (s.decay_importance_threshold, cutoff, cutoff),
    ).fetchall()

    user_id = getattr(engine, "user_node_id", None)
    eligible: list[str] = []
    for row in rows:
        if row["id"] == user_id:
            continue  # gate #7: never the self node
        if _retrievability(row, now) >= s.deletion_retrievability_floor:
            continue  # gate #3
        if _has_positive_feedback(engine, row["id"]):
            continue  # gate #5
        degree, max_weight = _connectivity(engine, row["id"])
        if degree > s.deletion_max_degree or max_weight >= s.deletion_strong_edge_weight:
            continue  # gate #6
        eligible.append(row["id"])
    return eligible


def _retrievability(row, now: datetime) -> float:
    """FSRS retrievability R = exp(-days_since_anchor / stability). 1.0 if uncomputable."""
    stability = row["stability"] if row["stability"] else 1.0
    anchor_str = row["last_review"] or row["last_accessed"]
    try:
        anchor = datetime.fromisoformat(anchor_str)
    except (ValueError, TypeError):
        return 1.0  # cannot compute → treat as fully retrievable (protect)
    days_since = max((now - anchor).total_seconds() / 86400, 0.001)
    return math.exp(-days_since / stability)


def _has_positive_feedback(engine, node_id: str) -> bool:
    """Gate #5: any submit_feedback(+1) / positive affinity protects forever."""
    row = engine.db.conn.execute(
        "SELECT 1 FROM affinity WHERE node_id = ? AND signal > 0 LIMIT 1", (node_id,)
    ).fetchone()
    return row is not None


def _connectivity(engine, node_id: str) -> tuple[int, float]:
    """Return (degree, max_edge_weight) over all edges touching the node."""
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree, COALESCE(MAX(weight), 0) AS max_w "
        "FROM edges WHERE source_id = ? OR target_id = ?",
        (node_id, node_id),
    ).fetchone()
    return row["degree"], row["max_w"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git add src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git commit -m "feat(background): forgetting manager gates + soft-delete (#28)"
```

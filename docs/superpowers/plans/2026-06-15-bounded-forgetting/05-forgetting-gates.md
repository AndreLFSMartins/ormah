# Task 05: Forgetting manager — Phase A gates → soft-delete

**Depends on:** Tasks 01, 02, 03, 04.

Create the new job module. Phase A selects `archival` candidates, applies the §1 gates split
into two predicates, and soft-deletes the eligible ones via `engine.delete_node`. The whole job
is a no-op when `deletion_enabled=False`.

## Council R1 design decisions baked in

- **Single source of protection (`_is_protected`).** The §1 gates split into **protections**
  (hard "never delete": self node, `archived_at IS NULL`, importance ≥ threshold, positive
  feedback, hub/strong-edge, degree > max) and **staleness signals** (`archived_at` old,
  `last_accessed` old, `R < floor`). Phase A requires *not protected AND stale*. Task 06's cap
  reuses **the exact same `_is_protected`** — so the cap can never delete a protected node
  (council C1). `archived_at IS NULL` counts as protected, closing the `remember(tier=archival)`
  hole (council H3).
- **Revalidate immediately before delete (council C2).** Eligibility is recomputed per-node from
  a *fresh* row read right before `delete_node`, because background jobs run concurrently — a
  node may be recalled / promoted / connected / get feedback between selection and deletion.
- **Robust success check (council L1).** `delete_node` returns `str | None`; treat success only
  when the message starts with `"Deleted"`.

**Files:**
- Create: `src/ormah/background/forgetting_manager.py`
- Test: `tests/test_background/test_forgetting_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_forgetting_manager.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ormah.background.forgetting_manager import run_forgetting
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier


def _exists(engine, node_id) -> bool:
    row = engine.db.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row is not None


def _enable(engine):
    engine.settings.deletion_enabled = True


def _make_eligible(engine, content="dead weight", days=200):
    """Create an archival node that passes every gate (not protected + stale)."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content=content, type=NodeType.fact, tier=Tier.archival, title=content))
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET tier='archival', importance=0.1, stability=1.0, "
        "last_review=?, last_accessed=?, archived_at=? WHERE id=?",
        (old, old, old, node_id))
    engine.db.conn.commit()
    return node_id


def test_master_switch_off_is_noop(engine):
    node_id = _make_eligible(engine)
    run_forgetting(engine)  # deletion_enabled defaults to False
    assert _exists(engine, node_id) is True


def test_fully_eligible_node_is_soft_deleted(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    assert _exists(engine, node_id) is False


def test_idempotent_second_run_deletes_nothing(engine):
    _enable(engine)
    node_id = _make_eligible(engine)
    run_forgetting(engine)
    run_forgetting(engine)
    assert _exists(engine, node_id) is False


# --- conjunction matrix: passing all gates deletes; breaking exactly one keeps (council M1) ---

def _break(engine, node_id, gate):
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    if gate == "tier":
        engine.db.conn.execute("UPDATE nodes SET tier='working' WHERE id=?", (node_id,))
    elif gate == "archived_recent":
        engine.db.conn.execute("UPDATE nodes SET archived_at=? WHERE id=?", (recent, node_id))
    elif gate == "accessed_recent":
        engine.db.conn.execute("UPDATE nodes SET last_accessed=? WHERE id=?", (recent, node_id))
    elif gate == "retrievable":   # high stability ⇒ R well above floor
        engine.db.conn.execute("UPDATE nodes SET stability=100000.0 WHERE id=?", (node_id,))
    elif gate == "importance":
        engine.db.conn.execute("UPDATE nodes SET importance=0.9 WHERE id=?", (node_id,))
    elif gate == "archived_null":
        engine.db.conn.execute("UPDATE nodes SET archived_at=NULL WHERE id=?", (node_id,))
    elif gate == "feedback":
        engine.db.conn.execute(
            "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
            "VALUES (?, ?, 1, 'explicit', ?, 's1')", (b"\x00", node_id, recent))
    engine.db.conn.commit()


@pytest.mark.parametrize("gate", [
    "tier", "archived_recent", "accessed_recent", "retrievable",
    "importance", "archived_null", "feedback",
])
def test_breaking_one_gate_keeps_node(engine, gate):
    _enable(engine)
    node_id = _make_eligible(engine)
    _break(engine, node_id, gate)
    run_forgetting(engine)
    assert _exists(engine, node_id) is True, f"gate={gate} should have protected the node"


def test_strong_edge_protects_both_nodes(engine):
    _enable(engine)
    a = _make_eligible(engine, content="hub a")
    b = _make_eligible(engine, content="hub b")
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to, weight=0.9))
    run_forgetting(engine)
    assert _exists(engine, a) is True and _exists(engine, b) is True


def test_user_node_never_deleted(engine):
    _enable(engine)
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
    if not engine.settings.deletion_enabled:
        return  # opt-in; the graveyard is untouched until explicitly armed
    try:
        now = datetime.now(timezone.utc)
        _run_gate_phase(engine, now)
        # Task 06 inserts the §3 cap backstop here.
        # Task 07 inserts Phase B (hard-purge) here.
    except Exception as e:
        logger.warning("Forgetting manager failed: %s", e)


def _run_gate_phase(engine, now: datetime) -> int:
    """Phase A: soft-delete archival nodes that are not protected AND are stale."""
    s = engine.settings
    candidates = [
        row["id"] for row in _archival_rows(engine)
        if not _is_protected(engine, row, now) and _is_stale_eligible(s, row, now)
    ]
    deleted = 0
    for node_id in candidates:
        row = _fetch_row(engine, node_id)  # re-read fresh (council C2)
        if row is None:
            continue
        if _is_protected(engine, row, now) or not _is_stale_eligible(s, row, now):
            continue  # state changed since selection — skip
        result = engine.delete_node(node_id)
        if result and result.startswith("Deleted"):
            deleted += 1
    if deleted:
        logger.info("Forgetting soft-deleted %d archival nodes", deleted)
    return deleted


# --- shared gate predicates -------------------------------------------------

_ROW_COLS = "id, importance, stability, last_review, last_accessed, archived_at"


def _archival_rows(engine):
    return engine.db.conn.execute(
        f"SELECT {_ROW_COLS} FROM nodes WHERE tier = 'archival'"
    ).fetchall()


def _fetch_row(engine, node_id: str):
    return engine.db.conn.execute(
        f"SELECT {_ROW_COLS} FROM nodes WHERE id = ? AND tier = 'archival'", (node_id,)
    ).fetchone()


def _is_protected(engine, row, now: datetime) -> bool:
    """§1 hard protections — a True here means NEVER delete (Phase A and the cap both honor it)."""
    s = engine.settings
    if row["id"] == getattr(engine, "user_node_id", None):
        return True                                   # gate #7: self node
    if row["archived_at"] is None:
        return True                                   # un-aged (e.g. remember(tier=archival))
    importance = row["importance"] if row["importance"] is not None else 0.5
    if importance >= s.decay_importance_threshold:
        return True                                   # gate #4: high importance
    if _has_positive_feedback(engine, row["id"]):
        return True                                   # gate #5: ever positively useful
    degree, max_weight = _connectivity(engine, row["id"])
    if degree > s.deletion_max_degree or max_weight >= s.deletion_strong_edge_weight:
        return True                                   # gate #6: hub / strong edge
    return False


def _is_stale_eligible(s, row, now: datetime) -> bool:
    """§1 staleness signals — sustained dead weight. NOT protections (the cap skips these)."""
    cutoff = now - timedelta(days=s.deletion_min_archival_days)
    if _parse_dt(row["archived_at"]) > cutoff:
        return False                                  # gate #2: in graveyard long enough
    if _parse_dt(row["last_accessed"]) > cutoff:
        return False                                  # gate #2: not re-accessed
    if _retrievability(row, now) >= s.deletion_retrievability_floor:
        return False                                  # gate #3: R below the floor
    return True


def _retrievability(row, now: datetime) -> float:
    """FSRS retrievability R = exp(-days_since_anchor / stability). 1.0 if uncomputable."""
    stability = row["stability"] if row["stability"] else 1.0
    anchor_str = row["last_review"] or row["last_accessed"]
    try:
        anchor = datetime.fromisoformat(anchor_str)
    except (ValueError, TypeError):
        return 1.0
    days_since = max((now - _aware(anchor)).total_seconds() / 86400, 0.001)
    return math.exp(-days_since / stability)


def _has_positive_feedback(engine, node_id: str) -> bool:
    row = engine.db.conn.execute(
        "SELECT 1 FROM affinity WHERE node_id = ? AND signal > 0 LIMIT 1", (node_id,)
    ).fetchone()
    return row is not None


def _connectivity(engine, node_id: str) -> tuple[int, float]:
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree, COALESCE(MAX(weight), 0) AS max_w "
        "FROM edges WHERE source_id = ? OR target_id = ?",
        (node_id, node_id),
    ).fetchone()
    return row["degree"], row["max_w"]


def _parse_dt(value: str) -> datetime:
    return _aware(datetime.fromisoformat(value))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -v`
Expected: PASS (all tests, including the 7-gate conjunction matrix).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git add src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git commit -m "feat(background): forgetting manager gates + soft-delete (#28)"
```

"""Bounded forgetting (#28): delete dead-weight archival nodes via conjunction gates.

Two phases per run, both behind the master switch ``deletion_enabled`` (default OFF):
  A. apply §1 gates → soft-delete eligible archival nodes (+ §3 cap backstop, task 06);
  B. hard-purge tombstones past the retention window (task 07).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from ormah.models.node import Tier

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
        if engine.delete_node_guarded(node_id, _eligibility_guard(engine, node_id, now)):
            deleted += 1
    if deleted:
        logger.info("Forgetting soft-deleted %d archival nodes", deleted)
    return deleted


def _hybrid_row(engine, node_id: str, conn):
    """A fresh gate row reading volatile fields from the SOURCE FILE, not the lagging index.

    Council R3 C5: mutators (`update_node`, `_touch_access`) write the markdown file BEFORE the
    index, so a guard reading only the index can see stale tier/last_accessed and delete a node
    mid-promotion. The file is authoritative for tier / last_accessed / archived_at / FSRS fields.
    `importance` stays index-authoritative (importance_scorer writes the index directly), and
    affinity/edges are read via conn (serialized by BEGIN IMMEDIATE). Returns None if the file is
    gone or no longer archival.
    """
    node = engine.file_store.load(node_id)
    if node is None or node.tier != Tier.archival:
        return None
    irow = conn.execute("SELECT importance FROM nodes WHERE id = ?", (node_id,)).fetchone()
    importance = irow["importance"] if irow and irow["importance"] is not None else node.importance
    return {
        "id": node.id,
        "importance": importance,
        "stability": node.stability,
        "last_review": node.last_review.isoformat() if node.last_review else None,
        "last_accessed": node.last_accessed.isoformat(),
        "archived_at": node.archived_at.isoformat() if node.archived_at else None,
    }


def _eligibility_guard(engine, node_id: str, now: datetime):
    """Build a guard(conn) that re-validates the gates from the source file inside the txn."""
    s = engine.settings

    def guard(conn) -> bool:
        row = _hybrid_row(engine, node_id, conn)
        if row is None:
            return False  # promoted / recalled-out / gone since selection
        return not _is_protected(engine, row, now) and _is_stale_eligible(s, row, now)

    return guard


# --- shared gate predicates -------------------------------------------------

_ROW_COLS = "id, importance, stability, last_review, last_accessed, archived_at"


def _archival_rows(engine):
    return engine.db.conn.execute(
        f"SELECT {_ROW_COLS} FROM nodes WHERE tier = 'archival'"
    ).fetchall()


def _evaluate_protection(engine, row, now: datetime) -> tuple[bool, int]:
    """§1 hard protections — single source of truth, computing connectivity at most once.

    Returns ``(protected, degree)``. ``protected`` True means NEVER delete (Phase A and the cap
    both honor it). ``degree`` is returned so the cap's forget-score never recomputes it (H5).
    Cheap protections short-circuit before the edge query, so Phase A stays cheap for the common
    high-importance / feedback cases.
    """
    s = engine.settings
    if row["id"] == getattr(engine, "user_node_id", None):
        return True, 0                                # gate #7: self node
    if row["archived_at"] is None:
        return True, 0                                # un-aged (e.g. remember(tier=archival))
    importance = row["importance"] if row["importance"] is not None else 0.5
    if importance >= s.decay_importance_threshold:
        return True, 0                                # gate #4: high importance
    if _has_positive_feedback(engine, row["id"]):
        return True, 0                                # gate #5: ever positively useful
    degree, max_weight = _connectivity(engine, row["id"])
    if degree > s.deletion_max_degree or max_weight >= s.deletion_strong_edge_weight:
        return True, degree                           # gate #6: hub / strong edge
    return False, degree


def _is_protected(engine, row, now: datetime) -> bool:
    return _evaluate_protection(engine, row, now)[0]


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

"""FSRS retrievability-based tier demotion for stale working memories."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from ormah.background.memory_lock import serialized_memory_job
from ormah.models.node import Tier, UpdateNodeRequest

logger = logging.getLogger(__name__)


@serialized_memory_job
def run_decay(engine) -> None:
    """Auto-demote working nodes whose FSRS retrievability drops below threshold.

    Retrievability alone decides (#222/#191). Importance is deliberately not a
    pre-gate: cumulative access and edge counts could push it permanently above
    any threshold, pinning a stale node to working forever. Identity (the self
    node) and core stay protected — core never enters this query.
    """
    try:
        settings = engine.settings
        now = datetime.now(timezone.utc)

        # One-time cleanup: remove legacy pending decay proposals
        with engine.db.transaction() as conn:
            conn.execute(
                "DELETE FROM proposals WHERE type = 'decay' AND status = 'pending'"
            )

        rows = engine.db.conn.execute(
            "SELECT id, stability, last_review, last_accessed "
            "FROM nodes WHERE tier = 'working'"
        ).fetchall()

        if not rows:
            return

        user_node_id = getattr(engine, "user_node_id", None)
        r_threshold = settings.fsrs_decay_threshold

        demoted = 0
        for row in rows:
            if row["id"] == user_node_id:
                continue

            # Compute FSRS retrievability
            stability = row["stability"] if row["stability"] else 1.0
            anchor_str = row["last_review"] or row["last_accessed"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
            except (ValueError, TypeError):
                continue
            days_since = max((now - anchor).total_seconds() / 86400, 0.001)
            retrievability = math.exp(-days_since / stability)

            if retrievability >= r_threshold:
                continue

            result = engine.update_node(row["id"], UpdateNodeRequest(tier=Tier.archival))
            if result:
                demoted += 1

        if demoted:
            logger.info("Decay manager demoted %d nodes to archival", demoted)

    except Exception as e:
        logger.warning("Decay manager failed: %s", e)

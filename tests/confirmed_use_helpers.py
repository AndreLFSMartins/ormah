"""Shared helpers for calling the confirmed-use mutator directly from a test.

Issue #272 made ``whisper_log_id`` a required keyword on
``MemoryEngine._record_confirmed_use`` and put the call behind an at-most-once
claim: the mutator now returns without doing anything unless a ``pending`` claim
exists for that (event, node) pair. Every production caller reaches it only after
``_claim_confirmed_use`` has taken that claim, so a direct call from a test needs
the same shape.

These two helpers are the shape. ``tests/test_engine/test_confirmed_use_contract.py``
carries its own private copies — that file is the upstream contribution and stays
self-contained; this module exists for the local-main-only suites (#223 reversible
promotion, #28 archived_at, the audit log, the #221 cooldown) that predate #272 and
whose call sites the upstream branch never saw.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def claim_fresh_event(engine, node_id: str) -> int:
    """Insert a whisper_log row for *node_id* and take its confirmed-use claim.

    Bypasses ``recall_search`` deliberately, so a test that calls the mutator
    several times on one node gets one fresh, independently-claimable event per
    call rather than depending on search surfacing the same node again.
    """
    with engine.db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO whisper_log "
            "(session_id, prompt_hash, prompt_vec, node_id, score, was_injected, logged_at) "
            "VALUES ('test-direct-claim', ?, X'00', ?, 1.0, 1, datetime('now'))",
            (uuid.uuid4().hex, node_id),
        )
        whisper_log_id = cursor.lastrowid
        engine._claim_confirmed_use(
            conn, whisper_log_id, node_id, signal=1, source="explicit", strength=1.0,
        )
        # _claim_confirmed_use stamps claimed_at with SQL datetime('now'), which
        # truncates to whole seconds. The mutator's clock IS claimed_at, so a test
        # calling reinforce() several times faster than 1 s apart would see identical
        # timestamps — and near an exact cooldown-day boundary that truncation alone
        # can flip `reinforcement_due`. Overwritten with microsecond precision.
        conn.execute(
            "UPDATE confirmed_use_claims SET claimed_at = ? "
            "WHERE whisper_log_id = ? AND node_id = ?",
            (datetime.now(timezone.utc).isoformat(), whisper_log_id, node_id),
        )
    return whisper_log_id


def reinforce(engine, node_id: str) -> None:
    """Claim a fresh event for *node_id* and reinforce it in one step.

    The direct replacement for the pre-#272 ``engine._record_confirmed_use(node_id)``
    call shape, for tests that exercise the mutator's lifecycle arithmetic rather
    than the claiming path itself.
    """
    engine._record_confirmed_use(
        node_id, whisper_log_id=claim_fresh_event(engine, node_id)
    )

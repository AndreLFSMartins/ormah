"""Per-day cooldown on numeric stability updates (#221)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ormah.models.node import CreateNodeRequest, NodeType, Tier


def _row(engine, node_id: str):
    return engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()


def _make_node(engine) -> str:
    node_id, _ = engine.remember(CreateNodeRequest(
        content="A node whose reinforcement we are measuring",
        type=NodeType.fact,
        tier=Tier.working,
        title="Cooldown subject",
    ))
    return node_id


def _backdate_review(engine, node_id: str, days: float) -> None:
    """Move both timestamps back so the next touch is off cooldown."""
    when = datetime.now(timezone.utc) - timedelta(days=days)
    node = engine.file_store.load(node_id)
    node.last_review = when
    node.last_accessed = when
    engine.file_store.save(node)
    engine.db.conn.execute(
        "UPDATE nodes SET last_review = ?, last_accessed = ? WHERE id = ?",
        (when.isoformat(), when.isoformat(), node_id),
    )
    engine.db.conn.commit()


def test_ten_touches_in_one_day_produce_one_stability_update(engine):
    """AC4: ten uses, one numeric update, and the latest use time is recorded."""
    node_id = _make_node(engine)
    engine._touch_access(node_id)

    after_first = _row(engine, node_id)
    for _ in range(9):
        engine._touch_access(node_id)
    after_ten = _row(engine, node_id)

    assert after_ten["stability"] == after_first["stability"]
    assert after_ten["last_review"] == after_first["last_review"]
    assert after_ten["access_count"] == after_first["access_count"] + 9
    assert after_ten["last_accessed"] > after_first["last_accessed"]


def test_a_touch_after_the_cooldown_moves_stability_again(engine):
    node_id = _make_node(engine)
    engine._touch_access(node_id)
    before = _row(engine, node_id)

    _backdate_review(engine, node_id, days=1.0)
    engine._touch_access(node_id)
    after = _row(engine, node_id)

    assert after["stability"] > before["stability"]
    assert after["last_review"] > before["last_review"]


def test_a_thirty_day_old_node_is_bounded_to_double(engine):
    """AC1 end to end: the unbounded formula produced ~202.7 here."""
    node_id = _make_node(engine)
    node = engine.file_store.load(node_id)
    node.stability = 1.0
    engine.file_store.save(node)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()
    _backdate_review(engine, node_id, days=30.0)

    engine._touch_access(node_id)

    assert _row(engine, node_id)["stability"] == 2.0


def test_the_cooldown_does_not_freeze_the_decay_anchor(engine):
    """last_accessed must keep moving so decay never sees an active node as stale."""
    node_id = _make_node(engine)
    engine._touch_access(node_id)
    first = _row(engine, node_id)

    engine._touch_access(node_id)
    second = _row(engine, node_id)

    assert second["last_accessed"] >= first["last_accessed"]
    assert second["last_review"] == first["last_review"]


def test_reinforcement_survives_a_zero_stability_node(engine):
    """Node.stability is ge=0.0; exp(-t/0) used to raise ZeroDivisionError."""
    node_id = _make_node(engine)
    node = engine.file_store.load(node_id)
    node.stability = 0.0
    engine.file_store.save(node)
    engine.db.conn.execute("UPDATE nodes SET stability = 0.0 WHERE id = ?", (node_id,))
    engine.db.conn.commit()

    engine._touch_access(node_id)

    assert _row(engine, node_id)["stability"] > 0.0


def test_concurrent_touches_still_produce_one_stability_update(engine):
    """AC4 under concurrency (council round 3, I1).

    The sequential ten-touch test above cannot see this: it is the *interleaving*
    that breaks the cooldown. Both threads read last_review before either writes
    it, both conclude they are off cooldown, and both bump. The recall paths that
    reach _touch_access carry no @_serialized_memory_operation, so this is the
    real production shape, not a synthetic one.

    Barrier, not a bare thread pair: without it the two threads can serialize by
    luck and the test greens on the broken code. The barrier forces both past the
    cooldown read before either proceeds.
    """
    import threading

    node_id = _make_node(engine)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, last_review = NULL WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()
    node = engine.file_store.load(node_id)
    node.stability = 1.0
    node.last_review = None
    engine.file_store.save(node)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _touch() -> None:
        try:
            barrier.wait(timeout=5)
            engine._touch_access(node_id)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` below
            errors.append(exc)

    threads = [threading.Thread(target=_touch) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"a touch thread raised: {errors}"
    row = _row(engine, node_id)
    # One bump from S=1.0, never two. The second bump would compound past this.
    assert row["stability"] == pytest.approx(1.5)
    assert row["access_count"] == 2, "both touches must still be counted"

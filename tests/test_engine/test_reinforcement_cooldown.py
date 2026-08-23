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
    engine._record_confirmed_use(node_id)

    after_first = _row(engine, node_id)
    for _ in range(9):
        engine._record_confirmed_use(node_id)
    after_ten = _row(engine, node_id)

    assert after_ten["stability"] == after_first["stability"]
    assert after_ten["last_review"] == after_first["last_review"]
    assert after_ten["access_count"] == after_first["access_count"] + 9
    assert after_ten["last_accessed"] > after_first["last_accessed"]


def test_a_touch_after_the_cooldown_moves_stability_again(engine):
    node_id = _make_node(engine)
    engine._record_confirmed_use(node_id)
    before = _row(engine, node_id)

    _backdate_review(engine, node_id, days=1.0)
    engine._record_confirmed_use(node_id)
    after = _row(engine, node_id)

    assert after["stability"] > before["stability"]
    assert after["last_review"] > before["last_review"]


def test_reinforcement_anchors_on_last_accessed_not_a_lagging_last_review(engine):
    """A confirmed use inside the cooldown must not be invisible to the spacing calc.

    last_review gates *whether* the numeric update runs; last_accessed is the last
    confirmed use. When they diverge (a use landed inside the cooldown, so it moved
    last_accessed but not last_review), the growth calculation must measure the gap
    since that last use, not since the last numeric write (PR #239 review comment).
    """
    node_id = _make_node(engine)
    node = engine.file_store.load(node_id)
    node.stability = 1.0
    now = datetime.now(timezone.utc)
    node.last_review = now - timedelta(hours=25)
    node.last_accessed = now - timedelta(hours=1)
    engine.file_store.save(node)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, last_review = ?, last_accessed = ? WHERE id = ?",
        (node.last_review.isoformat(), node.last_accessed.isoformat(), node_id),
    )
    engine.db.conn.commit()

    engine._record_confirmed_use(node_id)

    assert _row(engine, node_id)["stability"] == pytest.approx(1.50, abs=0.01)


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

    engine._record_confirmed_use(node_id)

    assert _row(engine, node_id)["stability"] == 2.0


def test_the_cooldown_does_not_freeze_the_decay_anchor(engine):
    """last_accessed must keep moving so decay never sees an active node as stale."""
    node_id = _make_node(engine)
    engine._record_confirmed_use(node_id)
    first = _row(engine, node_id)

    engine._record_confirmed_use(node_id)
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

    engine._record_confirmed_use(node_id)

    assert _row(engine, node_id)["stability"] > 0.0


def test_concurrent_touches_run_reinforcement_once(engine, monkeypatch):
    """AC4 under concurrency (council round 3 I1; test rebuilt after task review).

    The sequential ten-touch test cannot see this: it is the *interleaving* that
    breaks the cooldown. Both threads read last_review before either writes it,
    both conclude they are off cooldown, and both reinforce. On this branch
    _record_confirmed_use carries @_serialized_memory_operation precisely to close
    that window (#220's at-most-once latch is per whisper event, not per node, so
    it does not do this on its own) -- this test is what proves the decorator is
    load-bearing: Step 6 removes it and watches the race reappear.

    TWO construction choices, both load-bearing — read before editing:

    1. A DELAY widens the window; a Barrier would deadlock. Synchronizing the
       threads *inside* the critical section only works while the section is
       unguarded: once @_serialized_memory_operation is in place the second
       thread cannot enter until the first leaves, so a barrier there would time
       out on correct code. A sleep does not synchronize, so it is safe in both
       states — it just makes the unguarded race overwhelmingly likely.

    2. The assertion COUNTS reinforcements; it cannot be the final stability.
       Both threads read S=1.0 and both write 1.5 — the same value. Compounding
       to 2.25 needs read-after-write, which is the serialization the bug
       removes, so `stability == 1.5` holds whether the race fired or not. The
       number of reinforced_stability calls is the only signal that separates
       one bump from two.
    """
    import threading
    import time

    from ormah import lifecycle

    node_id = _make_node(engine)
    node = engine.file_store.load(node_id)
    node.stability = 1.0
    node.last_review = None
    engine.file_store.save(node)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, last_review = NULL WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    reinforcements: list[float] = []
    real_due = lifecycle.reinforcement_due
    real_reinforce = lifecycle.reinforced_stability
    lock = threading.Lock()

    def _slow_due(last_review, now, cooldown_days):
        verdict = real_due(last_review, now, cooldown_days)
        time.sleep(0.05)  # widen the check-then-write window
        return verdict

    def _counting_reinforce(*args, **kwargs):
        with lock:
            reinforcements.append(1.0)
        return real_reinforce(*args, **kwargs)

    import ormah.engine.memory_engine as engine_module

    monkeypatch.setattr(engine_module.lifecycle, "reinforcement_due", _slow_due)
    monkeypatch.setattr(engine_module.lifecycle, "reinforced_stability", _counting_reinforce)

    errors: list[BaseException] = []

    def _touch() -> None:
        try:
            engine._record_confirmed_use(node_id)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` below
            errors.append(exc)

    threads = [threading.Thread(target=_touch) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"a touch thread raised: {errors}"
    assert not [t for t in threads if t.is_alive()], "a touch thread never finished"
    assert len(reinforcements) == 1, (
        f"cooldown ran reinforcement {len(reinforcements)} times under concurrency"
    )
    assert _row(engine, node_id)["access_count"] == 4, "every touch must still be counted"


# --- Interaction with reversible promotion (#223) ---------------------------

def test_bounded_update_runs_before_the_floor(engine):
    """Archival, S=1, last used 30d ago -> 5.814.

    The bounded update gives 1 -> 2.0 (spacing saturates at cap 2.0); the floor
    then lifts 2.0 -> 5.814. The INVERTED order would give ~8.23
    (5.814 * (1 + 0.5 * 5.814**-0.5 * 2.0)), so equality at 5.814 catches it.
    Since e13d733 the spacing anchor is last_accessed (last_review only opens
    the cooldown gate), so both are backdated.
    """
    node_id, _ = engine.remember(CreateNodeRequest(content="an old archived memory"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_accessed = node.last_review = datetime.now(timezone.utc) - timedelta(days=30)
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)

    promoted = engine.file_store.load(node_id)
    assert promoted.stability == 5.814
    assert promoted.tier is Tier.working


def test_floor_applies_even_when_the_cooldown_blocked_the_numeric_update(engine):
    """Asserting only tier == working passes WITH the bug — and the node would
    re-archive in ~29 h on S=1. The stability assertion is the real gate."""
    node_id, _ = engine.remember(CreateNodeRequest(content="recently reviewed, archived"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_review = datetime.now(timezone.utc)   # on cooldown
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)

    promoted = engine.file_store.load(node_id)
    assert promoted.tier is Tier.working
    assert promoted.stability == 5.814


def test_the_floor_does_not_stack_across_two_uses_in_one_day(engine):
    """Two confirmed uses in one day -> 5.814, not 11.628 and not 6.814."""
    node_id, _ = engine.remember(CreateNodeRequest(content="used twice today"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_review = datetime.now(timezone.utc)
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)
    engine._record_confirmed_use(node_id)

    assert engine.file_store.load(node_id).stability == 5.814

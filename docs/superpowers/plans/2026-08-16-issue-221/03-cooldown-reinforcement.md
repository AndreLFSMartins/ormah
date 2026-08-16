# Task 3: Cooldown + bounded reinforcement in the engine

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1936-1960` (`_touch_access`)
- Create: `tests/test_engine/test_reinforcement_cooldown.py`

**Interfaces:**
- Consumes: `ormah.lifecycle.reinforcement_due` and `ormah.lifecycle.reinforced_stability` (Task 1); the four `Settings` fields from Task 2.
- Produces: no new public names. `_touch_access` keeps its signature `(self, node_id: str) -> None` and its five call sites (`memory_engine.py:646, 775, 811, 892, 938`) stay untouched.

**Behavior contract:** every call advances `last_accessed` and `access_count`. Only a call that is off cooldown changes `stability` and `last_review`.

**Note on #220:** PR #234 renames this method to `_record_confirmed_use` and adds its own zero-stability guard. On rebase, keep the new name and this task's body — the guard now lives in `lifecycle.py`.

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_reinforcement_cooldown.py`:

```python
"""Per-day cooldown on numeric stability updates (#221)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py -v`
Expected: FAIL. `test_ten_touches_in_one_day_produce_one_stability_update` fails because every touch still updates stability; `test_a_thirty_day_old_node_is_bounded_to_double` reports ~`202.7` instead of `2.0`; `test_reinforcement_survives_a_zero_stability_node` raises `ZeroDivisionError`.

- [ ] **Step 3: Add the import**

In `src/ormah/engine/memory_engine.py`, add to the existing `ormah` imports (alphabetical order within the block):

```python
from ormah import lifecycle
```

- [ ] **Step 4: Rewrite `_touch_access`**

Replace lines 1936-1960 entirely:

```python
    def _touch_access(self, node_id: str) -> None:
        """Update access stats, and FSRS stability when it is off cooldown."""
        node = self.file_store.load(node_id)
        if node is None:
            return
        now = datetime.now(timezone.utc)

        # One numeric stability update per node per cooldown window (#221): the
        # old formula let ten same-session touches compound to ~57x. The access
        # anchor below still advances on every call, so decay never mistakes an
        # actively used node for a stale one.
        if lifecycle.reinforcement_due(
            node.last_review, now, self.settings.fsrs_reinforcement_cooldown_days
        ):
            anchor = node.last_review or node.last_accessed
            days_since = max((now - anchor).total_seconds() / 86400, 0.0)
            node.stability = lifecycle.reinforced_stability(
                node.stability,
                days_since,
                growth_factor=self.settings.fsrs_growth_factor,
                growth_exponent=self.settings.fsrs_growth_exponent,
                spacing_cap=self.settings.fsrs_spacing_cap,
                max_stability=self.settings.fsrs_max_stability,
                initial_stability=self.settings.fsrs_initial_stability,
            )
            node.last_review = now

        # Standard access tracking
        node.last_accessed = now
        node.access_count += 1

        self.file_store.save(node)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE nodes SET access_count = ?, last_accessed = ?, stability = ?, "
                "last_review = ? WHERE id = ?",
                (
                    node.access_count,
                    node.last_accessed.isoformat(),
                    node.stability,
                    node.last_review.isoformat() if node.last_review else None,
                    node_id,
                ),
            )
```

Two deliberate changes beyond the formula swap: the `0.001` days floor is gone (the cooldown is what stops same-session compounding now), and `last_review` is written defensively as `None` when unset, because a node can now reach the write without ever being reinforced.

- [ ] **Step 5: Run the new tests**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run the suites that already exercised this path**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_mutation_stamping.py tests/test_engine/test_scoring_signals.py tests/test_store/test_file_store.py -v`
Expected: all pass unchanged. `test_touch_access_does_not_advance_updated` (`test_mutation_stamping.py:95`) is the important one — reinforcement must still not stamp `updated`.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_reinforcement_cooldown.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_reinforcement_cooldown.py
git commit -m "fix(lifecycle): bound stability growth and allow one update per node per day (#221)"
```

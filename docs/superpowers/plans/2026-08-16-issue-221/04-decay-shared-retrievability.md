# Task 4: Decay uses the shared retrievability and the use anchor

**Files:**
- Modify: `src/ormah/background/decay_manager.py:49-57`
- Modify: `tests/test_background/test_decay_manager.py` (append two tests)

**Interfaces:**
- Consumes: `ormah.lifecycle.retrievability` (Task 1).
- Produces: no new names. `run_decay(engine) -> None` is unchanged.

**Two changes:**

1. The inline `math.exp(-days_since / stability)` becomes `lifecycle.retrievability(...)` — one implementation shared with the reinforcement path (AC5).
2. The anchor flips from `last_review or last_accessed` to `last_accessed or last_review`. With the cooldown, `last_review` can lag the last use by a full cooldown window; anchoring decay on it would let an actively used node look stale. The two-way fallback stays so a row missing either column still decays instead of being skipped.

**Why existing tests stay green:** `_make_stale` (`test_decay_manager.py:13`) backdates `last_accessed` only, and nodes created by `engine.remember` have `last_review = NULL`. Both anchor orders resolve to `last_accessed` for those rows.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_decay_manager.py`:

```python
def test_decay_uses_the_shared_retrievability_implementation(engine, monkeypatch):
    """AC5: one exponential curve, shared with the reinforcement path."""
    from ormah.background import decay_manager

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Node whose retrievability we intercept",
        type=NodeType.fact,
        tier=Tier.working,
        title="Intercepted",
    ))
    _make_stale(engine, node_id)

    calls = []
    real = decay_manager.lifecycle.retrievability

    def _spy(days_since, stability, **kwargs):
        calls.append((days_since, stability))
        return real(days_since, stability, **kwargs)

    monkeypatch.setattr(decay_manager.lifecycle, "retrievability", _spy)
    run_decay(engine)

    assert calls, "run_decay computed retrievability without the shared helper"
    days_since, _stability = calls[0]
    assert days_since == pytest.approx(30, abs=1)


def test_a_node_used_today_is_not_decayed_while_its_review_lags(engine):
    """The cooldown can leave last_review a day behind; use must win the anchor."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Used today, reviewed yesterday",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh use, stale review",
    ))
    now = datetime.now(timezone.utc)
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, stability = 1.0 WHERE id = ?",
        (now.isoformat(), (now - timedelta(days=30)).isoformat(), node_id),
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"
```

Add `import pytest` to the file's imports if it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v`
Expected: the two new tests fail — the first with `AttributeError: module 'ormah.background.decay_manager' has no attribute 'lifecycle'`, the second by demoting the node to `archival`.

- [ ] **Step 3: Swap the import**

In `src/ormah/background/decay_manager.py`, replace `import math` with:

```python
from ormah import lifecycle
```

Keep it in the `ormah` import block with the existing `from ormah.background.memory_lock import serialized_memory_job`, above `from ormah.models.node import Tier, UpdateNodeRequest`.

- [ ] **Step 4: Rewrite the retrievability block**

Replace lines 49-57:

```python
            # Compute FSRS retrievability
            stability = row["stability"] if row["stability"] else 1.0
            anchor_str = row["last_review"] or row["last_accessed"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
            except (ValueError, TypeError):
                continue
            days_since = max((now - anchor).total_seconds() / 86400, 0.001)
            retrievability = math.exp(-days_since / stability)
```

with:

```python
            # Compute FSRS retrievability through the shared implementation (#221).
            # Anchor on use, not on the numeric stability update: the per-day
            # reinforcement cooldown can leave last_review a full window behind
            # the last use, and an actively used node must not read as stale.
            stability = row["stability"] if row["stability"] else 1.0
            anchor_str = row["last_accessed"] or row["last_review"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
            except (ValueError, TypeError):
                continue
            days_since = (now - anchor).total_seconds() / 86400
            retrievability = lifecycle.retrievability(days_since, stability)
```

The `0.001` floor is dropped: `lifecycle.retrievability` already clamps negative ages to `0`.

- [ ] **Step 5: Run the decay suite**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v`
Expected: all pass, including the pre-existing `test_low_importance_stale_node_decayed`, `test_decay_is_idempotent`, and `test_decay_writes_audit_log`.

- [ ] **Step 6: Confirm the duplicate formula is gone from this file**

Run: `grep -n "math.exp" src/ormah/background/decay_manager.py`
Expected: no output. `src/ormah/background/importance_scorer.py` keeps its own `math.exp` — that file belongs to #222 and is out of scope here.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/background/decay_manager.py tests/test_background/test_decay_manager.py
git add src/ormah/background/decay_manager.py tests/test_background/test_decay_manager.py
git commit -m "fix(decay): share one retrievability implementation and anchor on use (#221)"
```

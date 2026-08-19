# Task 2: Retrievability alone controls working → archival demotion

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:**
- Modify: `src/ormah/background/decay_manager.py:36-47`
- Modify: `src/ormah/config.py:265-266` (comment only)
- Test: `tests/test_background/test_decay_manager.py:29-46`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: no new symbols. `run_decay(engine)` keeps its signature.

- [ ] **Step 1: Rewrite the test that asserts the removed behavior**

In `tests/test_background/test_decay_manager.py`, replace `test_high_importance_node_not_decayed` (lines 29-46) entirely with:

```python
def test_high_importance_stale_node_is_decayed(engine):
    """#222: importance is no longer a pre-gate — a stale node decays regardless.

    Before #222 an importance >= decay_importance_threshold (0.5) node could never
    leave working, however stale it became.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Important stale node",
        type=NodeType.fact,
        tier=Tier.working,
        title="Important",
    ))

    _make_stale(engine, node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.9 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_accumulated_access_and_edges_do_not_pin_a_node_to_working(engine):
    """The reported case: 50 accesses + 4 edges produce a permanent non-recency
    importance contribution of ~0.514, above the old 0.5 gate. That node must
    still decay once it goes stale."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Hub node with long access history",
        type=NodeType.concept,
        tier=Tier.working,
        title="Hub",
    ))

    for i in range(4):
        sat_id, _ = engine.remember(CreateNodeRequest(
            content=f"Satellite of the hub number {i}",
            type=NodeType.fact,
            tier=Tier.working,
        ))
        engine.connect(ConnectRequest(
            source_id=node_id,
            target_id=sat_id,
            edge=EdgeType.related_to,
        ))

    engine.db.conn.execute(
        "UPDATE nodes SET access_count = 50, importance = 0.5145 WHERE id = ?",
        (node_id,),
    )
    engine.db.conn.commit()
    _make_stale(engine, node_id)

    run_decay(engine)

    assert _get_tier(engine, node_id) == "archival"


def test_fresh_high_importance_node_stays_working(engine):
    """The negative case (council I2): retrievability still decides.

    Removing the importance gate must not turn decay into "demote everything".
    A fresh node has R ~= 1.0 and stays working whatever its importance. Without
    this test, deleting the retrievability check would leave the suite green.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Fresh node that must not decay",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh",
    ))

    # Deliberately NOT made stale.
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.9 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"


def test_fresh_low_importance_node_stays_working(engine):
    """Same guard from the other side: low importance alone never demotes."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Fresh unimportant node that must not decay",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh unimportant",
    ))

    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.05 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"


def test_self_node_is_never_decayed(engine):
    """Identity protection survives the removal of the importance gate."""
    user_node_id = getattr(engine, "user_node_id", None)
    # Fail closed, not skip (council I2): the fixture does create a self node
    # (see test_forgetting_manager.test_user_node_never_deleted), so a missing
    # one means the fixture broke — silently skipping would hide that.
    assert user_node_id is not None, "engine fixture must provide a self node"

    _make_stale(engine, user_node_id)
    engine.db.conn.execute(
        "UPDATE nodes SET tier = 'working', importance = 0.1 WHERE id = ?",
        (user_node_id,),
    )
    engine.db.conn.commit()

    run_decay(engine)

    assert _get_tier(engine, user_node_id) == "working"
```

Update the imports at the top of the file (currently line 10) from:

```python
from ormah.models.node import CreateNodeRequest, NodeType, Tier
```

to:

```python
import pytest

from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier
```

(`import pytest` goes above the `from ormah...` imports, separated by a blank line, matching `test_importance_scorer.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_decay_manager.py -v
```

Expected: `test_high_importance_stale_node_is_decayed` and `test_accumulated_access_and_edges_do_not_pin_a_node_to_working` FAIL with `assert 'working' == 'archival'` — the importance gate is still skipping them. The two `fresh_*_stays_working` tests and `test_self_node_is_never_decayed` should already PASS (they assert behavior this task must preserve, not introduce).

- [ ] **Step 3: Remove the importance pre-gate**

In `src/ormah/background/decay_manager.py`, delete the line:

```python
        importance_threshold = settings.decay_importance_threshold
```

and delete this block from the loop:

```python
            # Skip high-importance nodes
            node_importance = row["importance"] if row["importance"] is not None else 0.5
            if node_importance >= importance_threshold:
                continue
```

Then narrow the row query — `importance` is no longer read. Change:

```python
        rows = engine.db.conn.execute(
            "SELECT id, importance, stability, last_review, last_accessed "
            "FROM nodes WHERE tier = 'working'"
        ).fetchall()
```

to:

```python
        rows = engine.db.conn.execute(
            "SELECT id, stability, last_review, last_accessed "
            "FROM nodes WHERE tier = 'working'"
        ).fetchall()
```

Finally, update the docstring of `run_decay` from:

```python
    """Auto-demote working nodes whose FSRS retrievability drops below threshold."""
```

to:

```python
    """Auto-demote working nodes whose FSRS retrievability drops below threshold.

    Retrievability alone decides (#222/#191). Importance is deliberately not a
    pre-gate: cumulative access and edge counts could push it permanently above
    any threshold, pinning a stale node to working forever. Identity (the self
    node) and core stay protected — core never enters this query.
    """
```

- [ ] **Step 4: Update the config comment**

In `src/ormah/config.py`, change lines 265-266 from:

```python
    # Decay: skip nodes above this importance
    decay_importance_threshold: float = 0.5
```

to:

```python
    # Bounded-forgetting protection: never delete an archival node above this
    # importance (forgetting_manager gate #4). No longer affects tier decay —
    # #222 made working->archival depend on retrievability alone. The rename to
    # match its surviving meaning belongs to #28/#31, which is gated on #223.
    decay_importance_threshold: float = 0.5
```

- [ ] **Step 5: Run the decay suite**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_decay_manager.py -v
```

Expected: all PASS, including the four untouched tests (`test_low_importance_stale_node_decayed`, `test_decay_still_works_without_importance`, `test_decay_is_idempotent`, `test_decay_writes_audit_log`) — their importance values were already below the old gate, so removing it cannot change their outcome.

- [ ] **Step 6: Verify no other production code lost a reader of `importance`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
grep -rn "decay_importance_threshold" src/
```

Expected: exactly two hits — `config.py` (the field) and `forgetting_manager.py:114` (gate #4). If `decay_manager.py` still appears, Step 3 was incomplete.

- [ ] **Step 7: Run the forgetting suite — its gate #4 must be untouched**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/ -k "forgetting" -v
```

Expected: same result as the Task 0 baseline (no new failures). This is the regression check that we did not disturb gated #28/#31 behavior.

- [ ] **Step 8: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
ruff check src/ormah/background/decay_manager.py src/ormah/config.py tests/test_background/test_decay_manager.py
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git add src/ormah/background/decay_manager.py src/ormah/config.py tests/test_background/test_decay_manager.py
git commit -m "fix(decay): retrievability alone controls working->archival demotion (#222)

Demotion required importance < decay_importance_threshold as well as
R < fsrs_decay_threshold. Importance mixes cumulative access and edge counts,
so 50 accesses + 4 edges (~0.514) exceeded the 0.5 gate permanently — such a
node could never leave working, however stale.

decay_importance_threshold stays: forgetting_manager reads it as gate #4 of
bounded forgetting (#28/#31, gated by #191). Comment updated to say so.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git show --stat HEAD
```

Expected: exactly 3 files.

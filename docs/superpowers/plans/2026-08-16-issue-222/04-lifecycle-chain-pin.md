# Task 2b: Pin the scorer → decay → forgetting coupling (council C1)

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:**
- Create: `tests/test_background/test_lifecycle_chain.py`

**Interfaces:**
- Consumes: `_recency_signal` behavior from Task 1 and the gate removal from Task 2.
- Produces: nothing consumed by later tasks.

> **What this task is and is not.** It does NOT fix the coupling — the fix edits
> `forgetting_manager.py`, which #191 gated and #31 owes a rebase on. It *documents* the real
> behavior with an executable test, so #31 inherits a failing-or-passing fact instead of a
> paragraph. If the assertion below turns out to be wrong when you run it, **do not adjust the
> production code** — record the actual outcome and report it.

- [ ] **Step 1: Write the chain test**

Create `tests/test_background/test_lifecycle_chain.py`:

```python
"""The three lifecycle jobs are coupled through the `importance` column, not through
any function call (council C1, #222).

`importance_scorer` writes importance; `forgetting_manager` gate #4 reads it
(`importance >= decay_importance_threshold`). The sleep cycle runs
importance_scorer -> ... -> decay_manager -> forgetting_manager in one pass
(`routes_admin._SLEEP_CYCLE_ORDER`), and `_run_cap_backstop` deliberately skips the
staleness gates ("staleness not required for the cap", forgetting_manager.py:221).

So #222's recency change can drop a node below gate #4, decay can demote it, and the
cap can evict it — all in the same pass. This test pins that behavior. The remedy
belongs to #28/#31.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ormah.background.decay_manager import run_decay
from ormah.background.forgetting_manager import run_forgetting
from ormah.background.importance_scorer import run_importance_scoring
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier


def _exists(engine, node_id) -> bool:
    row = engine.db.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row is not None


def _tier(engine, node_id) -> str | None:
    row = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return row["tier"] if row else None


def _boundary_node(engine, days: int = 130):
    """A node in the danger band the council identified: cumulative signals near 0.40,
    high stability, long unused. Under the OLD formula its FSRS recency inflated
    importance to ~0.50 (protected); under the new one it lands ~0.42."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Boundary node with long history and high stability",
        type=NodeType.concept,
        tier=Tier.working,
        title="Boundary",
    ))
    for i in range(2):
        sat_id, _ = engine.remember(CreateNodeRequest(
            content=f"Boundary satellite {i}", type=NodeType.fact, tier=Tier.working,
        ))
        engine.connect(ConnectRequest(
            source_id=node_id, target_id=sat_id, edge=EdgeType.related_to,
        ))

    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET access_count = 25, stability = 100.0, "
        "last_review = ?, last_accessed = ? WHERE id = ?",
        (old, old, node_id),
    )
    engine.db.conn.commit()
    return node_id


def test_boundary_node_importance_falls_below_gate_four(engine):
    """The premise of C1: the new recency formula drops this node under 0.5."""
    node_id = _boundary_node(engine)

    run_importance_scoring(engine)

    importance = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["importance"]

    assert importance < engine.settings.decay_importance_threshold, (
        f"expected the boundary node under gate #4 (0.5), got {importance}"
    )


def test_full_chain_with_deletion_disabled_is_safe(engine):
    """Default configuration: the node is demoted but never deleted."""
    node_id = _boundary_node(engine)

    run_importance_scoring(engine)
    run_decay(engine)
    run_forgetting(engine)  # deletion_enabled defaults to False

    assert _tier(engine, node_id) == "archival"
    assert _exists(engine, node_id) is True


def test_full_chain_with_cap_armed_can_evict_a_just_demoted_node(engine):
    """Council C1, pinned. With deletion and a tight archival cap armed — a supported
    #28 configuration — the cap can evict a node demoted in the SAME pass, because the
    cap path does not require staleness. The fix belongs to #28/#31, not here."""
    node_id = _boundary_node(engine)
    engine.settings.deletion_enabled = True
    engine.settings.archival_soft_cap = 1

    run_importance_scoring(engine)
    run_decay(engine)
    assert _tier(engine, node_id) == "archival", "precondition: decay demoted it"

    run_forgetting(engine)

    # Record the real outcome. If this node survives, the cap either found other
    # overflow victims or a hard protection held — either way, report the actual
    # result rather than editing production code to match the assertion.
    assert _exists(engine, node_id) is False, (
        "expected the just-demoted node to be cap-evicted (council C1). If it "
        "survived, capture why and report it — do NOT change forgetting_manager.py."
    )
```

- [ ] **Step 2: Run the chain test**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_lifecycle_chain.py -v
```

Expected: the first two PASS. The third pins C1 — **whatever it does, report the actual result verbatim**. If it fails, that is data about the cap's real behavior, not a bug to paper over. Do not modify `forgetting_manager.py` either way.

- [ ] **Step 3: If the third test does not behave as asserted**

Adjust the *test's* assertion to match observed reality and rewrite its docstring to state what actually happens, keeping the `#31` reference. Then note the discrepancy in the Task 4 report. Never change production code to satisfy it.

- [ ] **Step 4: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
ruff check tests/test_background/test_lifecycle_chain.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git add tests/test_background/test_lifecycle_chain.py
git commit -m "test(lifecycle): pin the scorer->decay->forgetting coupling (#222)

The three jobs are coupled through the importance column, not through calls:
gate #4 reads what the scorer writes, and the cap backstop skips the staleness
gates. #222's recency change can therefore drop a node below gate #4, demote it,
and make it cap-eligible in a single sleep-cycle pass.

Pins the behavior rather than fixing it — the remedy edits forgetting_manager,
which #191 gated until the lifecycle signals land (#28/#31).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git show --stat HEAD
```

Expected: exactly 1 file.

# Task 4: Decay and importance share one retrievability, anchored on use

**Files:**
- Modify: `src/ormah/background/decay_manager.py:49-57`
- Modify: `src/ormah/background/importance_scorer.py:78-86`
- Modify: `tests/test_background/test_decay_manager.py` (append two tests)
- Modify: `tests/test_background/test_importance_scorer.py` (append one test)

**Interfaces:**
- Consumes: `ormah.lifecycle.retrievability` (Task 1).
- Produces: no new names. `run_decay(engine) -> None` is unchanged.

**Three changes:**

1. The inline `math.exp(-days_since / stability)` in `decay_manager` becomes `lifecycle.retrievability(...)` — one implementation shared with the reinforcement path (AC5).
2. The decay anchor flips from `last_review or last_accessed` to `last_accessed or last_review`. With the cooldown, `last_review` can lag the last use by a full cooldown window; anchoring decay on it would let an actively used node look stale. The two-way fallback stays so a row missing either column still decays instead of being skipped.
3. **`importance_scorer.py` gets the same anchor flip — and nothing else.** This file was declared out of scope in the original spec; the council review showed why that was wrong — see below.

**Why `importance_scorer` is now in scope (council finding C2).** The scorer reads its recency
anchor as `r["last_review"] or r["last_accessed"]` with weight `0.33` (`config.py:144`). The
cooldown this issue introduces is precisely what makes `last_review` lag. A node used today but
reinforced yesterday reads as a day old, which costs it importance and can cross the `0.5` gate,
demoting the ranking of a memory that is in active use. Leaving it out would ship the cooldown
with two consumers reading the same lagging timestamp.

**The anchor flip is the ONLY change here — do not touch the formula (council round 2, C2).**
The first draft of this task also routed the scorer through `lifecycle.retrievability`, reading
`r["stability"]`. Both peers rejected that, and the source confirms them. #222 (PR #235, a merge
prerequisite for this issue) rewrites the scorer to
`SELECT id, access_count, last_accessed, importance, last_review FROM nodes` — **`stability` is
no longer selected** — and computes `_recency_signal(days_ago, half_life)` on importance's own
clock, deliberately decoupled from FSRS. Applying the old draft after #222 lands gives one of two
outcomes, both bad:

- `sqlite3.Row["stability"]` on a row without that column raises **`IndexError`**, which the
  surrounding `except (ValueError, TypeError)` does not catch (verified:
  `issubclass(IndexError, (ValueError, TypeError))` is `False`), so `run_importance_scoring`
  aborts entirely; or
- the hunk survives the rebase and **undoes #222**, putting FSRS stability back into a job it was
  deliberately removed from.

The earlier claim that this change is "orthogonal to #222" was wrong and has been removed.

**Why existing decay tests stay green:** `_make_stale` (`test_decay_manager.py:13`) backdates
`last_accessed` only, and nodes created by `engine.remember` have `last_review = NULL`. Both
anchor orders resolve to `last_accessed` for those rows.

**Why every new decay test sets `importance = 0.2` (council finding C1).** `run_decay` skips a
node when `importance >= decay_importance_threshold`, and both sides default to `0.5`
(`config.py:155`, `node.py:58`) — `0.5 >= 0.5` fires the `continue` before any retrievability is
computed. A decay test that leaves importance at its default never reaches the code it claims to
exercise: it passes whether or not the anchor flipped, and a spy on `retrievability` records
nothing. Every existing test that expects demotion lowers importance first; the new ones must too.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_decay_manager.py`:

```python
def _make_decayable(engine, node_id: str) -> None:
    """Lower importance under decay_importance_threshold.

    Both the node default and the threshold are 0.5, and the gate is `>=`, so a
    node left at its default is skipped before retrievability is ever computed.
    """
    engine.db.conn.execute(
        "UPDATE nodes SET importance = 0.2 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()


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
    _make_decayable(engine, node_id)

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
    """The cooldown can leave last_review a day behind; use must win the anchor.

    With the old `last_review or last_accessed` order this node reads as 30 days
    stale and is demoted. Step 2 pins that: the test must FAIL before the flip.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Used today, reviewed a month ago",
        type=NodeType.fact,
        tier=Tier.working,
        title="Fresh use, stale review",
    ))
    now = datetime.now(timezone.utc)
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, stability = 1.0 WHERE id = ?",
        (now.isoformat(), (now - timedelta(days=30)).isoformat(), node_id),
    )
    _make_decayable(engine, node_id)

    run_decay(engine)

    assert _get_tier(engine, node_id) == "working"
```

Add `import pytest` to the file's imports if it is not already there.

Append to `tests/test_background/test_importance_scorer.py`:

```python
def test_recency_ignores_a_lagging_last_review(engine):
    """A node used today must not read as stale because reinforcement is on cooldown.

    The 30-day lag is load-bearing, not decorative (council round 2, C2). A 1-day lag
    makes this test a FALSE GREEN after #222: with the 14-day half-life the old anchor
    still yields importance 0.3141, inside approx(0.33, abs=0.02), so the test passes
    whether or not the anchor was flipped. At 30 days the old anchor yields ~0.075 on
    the post-#222 half-life and ~0.0 on the pre-#222 exp(-t/S) curve, so the test is
    red on the old anchor under BOTH formulas — which matters because this branch is
    written pre-#222 and rebased post-#222.
    """
    from ormah.background.importance_scorer import run_importance_scoring

    node_id, _ = engine.remember(CreateNodeRequest(
        content="Used today, reinforced a month ago",
        type=NodeType.fact,
        tier=Tier.working,
        title="Lagging review",
    ))
    now = datetime.now(timezone.utc)
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, stability = 1.0, "
        "access_count = 0 WHERE id = ?",
        (now.isoformat(), (now - timedelta(days=30)).isoformat(), node_id),
    )
    engine.db.conn.commit()

    run_importance_scoring(engine)

    importance = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["importance"]

    # recency ~= 1.0 (used today), not ~= 0.23 (30 days on the importance half-life).
    # access_count=0 and no edges zero the other two signals, and the scorer
    # divides by the weight total, so importance collapses to w_recency/total.
    s = engine.settings
    total = s.importance_access_weight + s.importance_edge_weight + s.importance_recency_weight
    assert importance == pytest.approx(s.importance_recency_weight / total, abs=0.02)
```

Match the imports this file already uses; add `pytest`, `timedelta`, `timezone` and the node request imports if missing.

- [ ] **Step 2: Run the tests and verify the RIGHT failures**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py tests/test_background/test_importance_scorer.py -v`

Expected, and each one matters:

| Test | Expected failure |
|---|---|
| `test_decay_uses_the_shared_retrievability_implementation` | `AttributeError: module 'ormah.background.decay_manager' has no attribute 'lifecycle'` |
| `test_a_node_used_today_is_not_decayed_while_its_review_lags` | `AssertionError: assert 'archival' == 'working'` — the node **is** demoted on the old anchor |
| `test_recency_ignores_a_lagging_last_review` | importance `≈ 0.0` instead of `≈ 0.33` — on `a28837b` the old anchor reads 30 days at `S=1`, so `exp(-30)` underflows the recency term to nothing. After a rebase onto #222 the same test fails at `≈ 0.075` (30 days on the 14-day half-life). Red under both formulas, by design. |

If the anchor test passes here, stop: the node was skipped by the importance gate and the test proves nothing. Confirm with `SELECT importance FROM nodes` that it really is `0.2`.

- [ ] **Step 3: Swap the decay import**

In `src/ormah/background/decay_manager.py`, replace `import math` with:

```python
from ormah import lifecycle
```

Keep it in the `ormah` import block with the existing `from ormah.background.memory_lock import serialized_memory_job`, above `from ormah.models.node import Tier, UpdateNodeRequest`.

- [ ] **Step 4: Rewrite the decay retrievability block**

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

- [ ] **Step 5: Flip the importance scorer's anchor — ONE line, nothing else**

**Read this before touching the file.** This step changes exactly one expression: the anchor
`or`-chain. It does **not** import `lifecycle`, does **not** read `r["stability"]`, and does
**not** replace the recency formula. Whatever formula the scorer holds when you get here — the
`exp(-t/S)` of `a28837b`, or `_recency_signal(days_ago, half_life)` after a rebase onto #222 —
stays exactly as it is. This is the correction from council round 2 (C2), where both peers
rejected the earlier draft that routed the scorer through `lifecycle.retrievability`.

In `src/ormah/background/importance_scorer.py`, find the recency block and change only this line:

```python
            anchor_str = r["last_review"] or r["last_accessed"]
```

to:

```python
            # Anchor on use, not on the numeric stability update (#221): the
            # reinforcement cooldown can leave last_review a full window behind
            # the last use, and a memory used today must not read as stale.
            anchor_str = r["last_accessed"] or r["last_review"]
```

Both columns are in the scorer's `SELECT` on `a28837b` and remain in it on #222
(`SELECT id, access_count, last_accessed, importance, last_review FROM nodes`), so the flip
applies cleanly under either version.

**Rebase check — run this before and after any rebase onto #222:**

```bash
grep -n 'r\["stability"\]\|lifecycle\.' src/ormah/background/importance_scorer.py
```

Any hit means Step 5 overreached. `r["stability"]` after #222 raises `IndexError` — not caught by
the surrounding `except (ValueError, TypeError)` — and aborts `run_importance_scoring` for every
node. Leave `import math` and the existing imports untouched.

- [ ] **Step 6: Run both suites**

Run: `./.venv/bin/python -m pytest tests/test_background/test_decay_manager.py tests/test_background/test_importance_scorer.py -v`
Expected: all pass, including the pre-existing `test_low_importance_stale_node_decayed`, `test_decay_is_idempotent`, and `test_decay_writes_audit_log`.

- [ ] **Step 7: Confirm the duplicated formula is gone from both jobs**

Run: `grep -n "math.exp" src/ormah/background/decay_manager.py src/ormah/background/importance_scorer.py`
Expected: no output. Both jobs now go through `lifecycle.retrievability`.

- [ ] **Step 8: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/background/decay_manager.py src/ormah/background/importance_scorer.py tests/test_background/test_decay_manager.py tests/test_background/test_importance_scorer.py
git add src/ormah/background/decay_manager.py src/ormah/background/importance_scorer.py tests/test_background/test_decay_manager.py tests/test_background/test_importance_scorer.py
git commit -m "fix(lifecycle): decay and importance share one retrievability, anchored on use (#221)"
```

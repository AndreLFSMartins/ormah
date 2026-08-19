# Task 1: Importance recency uses its own half-life, not FSRS stability

> Part of `docs/superpowers/plans/2026-08-16-issue-222/`. **Read `00-overview.md` first** —
> it carries the Global Constraints and the council findings that every task must honor.

**Files:**
- Modify: `src/ormah/background/importance_scorer.py:33-36` (the row `SELECT`), `:78-86` (the recency block)
- Modify: `src/ormah/config.py` (new `field_validator`, near `:1003`)
- Test: `tests/test_background/test_importance_scorer.py`
- Test: `tests/test_config.py` (validator rejection cases — see Step 1c for locating the right file)

**Interfaces:**
- Consumes: `settings.importance_recency_half_life_days` (already exists in `config.py:263`, default `14.0`).
- Produces: module-level `_recency_signal(days_ago: float, half_life_days: float) -> float` in `importance_scorer.py`, returning `exp(-ln(2) * days_ago / half_life_days)` and `0.0` for a non-positive half-life. Task 3 does not depend on it.

> **Council I1:** this task makes `importance_recency_half_life_days` a *read* setting for the
> first time. It has no validator today, so `Settings` accepts `0.0` (→ `ZeroDivisionError`,
> which the recency block's `except (ValueError, TypeError)` does NOT catch, aborting the whole
> job) and negatives (→ recency grows with age, saturating importance at 1.0 and corrupting both
> forgetting gate #4 and core-cap ranking). Steps 1b/1c/3 close that.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_importance_scorer.py`:

```python
def test_recency_signal_follows_configured_half_life():
    """At exactly one half-life the signal is 0.5; at zero days it is 1.0."""
    from ormah.background.importance_scorer import _recency_signal

    assert _recency_signal(0.0, 14.0) == pytest.approx(1.0)
    assert _recency_signal(14.0, 14.0) == pytest.approx(0.5)
    assert _recency_signal(28.0, 14.0) == pytest.approx(0.25)

    # A different configured half-life moves the 0.5 point with it.
    assert _recency_signal(7.0, 7.0) == pytest.approx(0.5)


def test_recency_signal_survives_a_non_positive_half_life():
    """Defence in depth (council I1): the validator should make this unreachable,
    but a zero half-life must never raise ZeroDivisionError and kill the job."""
    from ormah.background.importance_scorer import _recency_signal

    assert _recency_signal(10.0, 0.0) == 0.0
    assert _recency_signal(10.0, -14.0) == 0.0


def test_importance_recency_is_independent_of_stability(engine):
    """Two nodes of identical age and profile score the same regardless of stability.

    Before #222 the recency term was exp(-days/stability), so a high-stability node
    scored far higher than a low-stability one at the same age. It must not anymore.
    """
    low_id, _ = engine.remember(CreateNodeRequest(
        content="Alpha node about zebras and telescopes",
        type=NodeType.fact,
        tier=Tier.working,
        title="Low stability",
    ))
    high_id, _ = engine.remember(CreateNodeRequest(
        content="Beta node about zebras and telescopes",
        type=NodeType.fact,
        tier=Tier.working,
        title="High stability",
    ))

    old_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, access_count = 3, "
        "stability = 1.0 WHERE id = ?",
        (old_date, old_date, low_id),
    )
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, access_count = 3, "
        "stability = 100.0 WHERE id = ?",
        (old_date, old_date, high_id),
    )
    # Auto-linking can attach edges non-deterministically; importance reads edge
    # counts, so strip them to isolate the recency term.
    engine.db.conn.execute(
        "DELETE FROM edges WHERE source_id IN (?, ?) OR target_id IN (?, ?)",
        (low_id, high_id, low_id, high_id),
    )
    engine.db.conn.commit()

    run_importance_scoring(engine)

    low_imp = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (low_id,)
    ).fetchone()["importance"]
    high_imp = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (high_id,)
    ).fetchone()["importance"]

    assert low_imp == pytest.approx(high_imp), (
        f"stability must not affect importance recency: {low_imp} vs {high_imp}"
    )
```

- [ ] **Step 1b: Write the failing validator tests**

Append to `tests/test_config.py` (it already imports `pytest`, `ValidationError` and `Settings`):

```python
def test_importance_recency_half_life_must_be_positive():
    with pytest.raises(ValidationError, match="importance_recency_half_life_days must be > 0"):
        Settings(importance_recency_half_life_days=0.0)
    with pytest.raises(ValidationError, match="importance_recency_half_life_days must be > 0"):
        Settings(importance_recency_half_life_days=-14.0)


def test_importance_recency_half_life_must_be_finite():
    with pytest.raises(ValidationError, match="importance_recency_half_life_days must be finite"):
        Settings(importance_recency_half_life_days=float("inf"))
    with pytest.raises(ValidationError, match="importance_recency_half_life_days must be finite"):
        Settings(importance_recency_half_life_days=float("nan"))


def test_importance_recency_half_life_accepts_the_default():
    assert Settings().importance_recency_half_life_days == 14.0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_importance_scorer.py -k "recency_signal or recency_is_independent" -v
python -m pytest tests/test_config.py -k "importance_recency_half_life" -v
```

Expected: the `_recency_signal` tests FAIL with `ImportError: cannot import name '_recency_signal'`; `test_importance_recency_is_independent_of_stability` FAILS on the `approx` assertion (the stability-100 node scores higher); the three validator tests FAIL because no validator raises yet (`Settings(...)` simply accepts the bad values).

- [ ] **Step 3: Add the helper**

In `src/ormah/background/importance_scorer.py`, insert after the `logger = logging.getLogger(__name__)` line:

```python
def _recency_signal(days_ago: float, half_life_days: float) -> float:
    """Importance recency: half-life decay on its own clock (#222).

    Independent of FSRS stability — importance answers "how recently was this
    touched", not "how retrievable is it". Coupling the two let a high-stability
    node read as permanently recent.

    A non-positive half-life is rejected by config validation; the guard here is
    defence in depth, because a ZeroDivisionError would abort the whole scoring
    job rather than skipping one node (council I1).
    """
    if half_life_days <= 0:
        return 0.0
    return math.exp(-math.log(2) * days_ago / half_life_days)
```

- [ ] **Step 3b: Add the config validator**

In `src/ormah/config.py`, insert immediately after the `_fsrs_positive` validator (ends at line 1008):

```python
    @field_validator("importance_recency_half_life_days")
    @classmethod
    def _importance_half_life_positive(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"importance_recency_half_life_days must be finite, got {v}")
        if v <= 0:
            raise ValueError(f"importance_recency_half_life_days must be > 0, got {v}")
        return v
```

`config.py` does NOT import `math` today (its stdlib block at lines 5-7 is `logging`, `os`, `pathlib.Path`). Add it, keeping alphabetical order:

```python
import logging
import math
import os
from pathlib import Path
```

- [ ] **Step 4: Use the helper and drop the stability read**

In `src/ormah/background/importance_scorer.py`, change the row query (currently lines 33-36) from:

```python
    rows = conn.execute(
        "SELECT id, access_count, last_accessed, "
        "importance, stability, last_review FROM nodes"
    ).fetchall()
```

to:

```python
    rows = conn.execute(
        "SELECT id, access_count, last_accessed, "
        "importance, last_review FROM nodes"
    ).fetchall()
```

Then, below `ref_edge = settings.importance_edge_reference`, add:

```python
    half_life = settings.importance_recency_half_life_days
```

Then replace the recency block (currently lines 78-86):

```python
        # Recency signal: FSRS retrievability (exp(-t/S))
        try:
            stability = r["stability"] if r["stability"] else 1.0
            anchor_str = r["last_review"] or r["last_accessed"]
            anchor = datetime.fromisoformat(anchor_str)
            days_ago = max((now - anchor).total_seconds() / 86400, 0)
            recency_signal = math.exp(-days_ago / stability)
        except (ValueError, TypeError):
            recency_signal = 0.0
```

with:

```python
        # Recency signal: importance's own half-life, not FSRS stability (#222)
        try:
            anchor_str = r["last_review"] or r["last_accessed"]
            anchor = datetime.fromisoformat(anchor_str)
            days_ago = max((now - anchor).total_seconds() / 86400, 0)
            recency_signal = _recency_signal(days_ago, half_life)
        except (ValueError, TypeError):
            recency_signal = 0.0
```

- [ ] **Step 5: Run the new tests**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_importance_scorer.py -k "recency_signal or recency_is_independent" -v
python -m pytest tests/test_config.py -k "importance_recency_half_life" -v
```

Expected: PASS (5 tests total — 2 helper, 3 validator).

- [ ] **Step 6: Run the whole importance suite — the existing tests must still hold**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
python -m pytest tests/test_background/test_importance_scorer.py -v
```

Expected: all PASS. Three existing tests encode numeric ranges that the new formula must not break — verify these specifically:
- `test_recency_decay`: fresh node (recency ≈ 1.0) still outscores a 30-day-old node (recency = `exp(-ln2·30/14)` ≈ 0.227).
- `test_importance_range_with_new_signals`: the stale node (5 accesses, 0 edges, 30 days) scores `0.34·0.4557 + 0.33·0.227 ≈ 0.230`, still under its `< 0.3` assertion; the hub still `> 0.7`; fresh still `> 0.2`.
- `test_all_new_nodes_get_recency_signal`: fresh nodes have `days_ago ≈ 0` → recency ≈ 1.0 → importance > 0.

If any of those fail, STOP and report the actual number — do not adjust the assertion to fit.

- [ ] **Step 7: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
ruff check src/ormah/background/importance_scorer.py src/ormah/config.py \
  tests/test_background/test_importance_scorer.py tests/test_config.py
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-222
git add src/ormah/background/importance_scorer.py src/ormah/config.py \
  tests/test_background/test_importance_scorer.py tests/test_config.py
git commit -m "fix(importance): recency uses its own half-life, not FSRS stability (#222)

importance_recency_half_life_days was configured but never read; the recency
term reused exp(-days/stability), coupling importance to retrievability. A
high-stability node therefore read as permanently recent.

Making it a read setting exposed that it had no validator: zero raised
ZeroDivisionError and aborted the whole scoring job, negatives inverted the
curve. Adds a finite-and-positive validator plus a defensive guard in the
helper.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git show --stat HEAD
```

Expected: `git show --stat` lists exactly 4 files.

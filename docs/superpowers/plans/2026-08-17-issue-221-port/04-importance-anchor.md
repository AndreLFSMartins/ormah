### Task 4: `importance_scorer` anchors on use

**Files:**
- Modify: `src/ormah/background/importance_scorer.py:99`
- Modify: `tests/test_background/test_importance_scorer.py`

**Interfaces:** consumes nothing; produces nothing.

**This task is one line, and it is much smaller than #221's version.** Do not port `4cf017f`'s `importance_scorer.py` — it is obsolete here. #222 already replaced the FSRS recency with `_recency_signal(days_ago, half_life)`, a half-life clock deliberately independent of stability, and removed `stability` from the SELECT. All that is still owed is the anchor.

**Do not** import `lifecycle` here, do not read `r["stability"]`, and do not touch `_recency_signal`. After #222 that column is not selected, and `sqlite3.Row` raises an `IndexError` the surrounding `except (ValueError, TypeError)` does not catch — which would abort the whole scoring job.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_importance_scorer.py`:

```python
def test_recency_anchors_on_use_not_on_the_numeric_update(engine):
    """#221: the cooldown can leave last_review a window behind real use.

    A node used today whose last_review is 30 days old must score as recent.
    Anchoring on last_review would read it as stale.
    """
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Gamma node about zebras and telescopes",
        type=NodeType.fact,
        tier=Tier.working,
        title="Lagging last_review",
    ))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).isoformat()

    # Used today, last reinforced 30 days ago — the shape the cooldown creates.
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ?, last_review = ?, access_count = 3 "
        "WHERE id = ?",
        (now.isoformat(), old, node_id),
    )
    engine.db.conn.commit()
    run_importance_scoring(engine)
    fresh = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["importance"]

    # Same node, same last_review, but the use is now old too.
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = ? WHERE id = ?", (old, node_id)
    )
    engine.db.conn.commit()
    run_importance_scoring(engine)
    stale = engine.db.conn.execute(
        "SELECT importance FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["importance"]

    assert fresh > stale, (
        "recency followed last_review, not last_accessed: "
        f"fresh={fresh} stale={stale}"
    )
```

`run_importance_scoring` and `CreateNodeRequest`/`NodeType`/`Tier` are already imported at the top of this test file (`from ormah.background.importance_scorer import run_importance_scoring`), as is `from datetime import datetime, timedelta, timezone` — verified on `local-main`, so add no imports. The `engine` fixture is the one `test_importance_recency_is_independent_of_stability` uses.

`access_count = 3` is set so the access signal is identical between the two runs; only the recency term is allowed to move. Without it both scores could be dominated by a zero access signal and the comparison would be vacuous.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_background/test_importance_scorer.py::test_recency_anchors_on_use_not_on_the_numeric_update -v`
Expected: FAIL — with the current anchor both runs read the same 30-day-old `last_review`, so `fresh == stale`.

- [ ] **Step 3: Flip the anchor**

In `src/ormah/background/importance_scorer.py`, change:

```python
            anchor_str = r["last_review"] or r["last_accessed"]
```

to:

```python
            # Anchor on use, not on the numeric stability update (#221): the
            # reinforcement cooldown can leave last_review a full window behind.
            anchor_str = r["last_accessed"] or r["last_review"]
```

- [ ] **Step 4: Run to verify pass, then check the scope gate**

Run: `./.venv/bin/python -m pytest tests/test_background/test_importance_scorer.py -v` — expected: all pass, including `test_importance_recency_is_independent_of_stability` from #222, which must stay green.

```bash
grep -c "r\[.stability.\]" src/ormah/background/importance_scorer.py
grep -c "lifecycle" src/ormah/background/importance_scorer.py
```

Expected: **0** for both. Any hit means #221's obsolete version leaked in — stop and report.

- [ ] **Step 5: Commit**

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/background/importance_scorer.py tests/test_background/test_importance_scorer.py
git commit -m "fix(lifecycle): importance recency anchors on use, not on the numeric update (#221)"
```


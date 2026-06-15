# Task 06: §3 cap backstop (forget-score eviction)

**Depends on:** Task 05.

After Phase A, if `archival_soft_cap > 0` and the archival count still exceeds it, evict the
worst nodes by a composite forget-score, worst-first, down to the cap — while respecting every
protection (self node, positive feedback, hub). The cap is independent of the gate staleness
window: it can evict a node that is *inside* the gates, which is the whole point of a backstop.

**Files:**
- Modify: `src/ormah/background/forgetting_manager.py`
- Test: `tests/test_background/test_forgetting_manager.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_forgetting_manager.py`:

```python
def _make_archival_recent(engine, content, archived_days):
    """Archival node that is NOT gate-eligible (recently accessed), with a chosen age."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content=content, type=NodeType.fact, tier=Tier.archival, title=content))
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    archived = (datetime.now(timezone.utc) - timedelta(days=archived_days)).isoformat()
    engine.db.conn.execute(
        "UPDATE nodes SET tier='archival', importance=0.1, stability=1.0, "
        "last_review=?, last_accessed=?, archived_at=? WHERE id=?",
        (recent, recent, archived, node_id))
    engine.db.conn.commit()
    return node_id


def test_cap_backstop_evicts_worst_down_to_cap(engine):
    _enable(engine)
    engine.settings.archival_soft_cap = 2
    ids = [_make_archival_recent(engine, f"n{i}", archived_days=age)
           for i, age in enumerate([300, 250, 200, 150, 50])]
    # none are gate-eligible (accessed 3 days ago) → Phase A deletes nothing
    run_forgetting(engine)
    remaining = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes WHERE tier='archival'").fetchone()["c"]
    assert remaining == 2
    # the two youngest (least forgettable) survive
    assert _exists(engine, ids[4]) is True   # 50d
    assert _exists(engine, ids[3]) is True   # 150d
    # the oldest were evicted
    assert _exists(engine, ids[0]) is False  # 300d


def test_cap_backstop_never_evicts_protected(engine):
    _enable(engine)
    engine.settings.archival_soft_cap = 1
    old = _make_archival_recent(engine, "old protected", archived_days=400)
    mid = _make_archival_recent(engine, "mid", archived_days=200)
    young = _make_archival_recent(engine, "young", archived_days=20)
    # protect the worst-scored (oldest) with positive feedback
    engine.db.conn.execute(
        "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
        "VALUES (?, ?, 1, 'explicit', ?, 's1')",
        (b"\x00", old, datetime.now(timezone.utc).isoformat()))
    engine.db.conn.commit()
    run_forgetting(engine)
    # protected node survives even though it scores worst; cap may stay above target
    assert _exists(engine, old) is True
    assert _exists(engine, young) is True   # youngest survives
    assert _exists(engine, mid) is False    # evicted to approach the cap


def test_cap_disabled_by_default_zero(engine):
    _enable(engine)
    # archival_soft_cap defaults to 0
    ids = [_make_archival_recent(engine, f"z{i}", archived_days=300) for i in range(4)]
    run_forgetting(engine)
    remaining = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes WHERE tier='archival'").fetchone()["c"]
    assert remaining == 4  # cap off → no eviction
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -k cap -v`
Expected: FAIL (cap not implemented; `test_cap_disabled_by_default_zero` may pass already).

- [ ] **Step 3: Wire the cap into `run_forgetting`**

In `src/ormah/background/forgetting_manager.py`, replace the line:

```python
        # Task 06 inserts the §3 cap backstop here.
```

with:

```python
        _run_cap_backstop(engine, now)
```

- [ ] **Step 4: Implement the cap + forget-score**

Append these functions to `forgetting_manager.py`:

```python
def _run_cap_backstop(engine, now: datetime) -> int:
    """Evict worst-first by forget-score down to archival_soft_cap, respecting protections."""
    s = engine.settings
    if s.archival_soft_cap <= 0:
        return 0
    rows = engine.db.conn.execute(
        "SELECT id, importance, stability, last_review, last_accessed, archived_at "
        "FROM nodes WHERE tier = 'archival'"
    ).fetchall()
    overflow = len(rows) - s.archival_soft_cap
    if overflow <= 0:
        return 0

    user_id = getattr(engine, "user_node_id", None)
    scored: list[tuple[float, str]] = []
    for row in rows:
        if row["id"] == user_id:
            continue  # never the self node
        if _has_positive_feedback(engine, row["id"]):
            continue  # proven-useful ⇒ protected forever
        degree, max_weight = _connectivity(engine, row["id"])
        if max_weight >= s.deletion_strong_edge_weight:
            continue  # never evict a hub
        scored.append((_forget_score(row, now, degree), row["id"]))

    scored.sort(reverse=True)  # highest forget-score (worst) first
    evicted = 0
    for _score, node_id in scored[:overflow]:
        if engine.delete_node(node_id):
            evicted += 1
    if evicted:
        logger.info("Forgetting cap backstop evicted %d archival nodes", evicted)
    return evicted


def _forget_score(row, now: datetime, degree: int) -> float:
    """Composite worst-first score: low R × low importance × age × low connectivity.

    Candidates already exclude positive feedback, so the no_positive_feedback factor is 1.
    """
    r = _retrievability(row, now)
    importance = row["importance"] if row["importance"] is not None else 0.5
    anchor_str = row["archived_at"] or row["last_accessed"]
    try:
        age_days = max((now - datetime.fromisoformat(anchor_str)).total_seconds() / 86400, 0.0)
    except (ValueError, TypeError):
        age_days = 0.0
    return (1.0 - r) * (1.0 - importance) * age_days * (1.0 / (1 + degree))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -v`
Expected: PASS (all tests, including the Task 05 set).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git add src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git commit -m "feat(background): cap backstop forget-score eviction (#28)"
```

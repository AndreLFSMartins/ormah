# Task 2: Pin the legacy fallback's accepted loss

> Read `00-overview.md` first — it carries the goal, the global constraints, and the interpreter rule this task depends on.

**Files:**
- Test: `tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: `_snapshot`, `_make_nodes`, and `_seed_held_back_whisper_log` from Task 1.
- Produces: nothing. This task adds no `src` change — it characterises a consequence Task 1 introduces, which André signed off on 2026-08-16.

- [ ] **Step 1: Write the test**

Append to `tests/test_engine/test_confirmed_use_contract.py`:

```python
def test_legacy_fallback_on_a_held_back_event_does_not_confirm(engine):
    """Contract 11a: the fallback's accepted loss, pinned deliberately.

    submit_feedback without whisper_log_id resolves to the node's newest
    whisper row, injected or not. When that row is a held-back review
    candidate, no claim is taken even though an older injected event exists —
    a legitimate reinforcement is lost in silence. Accepted: failing closed is
    the right side to err on under the at-most-once contract, and the fallback
    already documents itself as not exact. Fixing the fallback's selection
    would also move which event affinity and signals attach to, which is a
    different defect. This test exists so that loss stays a decision rather
    than becoming a surprise.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    injected_id = _seed_whisper_log(engine, target)
    held_back_id = _seed_held_back_whisper_log(engine, target)
    assert held_back_id > injected_id, "the held-back event must be the newer row"

    before = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit")

    assert _snapshot(engine, target) == before, (
        "the legacy fallback reinforced through a held-back event"
    )
    # The fallback still attaches its evidence to the newest event — unchanged.
    affinity = engine.db.conn.execute(
        "SELECT whisper_log_id FROM affinity WHERE node_id = ?", (target,)
    ).fetchone()
    assert affinity["whisper_log_id"] == held_back_id
```

- [ ] **Step 2: Run it**

```bash
./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py::test_legacy_fallback_on_a_held_back_event_does_not_confirm -v
```

Expected: **PASS** (Task 1 already made it true). If it fails on `held_back_id > injected_id`, the ordering assumption broke — both rows use `datetime('now')` at second resolution, so the tie-break is `wl.id DESC`, which the assertion checks directly. If it fails on the affinity assertion, Task 1 changed more than the claim: stop and re-read the diff.

- [ ] **Step 3: Full suite, for regressions outside this file**

```bash
./.venv/bin/python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: **11 failures**, all from the `~/.config/ormah/.env` leak, with the **same list of test IDs** measured before this branch's commits. Compare the IDs, not the count. Any failure outside that list is a regression from this work.

- [ ] **Step 4: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ tests/
git add tests/test_engine/test_confirmed_use_contract.py
git commit -m "test(lifecycle): pin the legacy fallback's accepted confirmed-use loss"
git show --stat HEAD
```

Expected: `git show --stat HEAD` lists exactly **1 file changed**.


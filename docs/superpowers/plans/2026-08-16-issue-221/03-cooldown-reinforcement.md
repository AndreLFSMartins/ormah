# Task 3: Cooldown + bounded reinforcement in the engine

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1936-1960` (`_touch_access`)
- Modify: `src/ormah/config.py` (remove `fsrs_stability_growth` and drop it from `_fsrs_positive`)
- Modify: `tests/test_config_fsrs.py` (append the two removal tests)
- Create: `tests/test_engine/test_reinforcement_cooldown.py`

**Interfaces:**
- Consumes: `ormah.lifecycle.reinforcement_due` and `ormah.lifecycle.reinforced_stability` (Task 1); the four `Settings` fields from Task 2.
- Produces: no new public names. `_touch_access` keeps its signature `(self, node_id: str) -> None` and its five call sites (`memory_engine.py:646, 775, 811, 892, 938`) stay untouched.
- Removes: `fsrs_stability_growth`. **This task owns the removal, together with its only reader**
  (`memory_engine.py:1947`, inside `_touch_access`). Task 2 deliberately left the field in place:
  deleting it there and rewriting the reader here would leave the Task 2 commit raising
  `AttributeError` on every recall path, and 12 test files exercise those paths (pre-flight,
  2026-08-16; decision: André). Field and reader go in one commit, so every commit stays green.

**Behavior contract:** every call advances `last_accessed` and `access_count`. Only a call that is off cooldown changes `stability` and `last_review`.

**Note on #220:** PR #234 renames this method to `_record_confirmed_use` and adds its own zero-stability guard. On rebase, keep the new name and this task's body — the guard now lives in `lifecycle.py`.

**The cooldown is TOCTOU without the lock (council round 3, I1, Cursor).** `reinforcement_due`
reads `last_review` off the in-memory node and the new `last_review` is written several statements
later. The read and the write are not atomic, and the paths that reach `_touch_access` are **not
serialized**: `recall_node` (`memory_engine.py:637`), `recall_search_structured` (`:679`) and
`recall_search` (`:832`) carry no `@_serialized_memory_operation`, unlike `remember`/`update`. Two
concurrent recalls on the FastAPI threadpool load the same node, both see `due=True`, and both
write a bump — so **AC4 does not hold under concurrency**, and the sequential ten-touch test cannot
see it. Sequential same-session compounding is genuinely fixed either way.

The fix is Step 4's decorator, not a new mechanism: `_memory_operation_lock` is a
`threading.RLock` (`memory_engine.py:93`), so it is **reentrant** — decorating `_touch_access`
cannot deadlock at the call sites that already hold it. It also covers the Markdown write and the
DB write as one unit, which a conditional `UPDATE … WHERE last_review < ?` would not: the file
store is the source of truth here, and a DB-only guard would still let two processes write
divergent Markdown.

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


def test_concurrent_touches_still_produce_one_stability_update(engine):
    """AC4 under concurrency (council round 3, I1).

    The sequential ten-touch test above cannot see this: it is the *interleaving*
    that breaks the cooldown. Both threads read last_review before either writes
    it, both conclude they are off cooldown, and both bump. The recall paths that
    reach _touch_access carry no @_serialized_memory_operation, so this is the
    real production shape, not a synthetic one.

    Barrier, not a bare thread pair: without it the two threads can serialize by
    luck and the test greens on the broken code. The barrier forces both past the
    cooldown read before either proceeds.
    """
    import threading

    node_id = _make_node(engine)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, last_review = NULL WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()
    node = engine.file_store.load(node_id)
    node.stability = 1.0
    node.last_review = None
    engine.file_store.save(node)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _touch() -> None:
        try:
            barrier.wait(timeout=5)
            engine._touch_access(node_id)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` below
            errors.append(exc)

    threads = [threading.Thread(target=_touch) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"a touch thread raised: {errors}"
    row = _row(engine, node_id)
    # One bump from S=1.0, never two. The second bump would compound past this.
    assert row["stability"] == pytest.approx(1.5)
    assert row["access_count"] == 2, "both touches must still be counted"
```

Add `import pytest` to the file's imports.

Then append to `tests/test_config_fsrs.py` (created in Task 2) the two tests that only become
true once this task removes the field:

```python
def test_the_removed_growth_knob_no_longer_exists(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir)
    assert not hasattr(settings, "fsrs_stability_growth")


def test_an_env_carrying_the_removed_knob_still_loads(tmp_memory_dir, monkeypatch):
    """extra="ignore" (config.py:20) keeps an old .env from breaking startup."""
    monkeypatch.setenv("ORMAH_FSRS_STABILITY_GROWTH", "1.5")
    settings = Settings(memory_dir=tmp_memory_dir)
    assert settings.fsrs_growth_factor == 0.5
```

These live here, not in Task 2, because in Task 2 the field still exists: the first would fail and
the second would pass for the wrong reason — the env var would bind to the live field instead of
being ignored as an extra.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py tests/test_config_fsrs.py -v`

Expected: FAIL, with these specific failures:

| Test | Expected failure |
|---|---|
| `test_ten_touches_in_one_day_produce_one_stability_update` | every touch still updates stability |
| `test_a_thirty_day_old_node_is_bounded_to_double` | reports ~`202.7` instead of `2.0` |
| `test_reinforcement_survives_a_zero_stability_node` | raises `ZeroDivisionError` |
| `test_concurrent_touches_still_produce_one_stability_update` | compounded stability instead of `1.5` |
| `test_the_removed_growth_knob_no_longer_exists` | the field is still there (Task 2 left it) |

`test_an_env_carrying_the_removed_knob_still_loads` **passes here for the wrong reason** — the env
var binds to the still-present field. That is expected and is exactly why it could not live in
Task 2: it only becomes meaningful after Step 3 removes the field.

If the concurrency test happens to pass before Step 4, do not accept it — re-run it a few
times. A lucky serialization greens it; the barrier makes that rare, not impossible.

- [ ] **Step 3: Add the import, and remove the old knob**

In `src/ormah/engine/memory_engine.py`, add to the existing `ormah` imports (alphabetical order within the block):

```python
from ormah import lifecycle
```

In `src/ormah/config.py`, delete the field line Task 2 left in place:

```python
    fsrs_stability_growth: float = 1.5     # base multiplier on access; removed in Task 3
```

and drop `"fsrs_stability_growth"` from the `_fsrs_positive` validator's field list, leaving
`"fsrs_initial_stability"`, `"fsrs_growth_factor"`, `"fsrs_growth_exponent"`.

Do this **before** Step 4, not after: between the two edits `memory_engine.py:1947` still reads a
field that no longer exists, so the tree is briefly broken. That is fine inside one task and not
fine across a commit boundary — which is the whole reason the removal lives here. Do not commit
until Step 4 is done.

- [ ] **Step 4: Rewrite `_touch_access`**

Replace lines 1936-1960 entirely:

```python
    @_serialized_memory_operation
    def _touch_access(self, node_id: str) -> None:
        """Update access stats, and FSRS stability when it is off cooldown.

        Serialized because the cooldown is a check-then-write pair (#221,
        council round 3): the recall paths that call this are not themselves
        serialized, so two concurrent recalls would both read a stale
        last_review and both bump stability. _memory_operation_lock is an
        RLock, so the call sites that already hold it re-enter safely.
        """
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

Three deliberate changes beyond the formula swap: the `0.001` days floor is gone (the cooldown is
what stops same-session compounding now), `last_review` is written defensively as `None` when
unset (a node can now reach the write without ever being reinforced), and the method is
**serialized** so the cooldown's check-then-write pair is atomic.

`_serialized_memory_operation` is defined at `memory_engine.py:79` and already decorates
`remember`/`update`; it is in scope at this indentation level, so no import is needed. Do not
reach for a new lock — reusing this one is what makes the Markdown write and the DB write move
as a unit.

- [ ] **Step 5: Run the new tests**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py -v`
Expected: 6 passed.

Then confirm the decorator is what carries the concurrency test, rather than luck: remove it,
re-run `test_concurrent_touches_still_produce_one_stability_update` five times, and see it go
red. Put it back. A lock nobody watched fail is a lock nobody knows works.

- [ ] **Step 6: Run the suites that already exercised this path, plus the config removal**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_mutation_stamping.py tests/test_engine/test_scoring_signals.py tests/test_store/test_file_store.py tests/test_config_fsrs.py -v`

Expected: all pass. `test_touch_access_does_not_advance_updated` (`test_mutation_stamping.py:95`)
is the important one — reinforcement must still not stamp `updated`. `test_config_fsrs.py` now
reports **32 passed**: the 30 from Task 2 plus the two removal tests added in Step 1.

Then run the recall paths, because this task both removed the old knob and serialized the method
they all call:

```bash
./.venv/bin/python -m pytest tests/test_engine/ tests/test_api/test_routes_concurrency.py -q
```

Expected: no new failures against the branch baseline. A `sqlite3.ProgrammingError` or a hang here
means the `RLock` re-entry assumption is wrong — stop and report rather than swapping in a
different lock.

- [ ] **Step 7: Confirm the old knob is gone from src/**

```bash
grep -rn "fsrs_stability_growth" src/ eval/
```

Expected: **no output** — this task removed the field and its last reader together.

`tests/` is deliberately not in that grep: `tests/test_config_fsrs.py` still contains the string,
inside `test_the_removed_growth_knob_no_longer_exists`, by construction. Do not widen the grep and
then delete that test to make it quiet (council round 3, I2).

- [ ] **Step 8: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/engine/memory_engine.py src/ormah/config.py tests/test_engine/test_reinforcement_cooldown.py tests/test_config_fsrs.py
git add src/ormah/engine/memory_engine.py src/ormah/config.py tests/test_engine/test_reinforcement_cooldown.py tests/test_config_fsrs.py
git commit -m "fix(lifecycle): bounded stability growth, one update per node per day (#221)"
```

`config.py` and `test_config_fsrs.py` are in this commit on purpose: the removal of
`fsrs_stability_growth` and the rewrite of its only reader must land together, or the intermediate
commit breaks every recall path.

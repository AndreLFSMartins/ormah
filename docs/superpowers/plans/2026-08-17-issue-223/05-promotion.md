# Task 5: Promotion inside `_record_confirmed_use`

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (symbol: `MemoryEngine._record_confirmed_use`)
- Test: `tests/test_engine/test_reversible_promotion.py` (create)
- Test: `tests/test_engine/test_reinforcement_cooldown.py`
- Test: `tests/test_engine/test_confirmed_use_contract.py`
- Test: `tests/test_engine/test_tier_manager.py`
- Test: `tests/test_engine/test_audit_log.py`
- Test: `tests/test_engine/test_recall_concurrency.py`

**Interfaces:**
- Consumes: `lifecycle.promotion_floor` (Task 1), `Settings.fsrs_initial_stability` (Task 1), `MemoryNode.superseded_by` (Task 2), the `superseded_by` index column (Task 3).
- Produces: a promoting `_record_confirmed_use`; Task 6 relies on `superseded_by` blocking it.

**Qualification needs no new logic.** `_claim_confirmed_use` already fail-closes on `signal == 1`, `source in _CONFIRMED_USE_SOURCES` (`{explicit, implicit, auto_llm_judge}`), `was_injected == 1`, and at-most-once, and all three callers pass through it. Promotion placed *inside* `_record_confirmed_use` inherits "unqualified sources do not promote" for free. The contract test below exists to stop a future fourth caller from reopening the hole.

---

- [ ] **Step 1: Write the failing cooldown-interaction tests**

Append to `tests/test_engine/test_reinforcement_cooldown.py`, matching the fixture and node-construction idiom already in that file:

```python
def test_bounded_update_runs_before_the_floor(engine):
    """Archival, S=1, last used 30d ago -> 5.814.

    The bounded update gives 1 -> 2.0 (spacing saturates at cap 2.0); the floor
    then lifts 2.0 -> 5.814. The INVERTED order would give ~8.23
    (5.814 * (1 + 0.5 * 5.814**-0.5 * 2.0)), so equality at 5.814 catches it.
    Since e13d733 the spacing anchor is last_accessed (last_review only opens
    the cooldown gate), so both are backdated.
    """
    from datetime import datetime, timedelta, timezone

    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="an old archived memory"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_accessed = node.last_review = datetime.now(timezone.utc) - timedelta(days=30)
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)

    promoted = engine.file_store.load(node_id)
    assert promoted.stability == 5.814
    assert promoted.tier is Tier.working


def test_floor_applies_even_when_the_cooldown_blocked_the_numeric_update(engine):
    """Asserting only tier == working passes WITH the bug — and the node would
    re-archive in ~29 h on S=1. The stability assertion is the real gate."""
    from datetime import datetime, timezone

    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="recently reviewed, archived"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_review = datetime.now(timezone.utc)   # on cooldown
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)

    promoted = engine.file_store.load(node_id)
    assert promoted.tier is Tier.working
    assert promoted.stability == 5.814


def test_the_floor_does_not_stack_across_two_uses_in_one_day(engine):
    """Two confirmed uses in one day -> 5.814, not 11.628 and not 6.814."""
    from datetime import datetime, timezone

    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="used twice today"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.stability = 1.0
    node.last_review = datetime.now(timezone.utc)
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)
    engine._record_confirmed_use(node_id)

    assert engine.file_store.load(node_id).stability == 5.814
```

- [ ] **Step 2: Write the failing behaviour tests**

Create `tests/test_engine/test_reversible_promotion.py`. Copy the fixture import style from `tests/test_engine/test_reinforcement_cooldown.py`:

```python
"""Reversible promotion: archival nodes return to working on confirmed use (#223)."""

from __future__ import annotations

from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, Tier


def _archive(engine, content: str, superseded_by: str | None = None) -> str:
    node_id, _ = engine.remember(CreateNodeRequest(content=content))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.superseded_by = superseded_by
    engine.builder.index_single(engine.file_store.save(node))
    return node_id


def test_recall_node_promotes_exactly_the_requested_node(engine):
    """The archival NEIGHBOUR is the point: without it, an implementation that
    promotes every id in whisper_log_ids passes — and recall_node DOES create
    whisper_log rows for neighbours, in _log_feedback_candidates."""
    a = _archive(engine, "the node actually recalled")
    b = _archive(engine, "a connected neighbour that must stay archival")
    engine.connect(ConnectRequest(source_id=a, target_id=b, edge=EdgeType.related_to))

    engine.recall_node(a)

    assert engine.file_store.load(a).tier is Tier.working
    assert engine.file_store.load(b).tier is Tier.archival


def test_a_generic_derived_from_target_still_promotes(engine):
    """derived_from is a general relationship; only marked sources are blocked.
    Testing only the marked node misses the block-everything bug the issue names."""
    plain = _archive(engine, "a derived_from target that was never superseded")
    marked = _archive(engine, "a genuinely superseded source", superseded_by="some-consolidation-id")

    engine._record_confirmed_use(plain)
    engine._record_confirmed_use(marked)

    assert engine.file_store.load(plain).tier is Tier.working
    assert engine.file_store.load(marked).tier is Tier.archival


def test_a_superseded_node_is_not_promoted_but_still_tracks_access(engine):
    """Blocking promotion must not silently swallow the access bookkeeping."""
    marked = _archive(engine, "superseded but still read", superseded_by="some-consolidation-id")
    before = engine.file_store.load(marked).access_count

    engine._record_confirmed_use(marked)

    after = engine.file_store.load(marked)
    assert after.tier is Tier.archival
    assert after.access_count == before + 1


def test_a_working_node_is_left_alone(engine):
    """promote() guards tier ordering; a working node must not be touched by the branch."""
    node_id, _ = engine.remember(CreateNodeRequest(content="already working"))
    engine.file_store.load(node_id)

    engine._record_confirmed_use(node_id)

    assert engine.file_store.load(node_id).tier is Tier.working


def test_promotion_is_written_to_the_index_too(engine):
    node_id = _archive(engine, "must land in SQL as well")

    engine._record_confirmed_use(node_id)

    row = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["tier"] == "working"
```

- [ ] **Step 3: Run both files to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/test_reversible_promotion.py tests/test_engine/test_reinforcement_cooldown.py \
    -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. Every new test fails with `assert <Tier.archival> is <Tier.working>` — `promote()` still has no production caller.

- [ ] **Step 4: Add the promotion block**

In `src/ormah/engine/memory_engine.py`, in `_record_confirmed_use`, insert between the closing of the `if lifecycle.reinforcement_due(...)` block and the `# Standard access tracking` comment:

```python
        # Reversible promotion (#223, decided in #191). Deliberately AFTER the
        # cooldown block: the bounded update runs on the OLD stability first, then
        # the floor lifts the result. The floor also runs when the cooldown blocked
        # the numeric update — otherwise a second confirmed use in one day promotes
        # with S=1, buying a ~29 h lease that the next decay run immediately revokes.
        # promotion_floor is max() against a constant, so running it on every
        # promotion cannot push stability past one initial lease.
        #
        # superseded_by blocks ONLY consolidation sources. A generic derived_from
        # target promotes, which is the narrowing #191 asked for over the originally
        # proposed blanket exclusion.
        promoted = False
        if node.tier is Tier.archival and node.superseded_by is None:
            node.stability = lifecycle.promotion_floor(
                node.stability, self.settings.fsrs_initial_stability
            )
            # Goes through TierManager.promote(), not `node.tier = ...`: this gives
            # #223's root cause its first production caller and brings the tier-ordering
            # guard along. promote() calls touch_updated(), so `updated` advances — that
            # is correct, the tier genuinely changed, and `updated` feeds LWW sync; not
            # advancing it would let a stale remote copy win and silently re-archive.
            promoted = self.tier_manager.promote(node, Tier.working)
```

- [ ] **Step 5: Widen the targeted UPDATE**

Still in `_record_confirmed_use`, replace the `UPDATE nodes SET ...` statement with:

```python
        self.file_store.save(node)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE nodes SET access_count = ?, last_accessed = ?, stability = ?, "
                "last_review = ?, tier = ?, updated = ? WHERE id = ?",
                (
                    node.access_count,
                    node.last_accessed.isoformat(),
                    node.stability,
                    node.last_review.isoformat() if node.last_review else None,
                    node.tier.value,
                    node.updated.isoformat(),
                    node_id,
                ),
            )
```

No branching: on the non-promoting path both new values are the ones already on disk. No `builder.index_single` and no `_index_embedding` — content did not change, and the UPDATE already carries every column that moved.

- [ ] **Step 6: Write the audit entry after the transaction**

Immediately after the `with self.db.transaction()` block closes, at the end of the method:

```python
        if promoted:
            # After the transaction: _write_audit_log opens its own, so it cannot
            # sit inside. Same position update_node places its own audit call.
            self._write_audit_log(
                operation="promote",
                node_id=node_id,
                detail=json.dumps({"from": "archival", "to": "working"}),
            )
```

`json` is already imported at module level in `memory_engine.py` — confirm before running; if it is not, add `import json` to the existing import block rather than importing inside the method.

- [ ] **Step 7: Run both files to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/test_reversible_promotion.py tests/test_engine/test_reinforcement_cooldown.py \
    -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 8: Add the qualification matrix**

Append to `tests/test_engine/test_confirmed_use_contract.py`, where #220's matrix already lives.
That file already carries the two whisper-log seeders this matrix needs — do **not** write a third:

- `_seed_whisper_log(engine, node_id, prompt="what about caching?") -> int` (line 186) goes through
  `engine.recall_search`, which writes `was_injected = 1`.
- `_seed_held_back_whisper_log(engine, node_id, prompt="what about caching?") -> int` (line 520)
  does a manual `INSERT INTO whisper_log` with `was_injected = 0` — the held-back event the
  session-start review hands to the agent. Its docstring explains why `recall_search` cannot be used
  for that half; read it before touching the row.

The node must be findable by the default prompt, so build it with the file's own `_make_nodes`
(content `"caching architecture note number 0"`) and *then* demote it to `archival`. Creating a node
whose content does not match `"what about caching?"` makes `_seed_whisper_log` blow up on its
`assert row is not None` — `recall_search` finds nothing, so no whisper-log row exists to attach to.

```python
@pytest.mark.parametrize(
    "signal,source,was_injected,should_promote",
    [
        (1, "explicit", 1, True),
        (1, "auto_heuristic", 1, False),
        (-1, "explicit", 1, False),
        (1, "explicit", 0, False),
    ],
)
def test_only_qualified_positives_promote(engine, signal, source, was_injected, should_promote):
    """#223: promotion needs a qualified positive on an event the agent actually saw."""
    from ormah.models.node import Tier

    node_id = _make_nodes(engine, count=1)[0]
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))

    if was_injected:
        whisper_log_id = _seed_whisper_log(engine, node_id)
    else:
        whisper_log_id = _seed_held_back_whisper_log(engine, node_id)

    engine.submit_feedback(node_id, signal=signal, source=source, whisper_log_id=whisper_log_id)

    expected = Tier.working if should_promote else Tier.archival
    assert engine.file_store.load(node_id).tier is expected, (
        f"signal={signal} source={source} was_injected={was_injected}: "
        f"expected {expected}, got {engine.file_store.load(node_id).tier}"
    )
```

`_seed_held_back_whisper_log` is defined at line 520, *below* the #220 matrix — Python resolves it at
call time, so appending this test above or below it both work. Keep the new test next to the other
`submit_feedback` contracts rather than at the end of the file.

- [ ] **Step 9: Add the promote() guard and audit tests**

Append to `tests/test_engine/test_tier_manager.py`:

```python
def test_promote_returns_true_upward_and_false_sideways():
    """#223 relies on this guard: a working node must not be re-promoted."""
    from ormah.engine.tier_manager import TierManager
    from ormah.models.node import MemoryNode, NodeType, Tier

    manager = TierManager()

    node = MemoryNode(type=NodeType.fact, content="c", tier=Tier.archival)
    assert manager.promote(node, Tier.working) is True
    assert node.tier is Tier.working

    assert manager.promote(node, Tier.working) is False
    assert node.tier is Tier.working
```

Append to `tests/test_engine/test_audit_log.py`:

```python
def test_promotion_writes_one_promote_audit_entry(engine):
    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="about to be promoted"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))

    engine._record_confirmed_use(node_id)

    entries = engine.list_audit_log(node_id=node_id, operation="promote")
    assert len(entries) == 1


def test_a_non_promoting_confirmed_use_writes_no_promote_entry(engine):
    from ormah.models.node import CreateNodeRequest

    node_id, _ = engine.remember(CreateNodeRequest(content="already working"))

    engine._record_confirmed_use(node_id)

    assert engine.list_audit_log(node_id=node_id, operation="promote") == []
```

- [ ] **Step 10: Add the concurrency test**

Append to `tests/test_engine/test_recall_concurrency.py`, matching its existing threading idiom:

```python
def test_decay_and_promotion_leave_disk_and_index_agreeing(engine):
    """"Did not raise" does not catch divergence — this compares disk against index.

    run_decay holds _memory_operation_lock for its whole run (serialized_memory_job
    -> engine.memory_operation()), and _record_confirmed_use takes the same RLock,
    so the two cannot interleave in-process.
    """
    import threading

    from ormah.background.decay_manager import run_decay
    from ormah.models.node import CreateNodeRequest, Tier

    node_id, _ = engine.remember(CreateNodeRequest(content="contended node"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))

    errors: list[BaseException] = []

    def decay():
        try:
            run_decay(engine)
        except BaseException as e:  # noqa: BLE001 - recorded and re-raised below
            errors.append(e)

    def promote():
        try:
            engine._record_confirmed_use(node_id)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=decay), threading.Thread(target=promote)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    on_disk = engine.file_store.load(node_id).tier.value
    in_index = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["tier"]
    assert on_disk == in_index
```

- [ ] **Step 11: Run the whole engine suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`. Then run the concurrency file five times — it is the one test whose failure mode is timing-dependent:

```bash
for i in 1 2 3 4 5; do
  env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
      tests/test_engine/test_recall_concurrency.py -q >> concurrency.txt 2>&1
  echo "RUN_$i=$?" >> concurrency.txt
done
grep -c "^RUN_[1-5]=0$" concurrency.txt
```

Expected: `5`. Any other number means at least one run failed —
read `concurrency.txt` before rerunning; a flaky pass is not a pass.

- [ ] **Step 12: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 13: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_reversible_promotion.py \
        tests/test_engine/test_reinforcement_cooldown.py tests/test_engine/test_confirmed_use_contract.py \
        tests/test_engine/test_tier_manager.py tests/test_engine/test_audit_log.py \
        tests/test_engine/test_recall_concurrency.py
git commit -m "feat(engine): confirmed use promotes archival nodes back to working (#223)"
git show --stat HEAD
```

Expected: exactly seven files.

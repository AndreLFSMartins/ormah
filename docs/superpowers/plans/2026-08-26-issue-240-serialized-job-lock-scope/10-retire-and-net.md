# Task 10: retire `serialized_memory_job`, close the lock-order net, run the full suite

Read `00-overview.md` first. **Requires Tasks 1–9 all complete** — this task deletes the decorator every earlier task stopped using; running it before the others leaves the seven jobs broken.

**Files:**
- Modify: `src/ormah/background/memory_lock.py` — delete `serialized_memory_job`
- Modify: `tests/test_index/test_builder.py` — update the two docstrings that still name `@serialized_memory_job` (`:68`, `:89`)
- Test: `tests/test_index/test_builder.py` (append the lock-order net)
- Test: `tests/test_engine/test_memory_engine.py` (append the restore-abort integration test)

**Interfaces:**
- Consumes: everything from Tasks 1–9.
- Produces: nothing — this is the closing task.

## The three things this task proves that no single job task proves alone

1. **`serialized_memory_job` has no remaining callers.** A grep, not a test — deleting it and running the full suite is the actual proof.
2. **No apply step across the seven jobs acquires `L_mem` inside an open `db.transaction()`.** Tasks 3–9 each converted their own file correctly in isolation; this is the cross-cutting check that the *set* of conversions did not reopen #207's inversion. Reuses `test_index/test_builder.py`'s existing `OrderProbe` pattern (`:112-120`), extended to instrument `L_mem` while every job runs against a small seeded graph.
3. **An abort mid-run writes nothing after the epoch bump, end to end**, exercised through the real scheduler entry points (`restore_aware_job`-wrapped `run_x`), not through a single job's internals.

- [ ] **Step 1: Confirm no remaining references**

```bash
grep -rn "serialized_memory_job" src/ tests/
```

Expected: only the definition and its two `import` lines are gone from `src/`; the two docstring mentions in `tests/test_index/test_builder.py` still show — fixed in Step 2.

- [ ] **Step 2: Delete the decorator and update the docstrings**

In `src/ormah/background/memory_lock.py`, delete the `serialized_memory_job` function and its now-unused `from functools import wraps` **only if** `restore_aware_job` no longer needs `wraps` — it does (Task 1's `@wraps(job)`), so keep the import; delete only the function body added at the bottom in Task 1's Step 4.

In `tests/test_index/test_builder.py`, update the two docstrings (`:68`, `:89`) — replace:

```
    file_hash: L_db -> L_mem. Every @serialized_memory_job background job goes L_mem -> L_db.
```

with:

```
    file_hash: L_db -> L_mem. Every background job apply step goes L_mem -> L_db (#240).
```

and replace:

```
        """What @serialized_memory_job + a write txn do on every background job: L_mem, L_db."""
```

with:

```
        """What every background job's apply step does: L_mem, then a write txn (#240)."""
```

- [ ] **Step 3: Write the lock-order net (failing first is not expected here — write it, run it, it should already pass)**

Append to `tests/test_index/test_builder.py`:

```python
def test_no_background_job_takes_l_mem_inside_a_write_transaction(engine):
    """Cross-cutting net for #240: the inversion #207 fixed must not come back.

    Every job now acquires and releases L_mem repeatedly instead of once, so this
    is not redundant with test_builder_never_takes_file_lock_inside_write_transaction
    above — that test covers the builder's own entry points, not the seven jobs.
    """
    import json
    from unittest.mock import patch

    from ormah.background.auto_cluster import run_auto_cluster
    from ormah.background.auto_linker import run_auto_linker
    from ormah.background.conflict_detector import run_conflict_detection
    from ormah.background.consolidator import run_consolidation
    from ormah.background.decay_manager import run_decay
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.importance_scorer import run_importance_scoring
    from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType, Tier

    real_lock = engine._memory_operation_lock
    violations: list[int] = []

    class OrderProbe:
        def __enter__(self):
            tx_depth = getattr(engine.db._local, "tx_depth", 0)
            if tx_depth > 0:
                violations.append(tx_depth)
            return real_lock.__enter__()

        def __exit__(self, *args):
            return real_lock.__exit__(*args)

    engine._memory_operation_lock = OrderProbe()
    engine.file_store._operation_lock = engine._memory_operation_lock

    # Seed a small graph that gives every job something to do.
    ids = []
    for i in range(3):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"seed node {i} about project architecture", type=NodeType.fact,
            title=f"seed {i}"))
        ids.append(nid)
    engine.connect(ConnectRequest(
        source_id=ids[0], target_id=ids[1], edge=EdgeType.related_to, weight=1.0))
    engine.db.conn.execute("UPDATE nodes SET space = NULL WHERE id = ?", (ids[2],))
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = datetime('now', '-30 days'), tier = 'working' "
        "WHERE id = ?", (ids[0],))
    engine.db.conn.commit()

    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_min_cluster_size = 2

    fake_link = json.dumps({"relationship": "supports", "reason": "same topic"})
    fake_conflict = json.dumps({
        "same_subject": True, "conflict": False, "type": "none", "explanation": "n/a"})
    fake_dup = json.dumps({"is_duplicate": False, "reason": "distinct"})
    fake_consolidate = json.dumps({
        "title": "merged", "summary": "merged content", "type": "fact"})

    def fake_llm(*args, **kwargs):
        prompt = args[1] if len(args) > 1 else kwargs.get("prompt", "")
        if "contradict" in prompt.lower():
            return fake_conflict
        if "duplicate" in prompt.lower():
            return fake_dup
        if "consolidat" in prompt.lower():
            return fake_consolidate
        return fake_link

    with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
        run_decay(engine)
        run_importance_scoring(engine)
        run_auto_cluster(engine)
        run_auto_linker(engine)
        run_conflict_detection(engine)
        run_duplicate_detection(engine)
        run_consolidation(engine)

    assert not violations, f"L_mem acquired inside db.transaction(): depths {violations}"
```

- [ ] **Step 4: Run it**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_index/test_builder.py -q
```

Expected: passes. If it fails, the violation is in whichever job's apply step opens `db.transaction()` before taking `memory_operation_at` — cross-reference Tasks 3–9's wrapping order (guard always wraps the transaction, never the reverse).

- [ ] **Step 5: Write the restore-abort integration test**

Append to `tests/test_engine/test_memory_engine.py`:

```python
def test_a_restore_mid_run_aborts_every_job_without_partial_writes(engine):
    """#210 acceptance criterion, exercised across the real scheduler entry points."""
    import json
    from unittest.mock import patch

    from ormah.background.auto_linker import run_auto_linker
    from ormah.background.decay_manager import run_decay
    from ormah.models.node import CreateNodeRequest, NodeType, Tier

    stale_id, _ = engine.remember(CreateNodeRequest(
        content="a stale working node", type=NodeType.fact, tier=Tier.working,
        title="stale"))
    engine.db.conn.execute(
        "UPDATE nodes SET last_accessed = datetime('now', '-30 days') WHERE id = ?",
        (stale_id,))
    engine.db.conn.commit()

    edges_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    epoch_before = engine.restore_epoch

    # The bump must land AFTER the job read its entry epoch, never before the call:
    # restore_aware_job reads engine.restore_epoch at call time, so a pre-call bump would
    # simply hand the job the new value and there would be no mismatch to detect. Each job
    # below gets the bump at the point where a real restore would land in its own run.
    from ormah import lifecycle

    real_retrievability = lifecycle.retrievability
    bumped = {"done": False}

    def bump_then_compute(days_since, stability, **kwargs):
        """decay's seam: fires once per candidate in the unlocked outer scan."""
        if not bumped["done"]:
            bumped["done"] = True
            engine._restore_epoch += 1
        return real_retrievability(days_since, stability, **kwargs)

    lifecycle.retrievability = bump_then_compute
    try:
        run_decay(engine)  # returns cleanly
    finally:
        lifecycle.retrievability = real_retrievability

    row = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (stale_id,)).fetchone()
    assert row["tier"] == "working"  # not demoted

    engine.settings.llm_provider = "ollama"

    def bump_then_link(*args, **kwargs):
        """auto_linker's seam: the unlocked LLM call, right before its apply step."""
        engine._restore_epoch += 1
        return json.dumps({"relationship": "supports", "reason": "x"})

    with patch("ormah.background.llm_client.llm_generate", side_effect=bump_then_link):
        run_auto_linker(engine)  # also returns cleanly

    # Guard against silent vacuousness: both assertions hold trivially if neither job ever
    # reached an apply step. Each bump lives inside that job's own seam, so an epoch that
    # moved twice is proof both jobs actually got there.
    assert engine.restore_epoch == epoch_before + 2, \
        "a job never reached its apply step — the fixture stopped exercising it"
    edges_after = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    assert edges_after == edges_before
```

- [ ] **Step 6: Run it**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_engine/test_memory_engine.py -q -k restore_mid_run
```

Expected: passes.

- [ ] **Step 7: Full FORK-WORKFLOW verification**

All three gates, exactly as `00-overview.md` states:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
#   printed path MUST contain ormah-wt-240/
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
cat out.txt | tail -30
```

Expected: printed path contains `ormah-wt-240/`; `PYTEST_EXIT=0`. If anything fails, this is where a real regression across the seven jobs would surface (e.g. two jobs racing against the same seeded fixture in a way no single-file task caught) — do not mark this task done until the tail shows `PYTEST_EXIT=0`.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/background/memory_lock.py tests/test_index/test_builder.py \
        tests/test_engine/test_memory_engine.py
git commit -m "chore(#240): retire serialized_memory_job, close the lock-order net"
```

## After this task — not part of it

Per `00-overview.md`: open the PR with the "what this does not fix" and "findings 2/3 need their own issues" notes in the body. Any comment on #257 or #240 about the interaction with `test_recall_concurrency` waits for André's explicit confirmation first (spec §6) — this island's own `test_recall_concurrency.py` (checked during planning) is unrelated to #257's canary and needs no change.

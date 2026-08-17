### Task 2: `_record_confirmed_use` gets the cooldown and the bounded curve

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — the `_record_confirmed_use` body
- Modify: `src/ormah/config.py` — remove `fsrs_stability_growth` and its validator entry
- Modify: `tests/test_config_fsrs.py` — add back the removal test Task 1 left out (Step 4)
- Create: `tests/test_engine/test_reinforcement_cooldown.py`

**Four files, not three.** An earlier revision of this task listed three and omitted `tests/test_config_fsrs.py`, even though Step 4 requires editing it. Step 8's `git add` is corrected to match.

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: `_record_confirmed_use` keeps its name, its `@_serialized_memory_operation` decorator, and its two call sites.

**This is the task where the port differs from the source branch.** On `fix/221-bounded-reinforcement` this logic lives in `_touch_access`, called from five places including the search paths. Here it lives in `_record_confirmed_use`, called from two places, both behind the `_claim_confirmed_use` latch. **Port the body; discard the call sites.**

- [ ] **Step 1: Write the failing tests**

```bash
git show 4cf017f:tests/test_engine/test_reinforcement_cooldown.py > tests/test_engine/test_reinforcement_cooldown.py
```

Then rewrite every reference in that file:

- `engine._touch_access(node_id)` → `engine._record_confirmed_use(node_id)`
- any docstring or comment naming `_touch_access` → `_record_confirmed_use`
- the concurrency test's monkeypatch target stays `ormah.lifecycle`, unchanged

Read the file after rewriting and confirm no `_touch_access` remains.

The concurrency test asserts the **count of reinforcement calls**, not final stability. That is deliberate and must not be "improved": all racing threads read `S = 1.0` and write `1.5`, so the final value cannot tell one bump from four. It also widens the race window with a sleep rather than a barrier — a barrier inside the critical section deadlocks on correct code, because the second thread cannot enter until the first leaves.

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py -v`
Expected: failures showing unbounded growth — `_record_confirmed_use` still multiplies by `fsrs_stability_growth` with no cooldown, so a second call in the same window still moves `stability`.

- [ ] **Step 3: Replace the FSRS block in `_record_confirmed_use`**

Add `from ormah import lifecycle` to the module imports if it is not already there.

In `_record_confirmed_use`, replace this block:

```python
        review_anchor = node.last_review or node.last_accessed
        days_since = max((now - review_anchor).total_seconds() / 86400, 0.001)
        stability = node.stability if node.stability else self.settings.fsrs_initial_stability
        retrievability = math.exp(-days_since / stability)
        new_stability = stability * self.settings.fsrs_stability_growth * (retrievability ** -0.2)
        node.stability = round(min(new_stability, self.settings.fsrs_max_stability), 2)
        node.last_review = now
```

with:

```python
        # One numeric stability update per node per cooldown window (#221): the old
        # formula let repeated confirmed uses compound without bound. last_accessed
        # below still advances on every call, and Tasks 3-4 point decay and importance
        # at it, so a node in active use never reads as stale even though last_review
        # now lags by up to one cooldown window.
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
```

The zero-stability guard #220 added is not lost — it moves inside `lifecycle.reinforced_stability`, which takes `initial_stability` for exactly that case. The `0.001` floor becomes `0.0` because `lifecycle.spacing_factor` handles `R = 0` on the exponent instead of materializing it.

The trailing SQL `UPDATE` must now write `last_review` as `node.last_review.isoformat() if node.last_review else None` — the cooldown means it can be `None` on a node whose first confirmed use is skipped by a clock anomaly.

Then append this to `_record_confirmed_use`'s existing docstring, keeping #220's first line intact. The invariant is real on this branch too: the decorator takes the memory lock and the body opens `db.transaction()`, while the inverse order exists in the startup-only paths.

```python
        Serialized because the cooldown is a check-then-write pair (#221,
        council round 3): the two callers are behind the at-most-once claim
        latch, but the latch is per whisper event, not per node, so two
        concurrent confirmed uses of the same node would both read a stale
        last_review and both bump stability. _memory_operation_lock is an
        RLock, so a caller that already holds it re-enters safely.

        Lock order: this decorator acquires the memory lock before the body
        opens db.transaction(), i.e. memory-lock -> db-lock. The inverse order
        (db-lock -> memory-lock, via file_store calls inside a transaction)
        exists in _migrate_fsrs and _migrate_identity_tiers, but both run only
        from startup() before the server serves, so the two orders never
        interleave today. Invariant this depends on: never call file_store
        inside db.transaction() outside startup().
        """
```

- [ ] **Step 4: Remove `fsrs_stability_growth` and add its removal test**

Nothing reads the knob anymore after Step 3. Delete the field from `src/ormah/config.py`'s FSRS block and remove `"fsrs_stability_growth"` from `_fsrs_positive`'s field list. It was a base multiplier; `fsrs_growth_factor` is an additive term with different semantics, so this is a removal, not a rename.

Then append to `tests/test_config_fsrs.py` the test Task 1 deliberately left out, so the removal is pinned by a regression test:

```python
def test_the_removed_growth_knob_no_longer_exists(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir)
    assert not hasattr(settings, "fsrs_stability_growth")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_reinforcement_cooldown.py tests/test_config_fsrs.py -v`
Expected: all pass, including the removal test just added.

- [ ] **Step 6: Prove the serialization is load-bearing**

Remove `@_serialized_memory_operation` from `_record_confirmed_use`, run the concurrency test, and confirm it fails with `assert 4 == 1`. Restore the decorator and confirm green. Report both outputs. A guard nobody ever saw fail is a guard nobody knows works.

- [ ] **Step 7: The no-regression gate**

```bash
grep -rn "_touch_access" src/ tests/
grep -c "_record_confirmed_use(" src/ormah/engine/memory_engine.py
```

Expected: **exactly 3** for `_record_confirmed_use(` — the two call sites plus the `def`.

For `_touch_access`, expected is **exactly these three pre-existing hits, all of which must survive**:

- `src/ormah/background/forgetting_manager.py:54` — a stale comment naming the old method
- `tests/test_engine/test_mutation_stamping.py:95` — `def test_touch_access_does_not_advance_updated`
- `tests/test_store/test_file_store.py:121` — `def test_touch_access`

The last two are **test function names**, matched by substring; they exercise `FileStore.touch_access`, a different and legitimate method that this port does not touch. All three are byte-identical on the base commit `3bfe663` — verify that with `git grep -n "_touch_access" 3bfe663 -- src/ tests/` rather than judging by eye.

**This gate said "zero" and was wrong** — the plan author did not account for pre-existing substring matches. What it is actually checking is that no *engine method* named `_touch_access` exists and no call site was added. If your count differs from the list above, **stop and report**; never delete a hit to reach a number.

- [ ] **Step 8: Run the engine suite and commit**

Run: `./.venv/bin/python -m pytest tests/test_engine/ -q` — expected: all pass.

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/engine/memory_engine.py src/ormah/config.py tests/test_config_fsrs.py tests/test_engine/test_reinforcement_cooldown.py
git commit -m "fix(lifecycle): bounded stability growth, one update per node per day (#221)"
```


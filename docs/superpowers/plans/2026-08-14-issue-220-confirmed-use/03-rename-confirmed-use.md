# Task 3: Rename the mutator and prove `recall_node` precision

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:2408` (the helper), `:783` (its one remaining caller)
- Modify: `tests/test_engine/test_mutation_stamping.py:141-150`
- Modify: `tests/test_engine/test_confirmed_use.py` (append one class)

**Interfaces:**
- Consumes: Task 2's deletions — after Task 2 the helper has exactly one caller.
- Produces: `MemoryEngine._record_confirmed_use(self, node_id: str) -> None`. Tasks 4 and 5 call it by this exact name.

The rename is the structural defence. `_touch_access` reads like harmless bookkeeping, which is why four search loops adopted it; nobody writes `_record_confirmed_use` inside a `for r in results` by accident. **The body does not change** — the formula stays `stability * fsrs_stability_growth * (retrievability ** -0.2)`, uncapped and uncooled. Bounding is #221.

- [ ] **Step 1: Write the failing test for `recall_node` precision**

Append to `tests/test_engine/test_confirmed_use.py`:

```python
class TestRecallNodeConfirmsExactlyOneNode:
    """recall_node(id) is deliberate use of one node — never of its neighbours."""

    def test_recall_node_confirms_only_the_requested_node(self, engine):
        from ormah.models.node import ConnectRequest, EdgeType

        target = _create(engine, "Target", "The node the caller asked for.")
        neighbour = _create(engine, "Neighbour", "A connected but unrequested node.")
        engine.connect(ConnectRequest(
            source_id=target, target_id=neighbour, edge=EdgeType.related_to,
        ))

        before = _snapshot(engine, [target, neighbour])
        engine.recall_node(target)
        after = _snapshot(engine, [target, neighbour])

        assert after[target]["access_count"] == before[target]["access_count"] + 1
        assert after[neighbour] == before[neighbour]

    def test_the_only_lifecycle_mutator_is_named_for_what_it_does(self, engine):
        """Guard the rename: a helper named _touch_access must not come back."""
        assert hasattr(engine, "_record_confirmed_use")
        assert not hasattr(engine, "_touch_access")
```

- [ ] **Step 2: Run to verify it fails**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use.py::TestRecallNodeConfirmsExactlyOneNode -v )
```

Expected: `test_the_only_lifecycle_mutator_is_named_for_what_it_does` FAILS on `assert hasattr(engine, "_record_confirmed_use")`. `test_recall_node_confirms_only_the_requested_node` should already PASS — `recall_node` was always correct about neighbours. If it fails, that is a real defect this task must fix rather than a rename artefact; investigate before renaming anything.

- [ ] **Step 3: Rename the helper**

At `src/ormah/engine/memory_engine.py:2408`, replace the signature and docstring:

```python
    def _touch_access(self, node_id: str) -> None:
        """Update access stats and FSRS stability on both disk and DB."""
```

with:

```python
    def _record_confirmed_use(self, node_id: str) -> None:
        """Record one confirmed use of *node_id* on both disk and DB.

        The only lifecycle mutator in the engine. Confirmed use is a deliberate
        recall_node(id) or a source-qualified positive feedback event — never a
        result appearing in a list (#220, decision record #191).

        The reinforcement formula is deliberately unchanged here: bounding and
        the per-day cooldown are #221.
        """
```

Leave every line of the body exactly as it is.

- [ ] **Step 4: Update the one remaining caller**

At `src/ormah/engine/memory_engine.py:782-783`, replace:

```python
        # Touch access
        self._touch_access(resolved_node_id)
```

with:

```python
        # Deliberate fetch of one node — this is confirmed use, and only for
        # the requested node. The neighbours below are surfacing.
        self._record_confirmed_use(resolved_node_id)
```

- [ ] **Step 5: Update the stale test in `test_mutation_stamping.py`**

At `tests/test_engine/test_mutation_stamping.py:141-150`, replace:

```python
def test_engine_access_tracking_does_not_advance_updated(engine):
    node_id = _create(engine, "Read often", "Frequently accessed fact.")
    _backdate(engine.file_store, node_id)

    engine._touch_access(node_id)
```

with:

```python
def test_engine_access_tracking_does_not_advance_updated(engine):
    node_id = _create(engine, "Read often", "Frequently accessed fact.")
    _backdate(engine.file_store, node_id)

    engine._record_confirmed_use(node_id)
```

Leave the assertions below it unchanged — `updated` must still not advance, and `access_count` must still become 1.

Do **not** touch `test_touch_access_does_not_advance_updated` at `:95`. That one exercises `FileStore.touch_access`, a different method on a different class, which this plan does not modify.

- [ ] **Step 6: Confirm no reference to the old engine helper survives**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "_touch_access" src/ tests/ )
```

Expected: no output at all. (`FileStore.touch_access` has no leading underscore and will not match.)

- [ ] **Step 7: Run to verify the tests pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use.py \
                   tests/test_engine/test_mutation_stamping.py -v )
```

Expected: all PASS.

- [ ] **Step 8: Full suite and baseline diff**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/220-after-task3.txt )
diff /tmp/220-baseline-ids.txt /tmp/220-after-task3.txt
```

Expected: no added (`>`) lines.

- [ ] **Step 9: Lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && ruff check src/ tests/ )
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use.py \
          tests/test_engine/test_mutation_stamping.py && \
  git commit -m "refactor(lifecycle): name the mutator _record_confirmed_use

_touch_access read like harmless bookkeeping, which is how four search loops
came to call it. The body is unchanged; only the name and its single caller
move. recall_node keeps confirming exactly the requested node.

Refs #220" )
```

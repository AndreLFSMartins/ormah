# Task 4: `remember()` uses the configured initial stability

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (symbol: `MemoryEngine.remember`)
- Test: `tests/test_engine/test_memory_engine.py`

**Interfaces:**
- Consumes: `Settings.fsrs_initial_stability` from Task 1.
- Produces: nothing new; every node created after this task carries the configured stability.

**Three `1.0` defaults deliberately stay put:** `MemoryNode.stability`'s `Field(default=1.0)`, `parse_node`'s `meta.get("stability", 1.0)` fallback, and `stability REAL DEFAULT 1.0` in `schema.sql`. Changing any of them would retroactively rescale nodes that never carried the field, which #191 forbids. **Only `remember()` changes.**

The `Self` node built by `_ensure_self_node` keeps `1.0` and is unaffected: it is `core`, and `run_decay` queries `tier = 'working'` and additionally skips `user_node_id`. Do not touch `_ensure_self_node`.

---

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine/test_memory_engine.py`:

```python
def test_remember_uses_the_configured_initial_stability(engine):
    """Set a NON-default value: testing with 5.814 would pass by accident if
    someone also changed MemoryNode.stability's model default."""
    from ormah.models.node import CreateNodeRequest

    engine.settings.fsrs_initial_stability = 9.0

    node_id, _ = engine.remember(CreateNodeRequest(content="a brand new memory"))

    assert engine.file_store.load(node_id).stability == 9.0


def test_remember_writes_the_initial_stability_to_the_index(engine):
    from ormah.models.node import CreateNodeRequest

    engine.settings.fsrs_initial_stability = 9.0

    node_id, _ = engine.remember(CreateNodeRequest(content="a brand new memory"))

    row = engine.db.conn.execute(
        "SELECT stability FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["stability"] == 9.0
```

If the `engine` fixture's settings object is frozen and rejects attribute assignment, build a second engine from a `Settings(fsrs_initial_stability=9.0)` using whatever construction helper `tests/test_engine/test_memory_engine.py` already uses — do not add a `monkeypatch` of the module-level default, which would not prove the knob is read.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/test_memory_engine.py -q -k initial_stability > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. `assert 5.814 == 9.0` — the node took the model default, not the knob.

- [ ] **Step 3: Wire the knob**

In `src/ormah/engine/memory_engine.py`, in `remember`, add one keyword to the `MemoryNode(...)` construction, immediately after `confidence=req.confidence,`:

```python
            stability=self.settings.fsrs_initial_stability,
```

Nothing else in `remember` changes. `file_store.save` and `builder.index_single` already carry `stability` to disk and to the index.

- [ ] **Step 4: Run it to verify it passes**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/test_memory_engine.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 5: Check the consolidator and auto-linker did not regress**

`_apply_consolidation` calls `engine.remember`, so every consolidated node now starts at the new default.

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_engine/ tests/test_background/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the only failures are baseline names from `00-overview.md`. Any new name is a regression — fix it before committing.

- [ ] **Step 6: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_memory_engine.py
git commit -m "feat(engine): remember() starts nodes at the configured initial stability (#223)"
git show --stat HEAD
```

Expected: exactly two files.

# Task 6: Consolidation provenance and its ordering fail-safe

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (new symbol: `MemoryEngine._mark_superseded`)
- Modify: `src/ormah/background/consolidator.py` (symbol: `_apply_consolidation`)
- Test: `tests/test_background/test_consolidator.py`

**Interfaces:**
- Consumes: `MemoryNode.superseded_by` (Task 2), the index column that survives reindex (Task 3), and the promotion gate (Task 5).
- Produces: `MemoryEngine._mark_superseded(source_id: str, consolidation_id: str) -> None`.

**Why the field does not travel through `update_node`:** `superseded_by` is deliberately absent from `UpdateNodeRequest` (Task 2), so it needs its own writer. `_mark_superseded` is decorated `@_serialized_memory_operation` for the same reason `_record_confirmed_use` is — it is a load-modify-save pair.

**Why marking comes BEFORE demoting.** The order is the fail-safe. Crashing between the two leaves the node `working` + marked, which is harmless: the marker only blocks *automatic* promotion, and a `working` node is not looking for one. The reverse order would leave it `archival` + unmarked — exactly the promotable node #223 must not create.

**`_mark_superseded` deliberately does not call `touch_updated()`.** In the only production path the `engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))` on the next line advances `updated` anyway. Adding a second bump would be redundant, and `touch_updated`'s own docstring reserves it for content mutations saved by their caller.

---

- [ ] **Step 1: Write the failing provenance tests**

Append to `tests/test_background/test_consolidator.py`, matching the fixture and cluster-building idiom already in that file:

```python
def test_consolidation_marks_sources_as_superseded(engine):
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about pytest fixtures"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about pytest fixtures"))

    new_id = _apply_consolidation(engine, [a, b], "Pytest fixtures", "merged body", "fact")

    for source_id in (a, b):
        node = engine.file_store.load(source_id)
        assert node.tier is Tier.archival
        assert node.superseded_by == new_id


def test_the_marker_survives_in_the_index_after_consolidation(engine):
    """Regression for the INSERT OR REPLACE column drop (Task 3): update_node
    re-indexes the file one line after the marker is written."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest

    a, _ = engine.remember(CreateNodeRequest(content="source one about ruff config"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about ruff config"))

    new_id = _apply_consolidation(engine, [a, b], "Ruff config", "merged body", "fact")

    row = engine.db.conn.execute(
        "SELECT superseded_by FROM nodes WHERE id = ?", (a,)
    ).fetchone()
    assert row["superseded_by"] == new_id


def test_a_superseded_source_does_not_come_back_on_confirmed_use(engine):
    """The end-to-end point of #223's exception: consolidation sources stay buried."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about sqlite vec"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about sqlite vec"))
    _apply_consolidation(engine, [a, b], "sqlite-vec", "merged body", "fact")

    engine._record_confirmed_use(a)

    assert engine.file_store.load(a).tier is Tier.archival


def test_marking_precedes_demotion_so_a_crash_leaves_working_plus_marked(engine, monkeypatch):
    """Inject a demotion failure and assert the node ended working + marked,
    NOT archival + unmarked — the promotable node we must never create."""
    from ormah.background.consolidator import _apply_consolidation
    from ormah.models.node import CreateNodeRequest, Tier

    a, _ = engine.remember(CreateNodeRequest(content="source one about apscheduler"))
    b, _ = engine.remember(CreateNodeRequest(content="source two about apscheduler"))

    def boom(*args, **kwargs):
        raise RuntimeError("demotion failed")

    monkeypatch.setattr(engine, "update_node", boom)

    with pytest.raises(RuntimeError):
        _apply_consolidation(engine, [a, b], "APScheduler", "merged body", "fact")

    node = engine.file_store.load(a)
    assert node.tier is Tier.working
    assert node.superseded_by is not None
```

If `pytest` is not already imported in that file, add `import pytest` at the top.

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-223
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_background/test_consolidator.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: the printed path contains `ormah-wt-223/`. `assert None == '<new_id>'` — nothing writes the field yet.

- [ ] **Step 3: Add the writer to the engine**

In `src/ormah/engine/memory_engine.py`, add this method immediately after `_record_confirmed_use`:

```python
    @_serialized_memory_operation
    def _mark_superseded(self, source_id: str, consolidation_id: str) -> None:
        """Record that *source_id* was replaced by *consolidation_id* (#223).

        Written here rather than through update_node because superseded_by is
        deliberately absent from UpdateNodeRequest: it is policy state, and no
        agent sets it. Serialized for the same reason _record_confirmed_use is —
        this is a load-modify-save pair.

        `updated` is intentionally NOT advanced here: the consolidator's
        update_node(tier=archival) on the next line already does it, and
        touch_updated is reserved for content mutations.
        """
        node = self.file_store.load(source_id)
        if node is None:
            return
        node.superseded_by = consolidation_id
        self.file_store.save(node)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE nodes SET superseded_by = ? WHERE id = ?",
                (consolidation_id, source_id),
            )
```

- [ ] **Step 4: Call it before demoting**

In `src/ormah/background/consolidator.py`, in `_apply_consolidation`, change the closing loop. The `derived_from` edge is untouched — that is what gives "a generic `derived_from` target can promote" for free:

```python
    # Create derived_from edges, record supersession, then demote originals to archival.
    # Mark BEFORE demoting (#223): crashing between the two leaves the node working +
    # marked, which is harmless because the marker only blocks automatic promotion.
    # The reverse order would leave it archival + unmarked — a promotable node.
    for node_id in node_ids:
        try:
            engine.connect(ConnectRequest(
                source_id=new_id,
                target_id=node_id,
                edge=EdgeType.derived_from,
                weight=1.0,
            ))
        except Exception:
            pass
        engine._mark_superseded(node_id, new_id)
        engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))
```

- [ ] **Step 5: Run them to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_background/test_consolidator.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: `PYTEST_EXIT=0`. If `test_the_marker_survives_in_the_index_after_consolidation` fails while the others pass, Task 3's `builder.py` change is missing — go back and apply it; do not work around it here.

- [ ] **Step 6: Run the background and engine suites**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
    tests/test_background/ tests/test_engine/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
```

Expected: only baseline failure names from `00-overview.md`.

- [ ] **Step 7: Lint**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/ormah/engine/memory_engine.py src/ormah/background/consolidator.py \
        tests/test_background/test_consolidator.py
git commit -m "feat(consolidator): record supersession before demoting sources (#223)"
git show --stat HEAD
```

Expected: exactly three files.

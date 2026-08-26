### Task 2: Consolidation clusters carry the node type

**Files:**
- Modify: `src/ormah/background/consolidator.py:38-40` (the working-tier SELECT) and `:77-80` (the by-id re-read)
- Test: `tests/test_background/test_consolidator.py`, `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: `_norm`'s `"type": node.get("type", "")` line from Task 1 — unchanged by this task; it is what turns the new SELECT column into a batch field.
- Produces: `_find_consolidation_clusters(engine, limit: int = 4) -> list[list[dict]]` where each dict now has keys `id, title, content, space, type` (the by-id path also keeps `tier`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_consolidator.py`:

```python
def test_clusters_carry_node_type(consolidation_engine):
    """The agent picks the consolidated node's type — it must see the sources' type."""
    from ormah.background.consolidator import _find_consolidation_clusters

    engine, _ids = consolidation_engine
    engine.settings.consolidation_cluster_threshold = 0.0
    engine.settings.consolidation_min_cluster_size = 2

    clusters = _find_consolidation_clusters(engine, limit=4)

    assert clusters, "no cluster formed — the assertion below would never run"
    for cluster in clusters:
        for node in cluster:
            assert node.get("type") == "fact"
```

Append to the `TestConsolidationBatchFidelity` class in `tests/test_background/test_run_maintenance.py`:

```python
    def test_consolidation_cluster_carries_type(self, engine):
        seeded = _seed_long_nodes(engine, n=2, chars=600)
        engine.settings.consolidation_cluster_threshold = 0.0
        engine.settings.consolidation_min_cluster_size = 2

        batches = engine.get_maintenance_batches()

        clusters = batches["consolidation_clusters"]
        assert clusters, "no consolidation cluster produced — the assertion below would never run"
        checked = 0
        for cluster in clusters:
            for node in cluster:
                if node["id"] in seeded:
                    assert node["type"] == "fact"
                    checked += 1
        assert checked >= 2, "seeded nodes never appeared in a cluster"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py::test_clusters_carry_node_type \
  "tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity::test_consolidation_cluster_carries_type" \
  -v > /tmp/t2.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2.txt
cat /tmp/t2.txt
```

Expected: both FAIL. The first on `assert node.get("type") == "fact"` with `None == "fact"` (the key is absent); the second with `'' == 'fact'` (`_norm`'s default).

- [ ] **Step 3: Write the minimal implementation**

In `src/ormah/background/consolidator.py`, the working-tier scan:

```python
    rows = conn.execute(
        "SELECT id, title, content, space, type FROM nodes WHERE tier = 'working'"
    ).fetchall()
```

and the by-id re-read inside the match loop:

```python
            m_row = conn.execute(
                "SELECT id, title, content, space, tier, type FROM nodes WHERE id = ?",
                (mid,),
            ).fetchone()
```

Nothing else changes — `run_consolidation` builds its prompt from `title`/`content` and never iterates the dict keys, so the extra column is additive.

- [ ] **Step 4: Run the tests to verify they pass, then the consolidator suite for regressions**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py tests/test_background/test_run_maintenance.py \
  -v > /tmp/t2b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2b.txt
cat /tmp/t2b.txt
```

Expected: `PYTEST_EXIT=0`. This is the run that confirms the "additive column does not affect `run_consolidation`" claim, which is inferred until this command is green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_background/test_consolidator.py tests/test_background/test_run_maintenance.py src/ormah/background/consolidator.py
git commit -m "fix(consolidator): cluster candidates carry the node type (#259)"
```

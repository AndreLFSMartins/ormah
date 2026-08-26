### Task 4: Consolidation clusters carry the node type

**Files:**
- Modify: `src/ormah/background/consolidator.py` — the working-tier SELECT (around line 40) and the by-id re-read (around line 78)
- Test: `tests/test_background/test_consolidator.py`, `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: `_norm`'s `"type": node.get("type", "")` line, unchanged since Task 2 — it is what turns the new SELECT column into a batch field.
- Produces: `_find_consolidation_clusters(engine, limit: int = 4) -> list[list[dict]]` where each dict now carries `type` in addition to whatever it already carried.

**⚠️ Do not paste the SQL wholesale.** #261 (PR #263, open) adds a `_NOT_CONSOLIDATED` filter to
these same lines. Read the two queries as they stand in the island and add `type` to the column
list, preserving every other clause. If the island already contains `_NOT_CONSOLIDATED`, keep it.

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
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py::test_clusters_carry_node_type \
  "tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity::test_consolidation_cluster_carries_type" \
  -v > /tmp/t4.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t4.txt
cat /tmp/t4.txt
```

Expected: both FAIL. The first on `None == "fact"` (the key is absent from the row dict); the
second on `'' == 'fact'` (`_norm`'s default for a missing key).

- [ ] **Step 3: Write the implementation**

Read both queries first:

```bash
sed -n '36,45p' src/ormah/background/consolidator.py
sed -n '74,84p' src/ormah/background/consolidator.py
```

Add `type` to the column list of each, keeping every other clause intact. On an unmodified
island the result is:

```python
    rows = conn.execute(
        "SELECT id, title, content, space, type FROM nodes WHERE tier = 'working'"
    ).fetchall()
```

```python
            m_row = conn.execute(
                "SELECT id, title, content, space, tier, type FROM nodes WHERE id = ?",
                (mid,),
            ).fetchone()
```

Nothing else changes — `run_consolidation` builds its prompt from `title`/`content` and never
iterates the dict keys, so the extra column is additive.

- [ ] **Step 4: Run the tests, then the consolidator suite for regressions**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py tests/test_background/test_run_maintenance.py \
  -v > /tmp/t4b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t4b.txt
cat /tmp/t4b.txt
```

Expected: `PYTEST_EXIT=0`. This run is what confirms the "additive column does not affect
`run_consolidation`" claim, which is inferred until this command is green.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/consolidator.py tests/test_background/test_consolidator.py tests/test_background/test_run_maintenance.py
git commit -m "fix(consolidator): cluster candidates carry the node type (#259)"
```

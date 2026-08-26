### Task 1: Budget setting and the split helper

**Files:**
- Modify: `src/ormah/config.py:293` (after `claude_maintenance_batch_size`) and the validators block
- Modify: `src/ormah/engine/memory_engine.py` (new module-level helper, near the other module-level helpers at the top of the file)
- Test: `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Settings.claude_maintenance_cluster_max_chars: int = 24000`
  - `_split_cluster_to_budget(cluster: list[dict], budget: int) -> list[list[dict]]` in `ormah.engine.memory_engine` — Task 2 calls it.

This task adds capability only. Nothing calls the helper yet, so `get_maintenance_batches` behaves
exactly as before and the whole existing suite must stay green.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_run_maintenance.py`:

```python
class TestSplitClusterToBudget:

    def _node(self, nid: str, chars: int) -> dict:
        return {
            "id": nid,
            "title": f"node {nid}",
            "type": "fact",
            "space": "testproject",
            "content": "x" * chars,
        }

    def test_cluster_within_budget_is_returned_whole(self):
        from ormah.engine.memory_engine import _split_cluster_to_budget

        cluster = [self._node("a", 100), self._node("b", 100)]
        assert _split_cluster_to_budget(cluster, budget=1000) == [cluster]

    def test_oversized_cluster_is_split_not_truncated(self):
        from ormah.engine.memory_engine import _split_cluster_to_budget

        cluster = [self._node(n, 400) for n in ("a", "b", "c", "d")]
        result = _split_cluster_to_budget(cluster, budget=900)

        assert len(result) == 2
        assert [n["id"] for n in result[0]] == ["a", "b"]
        assert [n["id"] for n in result[1]] == ["c", "d"]
        for sub in result:
            for node in sub:
                assert len(node["content"]) == 400, "split must never slice content"

    def test_single_node_subcluster_is_dropped(self):
        from ormah.engine.memory_engine import _split_cluster_to_budget

        cluster = [self._node(n, 400) for n in ("a", "b", "c")]
        result = _split_cluster_to_budget(cluster, budget=900)

        assert len(result) == 1
        assert [n["id"] for n in result[0]] == ["a", "b"]

    def test_node_larger_than_budget_is_dropped_with_warning(self, caplog):
        from ormah.engine.memory_engine import _split_cluster_to_budget

        cluster = [self._node("huge", 5000), self._node("a", 100), self._node("b", 100)]
        with caplog.at_level("WARNING"):
            result = _split_cluster_to_budget(cluster, budget=900)

        assert [n["id"] for sub in result for n in sub] == ["a", "b"]
        assert "huge" in caplog.text

    def test_order_is_preserved(self):
        from ormah.engine.memory_engine import _split_cluster_to_budget

        cluster = [self._node(n, 200) for n in ("seed", "m1", "m2", "m3")]
        result = _split_cluster_to_budget(cluster, budget=500)

        assert [n["id"] for n in result[0]] == ["seed", "m1"]
        assert [n["id"] for n in result[1]] == ["m2", "m3"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py::TestSplitClusterToBudget -v > /tmp/t1.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1.txt
cat /tmp/t1.txt
```

Expected: all five FAIL with `ImportError: cannot import name '_split_cluster_to_budget'`.

- [ ] **Step 3: Add the setting**

In `src/ormah/config.py`, after `claude_maintenance_batch_size`:

```python
    claude_maintenance_batch_size: int = 25  # candidates per type per run
    claude_maintenance_cluster_max_chars: int = 24000  # per-cluster budget before splitting
```

and in the validators block:

```python
    @field_validator("claude_maintenance_cluster_max_chars")
    @classmethod
    def _claude_maintenance_cluster_max_chars_min(cls, v: int) -> int:
        if v < 1000:
            raise ValueError(f"claude_maintenance_cluster_max_chars must be >= 1000, got {v}")
        return v
```

- [ ] **Step 4: Write the helper**

At module level in `src/ormah/engine/memory_engine.py` (`logger` is already defined at line 47):

```python
def _split_cluster_to_budget(cluster: list[dict], budget: int) -> list[list[dict]]:
    """Bin-pack a consolidation cluster into sub-clusters within `budget` characters.

    Greedy, in the order the finder produced (seed first, then descending
    similarity). Content is never sliced: a node that does not fit starts the
    next sub-cluster. Sub-clusters of fewer than two nodes are dropped —
    there is nothing to consolidate a lone node with.
    """
    subs: list[list[dict]] = []
    current: list[dict] = []
    used = 0

    for node in cluster:
        size = len(node.get("content") or "")
        if size > budget:
            logger.warning(
                "consolidation: node %s (%d chars) exceeds the cluster budget of %d; "
                "leaving it in the working tier",
                node.get("id", "?"), size, budget,
            )
            continue
        if current and used + size > budget:
            subs.append(current)
            current = []
            used = 0
        current.append(node)
        used += size

    if current:
        subs.append(current)

    return [sub for sub in subs if len(sub) >= 2]
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py -v > /tmp/t1b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1b.txt
cat /tmp/t1b.txt
```

Expected: `PYTEST_EXIT=0`. The whole file green — the pre-existing tests must not move, since
nothing calls the helper yet.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/config.py src/ormah/engine/memory_engine.py tests/test_background/test_run_maintenance.py
git commit -m "feat(engine): add a per-cluster character budget and a split helper (#259)"
```

### Task 1: Budget setting and the prefix-selection helper

**Files:**
- Modify: `src/ormah/config.py` (after `claude_maintenance_batch_size`, and the validators block)
- Modify: `src/ormah/engine/memory_engine.py` (new module-level helper, near the other module-level helpers)
- Test: `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Settings.claude_maintenance_cluster_max_chars: int = 24000`
  - `_select_cluster_within_budget(cluster: list[dict], budget: int, min_size: int) -> list[dict]` in `ormah.engine.memory_engine` — Task 2 calls it.

This task adds capability only. Nothing calls the helper yet, so `get_maintenance_batches`
behaves exactly as before and the existing suite must stay green.

**Why a prefix and not bin-packing.** v2 specified greedy next-fit packing. Both `/council` peers
converged on its defect and it was confirmed by execution: `[500,500,400,400]` at budget 900
yields `[500],[500,400],[400]`, and the `len >= 2` filter then deletes two nodes that would have
paired; a large seed followed by smaller matches gets the **seed** dropped, silently. A prefix has
no bins, so no orphan singletons, and it keeps the most central nodes because
`_find_consolidation_clusters` already returns seed-first, matches by descending similarity.

**Why the budget measures `json.dumps(node)`.** The normalized node also carries `id`, `title`,
`type` and `space`, and JSON escaping can multiply size — 3000 NUL characters of content serialize
to 18.070 characters, roughly 6x. Budgeting `len(content)` measures the wrong thing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_run_maintenance.py`:

```python
import json


class TestSelectClusterWithinBudget:
    """The per-node metadata overhead is ~77 chars for these fixtures; budgets below
    are chosen with that measured overhead in mind, so each case exercises the
    boundary it names."""

    def _node(self, nid: str, chars: int, content: str | None = None) -> dict:
        return {
            "id": nid,
            "title": f"t{nid}",
            "type": "fact",
            "space": "s",
            "content": content if content is not None else "x" * chars,
        }

    def _size(self, node: dict) -> int:
        return len(json.dumps(node, ensure_ascii=False))

    def test_cluster_within_budget_is_returned_whole(self):
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node(f"n{i}", 400) for i in range(5)]
        assert _select_cluster_within_budget(cluster, budget=24000, min_size=2) == cluster

    def test_oversized_cluster_is_trimmed_to_a_prefix(self, caplog):
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node(f"n{i}", 500) for i in range(4)]
        budget = self._size(cluster[0]) * 2 + 10  # exactly two nodes fit

        with caplog.at_level("INFO"):
            result = _select_cluster_within_budget(cluster, budget=budget, min_size=2)

        assert [n["id"] for n in result] == ["n0", "n1"]
        for node in result:
            assert len(node["content"]) == 500, "trim must never slice a node"
        assert "trimmed" in caplog.text

    def test_a_kept_cluster_always_contains_the_seed(self):
        """The invariant next-fit violated: never consolidate without the seed."""
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node("seed", 600), self._node("m1", 400), self._node("m2", 400)]
        budget = self._size(cluster[0]) + self._size(cluster[1]) + 10

        result = _select_cluster_within_budget(cluster, budget=budget, min_size=2)

        assert result, "this budget fits two nodes; the cluster should survive"
        assert result[0]["id"] == "seed"

    def test_cluster_below_min_size_after_trim_is_dropped_with_warning(self, caplog):
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node(f"n{i}", 12001) for i in range(5)]

        with caplog.at_level("WARNING"):
            result = _select_cluster_within_budget(cluster, budget=24000, min_size=2)

        assert result == []
        assert caplog.records, "a dropped cluster must never be silent"

    def test_seed_larger_than_the_budget_drops_the_cluster(self, caplog):
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node("huge", 30000), self._node("a", 100), self._node("b", 100)]

        with caplog.at_level("WARNING"):
            result = _select_cluster_within_budget(cluster, budget=24000, min_size=2)

        assert result == []
        assert caplog.records

    def test_budget_counts_serialized_size_not_raw_content(self, caplog):
        """3000 NUL chars are 3000 raw but 18_070 serialized — a len(content)
        budget would keep this cluster; the serialized budget must drop it."""
        from ormah.engine.memory_engine import _select_cluster_within_budget

        cluster = [self._node("esc", 0, content="\x00" * 3000), self._node("a", 400)]
        assert self._size(cluster[0]) > 5000 > len(cluster[0]["content"])

        with caplog.at_level("WARNING"):
            result = _select_cluster_within_budget(cluster, budget=5000, min_size=2)

        assert result == [], "the budget is measuring raw content, not the serialized node"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py::TestSelectClusterWithinBudget -v > /tmp/t1.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1.txt
cat /tmp/t1.txt
```

Expected: all six FAIL with `ImportError: cannot import name '_select_cluster_within_budget'`.

- [ ] **Step 3: Add the setting**

In `src/ormah/config.py`, after `claude_maintenance_batch_size`:

```python
    claude_maintenance_batch_size: int = 25  # candidates per type per run
    claude_maintenance_cluster_max_chars: int = 24000  # serialized budget per cluster
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

At module level in `src/ormah/engine/memory_engine.py` (`json` is imported at the top of the file;
add the import if it is not, and `logger` is defined at line 47):

```python
def _select_cluster_within_budget(
    cluster: list[dict], budget: int, min_size: int
) -> list[dict]:
    """Longest prefix of `cluster` whose serialized size fits `budget`.

    The cluster arrives seed-first, then matches by descending similarity, so the
    prefix keeps the most central nodes. A node is never sliced; nodes left out
    stay in the working tier and return on the next cycle. Returns [] when the
    prefix cannot reach `min_size`.
    """
    selected: list[dict] = []
    used = 0

    for node in cluster:
        size = len(json.dumps(node, ensure_ascii=False))
        if used + size > budget:
            break
        selected.append(node)
        used += size

    if len(selected) < min_size:
        logger.warning(
            "consolidation: cluster dropped — only %d of %d nodes fit the %d-char budget "
            "(minimum %d); leaving them in the working tier",
            len(selected), len(cluster), budget, min_size,
        )
        return []

    if len(selected) < len(cluster):
        logger.info(
            "consolidation: cluster trimmed from %d to %d nodes to fit the %d-char budget",
            len(cluster), len(selected), budget,
        )

    return selected
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py -v > /tmp/t1b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1b.txt
cat /tmp/t1b.txt
```

Expected: `PYTEST_EXIT=0`, whole file green — the pre-existing tests must not move, since nothing
calls the helper yet.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/config.py src/ormah/engine/memory_engine.py tests/test_background/test_run_maintenance.py
git commit -m "feat(engine): add a serialized per-cluster budget and prefix selection (#259)"
```

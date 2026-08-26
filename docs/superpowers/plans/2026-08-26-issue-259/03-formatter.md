### Task 3: The MCP formatter stops cutting cluster content

**Files:**
- Modify: `src/ormah/adapters/mcp_adapter.py:183`
- Test: `tests/test_adapters/test_mcp_adapter.py`

**Interfaces:**
- Consumes: the uncapped `content` Task 2 now puts in `batches["consolidation_clusters"]`, and the split that keeps it bounded.
- Produces: nothing later tasks depend on.

**Why this task exists.** This is the cut the agent actually reads. `ormah-maintenance` calls
`mcp__ormah__run_maintenance`; `_dispatch` returns `_format_maintenance_batches(batches)`, which
renders cluster nodes with `n['content'][:200]`. Without this task the previous two tasks change
the JSON in `job.batches` and in `GET /agent/maintenance`, while the model keeps summarizing from
200 characters — half of what issue #259 denounces. `tests/test_adapters/test_mcp_adapter.py`
currently covers only the "nothing to process" path, so nothing catches it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adapters/test_mcp_adapter.py`:

```python
def _batches_with_cluster(content: str) -> dict:
    node = {
        "id": "n1",
        "title": "Long node",
        "type": "fact",
        "space": "testproject",
        "content": content,
    }
    other = dict(node, id="n2", title="Other node")
    return {
        "summary": "1 cluster(s)",
        "link_candidates": [],
        "conflict_candidates": [],
        "merge_candidates": [],
        "consolidation_clusters": [[node, other]],
    }


def test_formatter_emits_full_cluster_content():
    """The agent must see the whole source, not the first 200 chars."""
    content = "x" * 600
    text = mcp_adapter._format_maintenance_batches(_batches_with_cluster(content))

    assert content in text, "cluster content was truncated before reaching the agent"


def test_formatter_still_truncates_screening_pairs():
    """Screening stays a screening view — 300 chars, unchanged."""
    long_content = "y" * 600
    node_a = {
        "id": "a", "title": "A", "type": "fact", "space": "s", "content": long_content,
    }
    node_b = dict(node_a, id="b", title="B")
    batches = {
        "summary": "1 link candidates",
        "link_candidates": [{"node_a": node_a, "node_b": node_b, "similarity": 0.9}],
        "conflict_candidates": [],
        "merge_candidates": [],
        "consolidation_clusters": [],
    }

    text = mcp_adapter._format_maintenance_batches(batches)

    assert long_content not in text
    assert long_content[:300] in text
```

- [ ] **Step 2: Run the tests to verify the first fails**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_adapters/test_mcp_adapter.py -k formatter -v > /tmp/t3.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t3.txt
cat /tmp/t3.txt
```

Expected: `test_formatter_emits_full_cluster_content` **FAILS** (only 200 `x` are rendered);
`test_formatter_still_truncates_screening_pairs` PASSES — it pins behaviour that must not change.

- [ ] **Step 3: Write the implementation**

In `src/ormah/adapters/mcp_adapter.py`, inside the consolidation-cluster loop:

```python
            for j, n in enumerate(cluster, 1):
                lines.append(f"  {j}. [{n['type']}] {n['id']}  \"{n['title']}\"")
                if n.get("content"):
                    lines.append(f"     {n['content']}")
```

Only the cluster loop changes. `_pair_block`'s two `[:300]` slices stay exactly as they are.

- [ ] **Step 4: Run the tests to verify both pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_adapters/test_mcp_adapter.py -v > /tmp/t3b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t3b.txt
cat /tmp/t3b.txt
```

Expected: `PYTEST_EXIT=0`, whole file green.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/adapters/mcp_adapter.py tests/test_adapters/test_mcp_adapter.py
git commit -m "fix(mcp): the maintenance formatter emits full cluster content (#259)"
```

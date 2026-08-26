### Task 1: Consolidation batch carries full content

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1824-1831` (the `_norm` helper inside `get_maintenance_batches`) and `:1855-1858` (the consolidation batch comprehension)
- Test: `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_norm(node: dict, content_limit: int | None = 400) -> dict` — a module-local closure inside `get_maintenance_batches`. Task 2 asserts on the `type` key this same helper emits.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_run_maintenance.py`:

```python
def _seed_long_nodes(engine, n: int = 2, chars: int = 600) -> dict[str, str]:
    """Create n nodes whose content is exactly `chars` long. Returns {id: content}.

    auto_link is disabled during remember() so the pairs stay unchecked and remain
    available as link candidates later.
    """
    base = "Python uses indentation to define code block scope. "
    seeded: dict[str, str] = {}
    orig_threshold = engine.settings.auto_link_similarity_threshold
    engine.settings.auto_link_similarity_threshold = 999.0
    try:
        for i in range(n):
            content = (f"{i} " + base * 20)[:chars]
            assert len(content) == chars
            req = CreateNodeRequest(
                content=content,
                type=NodeType.fact,
                title=f"Python indentation {i}",
                space="testproject",
            )
            nid, _ = engine.remember(req)
            seeded[nid] = content
    finally:
        engine.settings.auto_link_similarity_threshold = orig_threshold
    return seeded


class TestConsolidationBatchFidelity:

    def test_consolidation_cluster_carries_full_content(self, engine):
        seeded = _seed_long_nodes(engine, n=2, chars=600)
        engine.settings.consolidation_cluster_threshold = 0.0
        engine.settings.consolidation_min_cluster_size = 2

        batches = engine.get_maintenance_batches()

        clusters = batches["consolidation_clusters"]
        assert clusters, "no consolidation cluster produced — the fixture is not exercising the batch"
        checked = 0
        for cluster in clusters:
            for node in cluster:
                if node["id"] in seeded:
                    assert node["content"] == seeded[node["id"]]
                    assert len(node["content"]) == 600
                    checked += 1
        assert checked >= 2, "seeded nodes never appeared in a cluster"

    def test_screening_batches_still_truncate(self, engine):
        seeded = _seed_long_nodes(engine, n=2, chars=600)
        engine.settings.auto_link_similarity_threshold = 0.0

        batches = engine.get_maintenance_batches()

        assert batches["link_candidates"], "no link candidates — the guard would pass vacuously"
        checked = 0
        for candidate in batches["link_candidates"]:
            for node in (candidate["node_a"], candidate["node_b"]):
                assert len(node["content"]) <= 400
                if node["id"] in seeded:
                    assert node["content"] == seeded[node["id"]][:400]
                    checked += 1
        assert checked >= 2, "seeded nodes never appeared as link candidates"
```

- [ ] **Step 2: Run the tests to verify the first fails and the second passes**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity -v > /tmp/t1.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1.txt
cat /tmp/t1.txt
```

Expected: `test_consolidation_cluster_carries_full_content` **FAILS** on `assert node["content"] == seeded[node["id"]]` (the value is the first 400 chars). `test_screening_batches_still_truncate` **PASSES** — it is the over-fix guard and is green by design both before and after.

- [ ] **Step 3: Write the minimal implementation**

In `src/ormah/engine/memory_engine.py`, replace the `_norm` helper:

```python
        def _norm(node: dict, content_limit: int | None = 400) -> dict:
            content = node.get("content") or ""
            return {
                "id": node.get("id", ""),
                "title": node.get("title", ""),
                "type": node.get("type", ""),
                "space": node.get("space", ""),
                "content": content if content_limit is None else content[:content_limit],
            }
```

and, in the returned dict, the consolidation entry only:

```python
            "consolidation_clusters": [
                [_norm(n, content_limit=None) for n in cluster]
                for cluster in consolidation_clusters
            ],
```

Leave `_norm_pair` and the three screening entries exactly as they are.

- [ ] **Step 4: Run the tests to verify both pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py -v > /tmp/t1b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t1b.txt
cat /tmp/t1b.txt
```

Expected: `PYTEST_EXIT=0`, whole file green — including the pre-existing `test_content_truncated_to_400`, which must not regress.

- [ ] **Step 5: Commit**

```bash
git add tests/test_background/test_run_maintenance.py src/ormah/engine/memory_engine.py
git commit -m "fix(engine): maintenance consolidation batch carries full source content (#259)"
```

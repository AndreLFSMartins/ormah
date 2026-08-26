### Task 2: Uncap the consolidation batch and apply the split

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1824-1831` (the `_norm` closure) and `:1855-1858` (the consolidation entry of the returned dict)
- Test: `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: `_split_cluster_to_budget(cluster, budget)` and `Settings.claude_maintenance_cluster_max_chars` from Task 1.
- Produces: `_norm(node: dict, content_limit: int | None = 400) -> dict` — Task 4 asserts on the `type` key this helper emits; Task 3 consumes the uncapped `content` it now puts in `consolidation_clusters`.

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
            content = (f"{i} " + base * 40)[:chars]
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

    def test_norm_truncates_screening_batches(self, engine, monkeypatch):
        """The over-fix guard: it must fail if _norm stops truncating screening.

        It monkeypatches the finder because the real one already slices to 400 in
        `_node_dict` (auto_linker.py:154), so asserting on its output would stay
        green even with _norm's limit removed.
        """
        import ormah.background.auto_linker as auto_linker

        long_node = {
            "id": "n1",
            "title": "long",
            "type": "fact",
            "space": "testproject",
            "content": "y" * 600,
        }
        other = dict(long_node, id="n2")
        monkeypatch.setattr(
            auto_linker,
            "_find_link_candidates",
            lambda engine, limit: [{"node_a": long_node, "node_b": other, "similarity": 0.9}],
        )

        batches = engine.get_maintenance_batches()

        assert batches["link_candidates"], "monkeypatched finder produced nothing"
        for candidate in batches["link_candidates"]:
            for node in (candidate["node_a"], candidate["node_b"]):
                assert len(node["content"]) == 400, "screening batches must stay truncated"

    def test_oversized_cluster_is_split_in_the_batch(self, engine, monkeypatch):
        """A cluster over budget reaches the batch as sub-clusters, content intact."""
        import ormah.background.consolidator as consolidator

        nodes = [
            {
                "id": f"n{i}",
                "title": f"node {i}",
                "type": "fact",
                "space": "testproject",
                "content": "z" * 400,
            }
            for i in range(4)
        ]
        monkeypatch.setattr(consolidator, "_find_consolidation_clusters", lambda engine, limit: [nodes])
        engine.settings.claude_maintenance_cluster_max_chars = 900

        batches = engine.get_maintenance_batches()

        clusters = batches["consolidation_clusters"]
        assert len(clusters) == 2, f"expected a split into 2 sub-clusters, got {len(clusters)}"
        for cluster in clusters:
            for node in cluster:
                assert len(node["content"]) == 400, "split must never slice content"

    def test_worst_case_cardinality_stays_bounded(self, engine, monkeypatch):
        """Four max-size clusters of oversized nodes must not produce an unbounded batch."""
        import json

        import ormah.background.consolidator as consolidator

        budget = engine.settings.claude_maintenance_cluster_max_chars
        big_clusters = [
            [
                {
                    "id": f"c{c}n{i}",
                    "title": f"node {c}-{i}",
                    "type": "fact",
                    "space": "testproject",
                    "content": "w" * 100_000,
                }
                for i in range(5)
            ]
            for c in range(4)
        ]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda engine, limit: big_clusters
        )

        batches = engine.get_maintenance_batches()

        payload = json.dumps(batches["consolidation_clusters"])
        assert len(payload) <= 4 * budget + 4096, (
            f"consolidation batch is unbounded: {len(payload)} chars"
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity -v > /tmp/t2.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2.txt
cat /tmp/t2.txt
```

Expected, and each for its own reason — read the failures, do not just count them:

- `test_consolidation_cluster_carries_full_content` FAILS: content is the first 400 chars.
- `test_norm_truncates_screening_batches` PASSES: it is a guard, green before and after. It is
  not vacuous now — with `_norm`'s default changed to `None` it goes red, which is the whole
  point of the monkeypatch.
- `test_oversized_cluster_is_split_in_the_batch` FAILS: one cluster comes back, not two.
- `test_worst_case_cardinality_stays_bounded` FAILS on the payload size (4 x 5 x 400 chars of
  `_norm` truncation is well under budget today, so if this one passes before the fix, check
  that the monkeypatch actually took effect before moving on).

- [ ] **Step 3: Write the implementation**

Replace the `_norm` closure in `get_maintenance_batches`:

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

Right after `consolidation_clusters = _find_consolidation_clusters(self, limit=4)`, apply the
budget:

```python
        cluster_budget = getattr(self.settings, "claude_maintenance_cluster_max_chars", 24000)
        consolidation_clusters = [
            sub
            for cluster in consolidation_clusters
            for sub in _split_cluster_to_budget(cluster, cluster_budget)
        ]
```

and in the returned dict, the consolidation entry only:

```python
            "consolidation_clusters": [
                [_norm(n, content_limit=None) for n in cluster]
                for cluster in consolidation_clusters
            ],
```

Leave `_norm_pair` and the three screening entries exactly as they are. The `summary` string is
built from `consolidation_clusters` after the split, so its cluster count reports sub-clusters —
that is intended and matches #192's decision.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py -v > /tmp/t2b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2b.txt
cat /tmp/t2b.txt
```

Expected: `PYTEST_EXIT=0`, whole file green — including the pre-existing
`test_content_truncated_to_400`, which asserts on `link_candidates` and must not regress.

- [ ] **Step 5: Prove the guard actually guards**

Not a code change — a one-off mutation check, then revert it:

```bash
# temporarily change _norm's default to None
sed -i '' 's/def _norm(node: dict, content_limit: int | None = 400)/def _norm(node: dict, content_limit: int | None = None)/' src/ormah/engine/memory_engine.py
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  "tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity::test_norm_truncates_screening_batches" -q > /tmp/t2m.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2m.txt
cat /tmp/t2m.txt
git checkout -- src/ormah/engine/memory_engine.py
```

Expected: the mutated run **FAILS**. If it passes, the guard is still vacuous — fix the test
before committing. This step exists because v1's guard passed this mutation.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_background/test_run_maintenance.py
git commit -m "fix(engine): consolidation batch carries full content, split to budget (#259)"
```

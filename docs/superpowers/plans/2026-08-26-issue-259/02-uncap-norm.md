### Task 2: Uncap the consolidation batch and apply the trim

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1824-1831` (the `_norm` closure) and `:1855-1858` (the consolidation entry of the returned dict)
- Test: `tests/test_background/test_run_maintenance.py`

**Interfaces:**
- Consumes: `_select_cluster_within_budget(cluster, budget, min_size)` and `Settings.claude_maintenance_cluster_max_chars` from Task 1.
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
        green even with _norm's limit removed. Both council peers found that.
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

    def test_oversized_cluster_is_trimmed_in_the_batch(self, engine, monkeypatch):
        """A cluster over budget reaches the batch as a prefix, contents intact."""
        import json

        import ormah.background.consolidator as consolidator

        nodes = [
            {
                "id": f"n{i}",
                "title": f"node {i}",
                "type": "fact",
                "space": "testproject",
                "content": "z" * 6000,
            }
            for i in range(5)
        ]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda engine, limit: [nodes]
        )
        engine.settings.claude_maintenance_cluster_max_chars = 24000

        batches = engine.get_maintenance_batches()

        clusters = batches["consolidation_clusters"]
        assert len(clusters) == 1, "a prefix is one cluster, never several"
        kept = clusters[0]
        assert [n["id"] for n in kept] == ["n0", "n1", "n2"], (
            "three 6000-char nodes serialize to 18_258; a fourth reaches 24_344, over 24_000"
        )
        for node in kept:
            assert len(node["content"]) == 6000, "trim must never slice a node"
        assert len(json.dumps(kept, ensure_ascii=False)) <= 24000

    def test_worst_case_cardinality_stays_bounded(self, engine, monkeypatch):
        """Four max-size clusters of large nodes stay within `4 x budget`.

        With one prefix per cluster the bound is exactly `n_clusters * budget` —
        unlike v2's bin-packing, where the sub-cluster count was unbounded. Node
        size is 6000 chars so the trim actually fires (3 of 5 survive), and
        `assert clusters` keeps the test from passing by emitting nothing.
        """
        import json

        import ormah.background.consolidator as consolidator

        budget = engine.settings.claude_maintenance_cluster_max_chars
        max_nodes = engine.settings.consolidation_max_cluster_nodes
        big_clusters = [
            [
                {
                    "id": f"c{c}n{i}",
                    "title": f"node {c}-{i}",
                    "type": "fact",
                    "space": "testproject",
                    "content": "w" * 6000,
                }
                for i in range(max_nodes)
            ]
            for c in range(4)
        ]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda engine, limit: big_clusters
        )

        batches = engine.get_maintenance_batches()

        clusters = batches["consolidation_clusters"]
        assert clusters, "the trim dropped everything — the fixture proves nothing"
        assert len(clusters) == 4, "one prefix per cluster"
        for sub in clusters:
            assert len(json.dumps(sub, ensure_ascii=False)) <= budget

        payload = json.dumps(clusters, ensure_ascii=False)
        bound = 4 * budget + 4096
        assert len(payload) <= bound, (
            f"consolidation batch is unbounded: {len(payload)} chars, bound {bound}"
        )
```

- [ ] **Step 2: Run the tests and read each failure**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-259
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity -v > /tmp/t2.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2.txt
cat /tmp/t2.txt
```

Expected, each for its own reason — read the messages, do not just count:

- `test_consolidation_cluster_carries_full_content` **FAILS**: content is the first 400 chars.
- `test_norm_truncates_screening_batches` **PASSES**. It is a guard, green before and after; Step 5
  proves it is not vacuous.
- `test_oversized_cluster_is_trimmed_in_the_batch` **FAILS**: all five nodes come back, each cut to
  400 chars, so both the id list and the content-length assertion are wrong.
- `test_worst_case_cardinality_stays_bounded` **PASSES**. Today `_norm` cuts everything to 400
  chars, so four short clusters serialize well within budget. This is a bound guard, not a red
  test — its job is to fail if a later change removes the trim, and Step 5 proves that it does.

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

Right after `consolidation_clusters = _find_consolidation_clusters(self, limit=4)`, normalize and
trim in one step — the budget must measure what actually ships, so `_norm` runs first:

```python
        cluster_budget = getattr(self.settings, "claude_maintenance_cluster_max_chars", 24000)
        min_size = self.settings.consolidation_min_cluster_size
        consolidation_clusters = [
            trimmed
            for cluster in consolidation_clusters
            if (trimmed := _select_cluster_within_budget(
                [_norm(n, content_limit=None) for n in cluster], cluster_budget, min_size
            ))
        ]
```

and in the returned dict, the consolidation entry becomes a plain passthrough — the nodes are
already normalized:

```python
            "consolidation_clusters": consolidation_clusters,
```

Leave `_norm_pair` and the three screening entries exactly as they are. The `summary` string is
built from `consolidation_clusters` after the trim, so a cluster dropped for exceeding the budget
is not counted — correct, since it was never handed to the agent.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_run_maintenance.py -v > /tmp/t2b.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2b.txt
cat /tmp/t2b.txt
```

Expected: `PYTEST_EXIT=0`, whole file green — including the pre-existing
`test_content_truncated_to_400`, which asserts on `link_candidates` and must not regress.

- [ ] **Step 5: Commit the implementation FIRST**

The mutation checks below rewrite `memory_engine.py` and restore it from git. If the Task 2
implementation is still uncommitted at that point, the restore wipes it: the file reverts to
Task 1's HEAD, `content_limit` and the trim call site vanish, Mutation B's `sed` finds no pattern,
and its test runs against the old 400-char truncation — where the plan already says it passes. A
green Mutation B would then mean nothing, and Step 6 would commit new tests against a reverted
engine. Both council peers flagged this; the Codex peer at confidence 1.0.

So commit before mutating:

```bash
git add src/ormah/engine/memory_engine.py tests/test_background/test_run_maintenance.py
git commit -m "fix(engine): consolidation batch carries full content, trimmed to budget (#259)"
```

- [ ] **Step 6: Prove both guards actually guard (mutation check)**

Neither guard is red in Step 2, so each must be shown to go red under the mutation it exists to
catch. **This step is not optional:** v1 shipped a guard that passed its own mutation.

Mutation A — remove `_norm`'s screening limit:

```bash
cp src/ormah/engine/memory_engine.py /tmp/me_backup.py
sed -i '' 's/def _norm(node: dict, content_limit: int | None = 400)/def _norm(node: dict, content_limit: int | None = None)/' src/ormah/engine/memory_engine.py
git diff --stat src/ormah/engine/memory_engine.py   # must show exactly 1 changed line
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest   "tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity::test_norm_truncates_screening_batches" -q > /tmp/t2mA.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2mA.txt
cat /tmp/t2mA.txt
cp /tmp/me_backup.py src/ormah/engine/memory_engine.py
```

Expected: **FAILS** — content arrives at 600 chars instead of 400. If `git diff --stat` shows 0
changed lines, the `sed` pattern did not match: fix the pattern, because an unapplied mutation
looks exactly like a passing guard.

Mutation B — remove the trim:

```bash
cp src/ormah/engine/memory_engine.py /tmp/me_backup.py
sed -i '' 's/if (trimmed := _select_cluster_within_budget(/if (trimmed := (lambda c, b, m: c)(/' src/ormah/engine/memory_engine.py
git diff --stat src/ormah/engine/memory_engine.py   # must show exactly 1 changed line
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest   "tests/test_background/test_run_maintenance.py::TestConsolidationBatchFidelity::test_worst_case_cardinality_stays_bounded" -q > /tmp/t2mB.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2mB.txt
cat /tmp/t2mB.txt
cp /tmp/me_backup.py src/ormah/engine/memory_engine.py
```

Expected: **FAILS** on the per-cluster serialized assertion — five 6000-char nodes serialize to
30_450 chars, over the 24_000 budget.

If either mutation passes, the guard is vacuous: fix the test, amend the commit from Step 5, and
re-run both mutations.

- [ ] **Step 7: Confirm the tree is back to the committed state**

```bash
git status --porcelain src/ormah/engine/memory_engine.py   # must be empty
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest   tests/test_background/test_run_maintenance.py -q > /tmp/t2c.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/t2c.txt
tail -5 /tmp/t2c.txt
```

Expected: no diff against the commit, and `PYTEST_EXIT=0`. This is what proves the mutations were
fully reverted before moving on.


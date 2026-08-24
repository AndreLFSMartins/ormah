### Task 4: run_consolidation splits, and the cap counts sub-clusters

**Files:**
- Modify: `src/ormah/background/consolidator.py:182-204` (`run_consolidation`)
- Test: `tests/test_background/test_consolidator.py`

**Interfaces:**
- Consumes: `Settings.consolidation_max_prompt_chars` (Task 2); `_prompt_overhead_chars()` and
  `_split_cluster_to_fit(cluster, budget_chars)` (Task 3).
- Produces: `run_consolidation(engine)` keeps its `-> None` signature. Nothing downstream reads a
  return value, so none is introduced.

**Context you need.** `run_consolidation` is decorated with `@serialized_memory_job` and called by
the background scheduler. Upstream it returns `None` and reports through a single INFO line;
**keep it that way** — inventing a stats dict is an API change #192 does not need.

Two behavior changes land here:

1. Each discovered cluster passes through the split before reaching the LLM. Sub-clusters shorter
   than `consolidation_min_cluster_size` are dropped: there is nothing to consolidate in a group
   of one, and its node simply stays `working`.
2. `consolidation_max_clusters_per_run` now truncates the **post-split queue**. Discovery is
   unchanged — `_find_consolidation_clusters` still receives the same `limit`, which the existing
   `test_run_consolidation_uses_settings_cap` asserts — so the cap stays a ceiling on LLM calls,
   never a floor on clusters. Without this, splitting could turn 10 clusters into ~25 calls in a
   daily job: a silent 2.5x cost increase on a paid provider. Excess sub-clusters are simply not
   processed and come back next run.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_consolidator.py`:

```python
class TestRunConsolidationSplits:
    """#192: run_consolidation splits oversized clusters and caps LLM calls, not discovery."""

    @staticmethod
    def _fat(nid: str, chars: int) -> dict:
        return {"id": nid, "title": "t", "content": "x" * chars, "space": None}

    def test_oversized_cluster_becomes_two_consolidations(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        cluster = [self._fat(x, 1_500) for x in ("a", "b", "c", "d")]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"], ["c", "d"]]

    def test_oversized_node_is_never_sent_to_the_llm(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        cluster = [self._fat("a", 800), self._fat("huge", 20_000), self._fat("b", 800)]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"]]

    def test_short_subcluster_is_dropped(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        # a+b fill the budget; c lands alone in its sub-cluster with nothing to merge with
        cluster = [self._fat("a", 1_700), self._fat("b", 1_700), self._fat("c", 1_700)]
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
        )
        seen = []
        monkeypatch.setattr(
            consolidator, "_consolidate_cluster", lambda eng, sub: seen.append(sub)
        )

        consolidator.run_consolidation(engine)

        assert [[n["id"] for n in sub] for sub in seen] == [["a", "b"]]

    def test_cap_counts_subclusters_not_raw_clusters(self, monkeypatch, engine):
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_max_prompt_chars = 6_000
        engine.settings.consolidation_max_clusters_per_run = 2
        clusters = [
            [self._fat(f"c{i}n{j}", 1_500) for j in range(4)] for i in range(3)
        ]  # 3 raw clusters -> 6 sub-clusters of 2
        monkeypatch.setattr(
            consolidator, "_find_consolidation_clusters", lambda eng, limit: clusters
        )
        calls = {"n": 0}

        def spy(eng, sub):
            calls["n"] += 1

        monkeypatch.setattr(consolidator, "_consolidate_cluster", spy)

        consolidator.run_consolidation(engine)

        assert calls["n"] == 2, "the cap must bound LLM calls, not discovery"
```

- [ ] **Step 2: Run them and verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -k RunConsolidationSplits -v > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL — `run_consolidation` still passes whole clusters through, so the first assertion
sees one four-node cluster instead of two pairs.

- [ ] **Step 3: Rewrite run_consolidation**

Replace the body of `run_consolidation` in `src/ormah/background/consolidator.py` with:

```python
@serialized_memory_job
def run_consolidation(engine) -> None:
    """Find clusters of similar working memories and consolidate via LLM."""
    settings = engine.settings
    if not settings.llm_enabled:
        return

    clusters = _find_consolidation_clusters(
        engine, limit=settings.consolidation_max_clusters_per_run
    )
    if not clusters:
        return

    # A cluster whose sources do not fit the prompt is SPLIT, never truncated (#192).
    budget = settings.consolidation_max_prompt_chars - _prompt_overhead_chars()
    min_size = settings.consolidation_min_cluster_size
    queue: list[list[dict]] = []
    dropped_nodes = 0

    for cluster in clusters:
        parts = _split_cluster_to_fit(cluster, budget)
        kept = [p for p in parts if len(p) >= min_size]
        dropped_nodes += len(cluster) - sum(len(p) for p in kept)
        queue.extend(kept)

    # The cap bounds LLM CALLS, not discovery. Splitting can multiply one cluster into several,
    # and a daily job silently costing 2.5x more is not what this setting promises. The excess is
    # simply not processed, so it is rediscovered next run.
    capped = queue[: settings.consolidation_max_clusters_per_run]
    if len(queue) > len(capped):
        logger.info(
            "consolidation queue held %d sub-cluster(s) over the per-run cap; deferring to the "
            "next run", len(queue) - len(capped),
        )
    if dropped_nodes:
        logger.info(
            "%d source(s) left working: too large for the prompt budget, or alone in a "
            "sub-cluster after the split", dropped_nodes,
        )

    consolidated_count = 0
    for sub in capped:
        try:
            _consolidate_cluster(engine, sub)
            consolidated_count += 1
        except Exception as e:
            logger.warning("Failed to consolidate cluster: %s", e)

    if consolidated_count:
        logger.info(
            "Consolidated %d sub-cluster(s) from %d cluster(s)", consolidated_count, len(clusters)
        )
```

- [ ] **Step 4: Run the new tests and verify they pass**

Same command as Step 2. Expected: 4 passed, `PYTEST_EXIT=0`.

- [ ] **Step 5: Add the end-to-end test that real nodes actually move**

Every test above mocks `_consolidate_cluster`, so none of them prove the split produces real
consolidations. Add two that mock only the LLM:

```python
def test_split_produces_two_real_consolidations_and_demotes_every_source(
    monkeypatch, consolidation_engine
):
    """#192 end-to-end: an oversized cluster yields TWO consolidated nodes, and all four
    sources end up archival — none is left half-processed."""
    engine, ids = consolidation_engine
    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_max_prompt_chars = 6_000
    cluster = [
        {"id": nid, "title": f"src {i}", "content": "x" * 1_500, "space": "testproject"}
        for i, nid in enumerate(ids)
    ]
    monkeypatch.setattr(
        consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
    )
    monkeypatch.setattr(
        "ormah.background.llm_client.llm_generate",
        lambda settings, prompt, json_mode=True, **kw: json.dumps(
            {"title": "merged", "summary": "merged body", "type": "fact"}
        ),
    )

    consolidator.run_consolidation(engine)

    tiers = {
        nid: engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id = ?", (nid,)
        ).fetchone()["tier"]
        for nid in ids
    }
    assert set(tiers.values()) == {"archival"}, tiers
    created = engine.db.conn.execute(
        "SELECT COUNT(DISTINCT source_id) AS n FROM edges WHERE edge_type = 'derived_from'"
    ).fetchone()["n"]
    assert created == 2, "each sub-cluster must produce its own consolidated node"


def test_oversized_source_is_left_working_end_to_end(monkeypatch, consolidation_engine):
    """The node the split refuses to pack must not be demoted or linked."""
    engine, ids = consolidation_engine
    engine.settings.llm_provider = "ollama"
    engine.settings.consolidation_max_prompt_chars = 6_000
    huge, a, b = ids[0], ids[1], ids[2]
    cluster = [
        {"id": huge, "title": "huge", "content": "x" * 20_000, "space": "testproject"},
        {"id": a, "title": "a", "content": "y" * 800, "space": "testproject"},
        {"id": b, "title": "b", "content": "z" * 800, "space": "testproject"},
    ]
    monkeypatch.setattr(
        consolidator, "_find_consolidation_clusters", lambda eng, limit: [cluster]
    )
    monkeypatch.setattr(
        "ormah.background.llm_client.llm_generate",
        lambda settings, prompt, json_mode=True, **kw: json.dumps(
            {"title": "merged", "summary": "merged body", "type": "fact"}
        ),
    )

    consolidator.run_consolidation(engine)

    tier = engine.db.conn.execute(
        "SELECT tier FROM nodes WHERE id = ?", (huge,)
    ).fetchone()["tier"]
    assert tier == "working"
    inbound = engine.db.conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE edge_type = 'derived_from' AND target_id = ?",
        (huge,),
    ).fetchone()["n"]
    assert inbound == 0
```

Run them:

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -k "end_to_end or two_real_consolidations" -v \
  > out.txt 2>&1; echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: 2 passed.

- [ ] **Step 6: Confirm the existing cap test still holds**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; tail -20 out.txt
```

Expected: `PYTEST_EXIT=0`, including `test_run_consolidation_uses_settings_cap` — discovery must
still receive `limit=consolidation_max_clusters_per_run`.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/consolidator.py tests/test_background/test_consolidator.py
git commit -m "feat(consolidator): split oversized clusters instead of truncating (#192)

run_consolidation now packs each discovered cluster into sub-clusters that fit
the prompt budget. A source too large for the whole budget is left working
rather than summarized from a partial view, and sub-clusters below
min_cluster_size are dropped.

consolidation_max_clusters_per_run now truncates the post-split queue, so it
stays a ceiling on LLM calls: discovery is unchanged and the excess is
rediscovered next run."
```

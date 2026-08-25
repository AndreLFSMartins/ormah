> Plan overview: [00-overview.md](00-overview.md)

### Task 2: Red tests — discovery re-clusters consolidated nodes

**Files:**
- Modify: `tests/test_background/test_consolidator.py` (append after `test_inverted_cluster_bounds_returns_empty_and_warns`, line 173)

**Interfaces:**
- Consumes: `_find_consolidation_clusters(engine, limit=4) -> list[list[dict]]` (each dict has `id`); `run_consolidation(engine)`; `CreateNodeRequest(content, type, title, space, tags)`; `engine.remember(req) -> (id, str)`.
- Produces: helper `_remember(engine, content, title, tags=None) -> str` used by both tests.

- [ ] **Step 1: Append the helper and the two failing tests**

```python
def _remember(engine, content: str, title: str, tags: list[str] | None = None) -> str:
    req = CreateNodeRequest(
        content=content, type=NodeType.fact, title=title, space="testproject", tags=tags or []
    )
    nid, _ = engine.remember(req)
    return nid


_SAME_TEXT = "Python uses indentation to define code blocks"


def test_consolidated_nodes_are_never_seed_nor_member(engine):
    """A summary is terminal: discovery must not pick it as seed or member (#261)."""
    from ormah.background.consolidator import _find_consolidation_clusters

    raw = [_remember(engine, _SAME_TEXT, f"Raw {i}") for i in range(2)]
    summaries = [
        _remember(engine, _SAME_TEXT, f"Summary {i}", tags=["consolidated"]) for i in range(2)
    ]
    # Fixture check: the tag reached the index, otherwise the test proves nothing.
    tagged = {
        r[0]
        for r in engine.db.conn.execute(
            "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
        ).fetchall()
    }
    assert set(summaries) <= tagged

    clusters = _find_consolidation_clusters(engine)
    ids_in_clusters = {n["id"] for cluster in clusters for n in cluster}

    assert ids_in_clusters.isdisjoint(summaries), "a consolidated node entered a cluster"
    assert set(raw) <= ids_in_clusters, "the raw pair should still cluster"


def test_two_summaries_are_not_summarised_again(monkeypatch, engine):
    """Issue #261's scenario: run 1 yields N1 and N2, run 2 must leave them alone."""
    from ormah.background import consolidator

    engine.settings.llm_provider = "ollama"  # default is "none", which skips the job
    engine.settings.consolidation_max_cluster_nodes = 2  # four sources -> two clusters
    for i in range(4):
        _remember(engine, _SAME_TEXT, f"Source {i}")

    prompts: list[str] = []

    def fake_llm(settings, prompt, json_mode=True, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {"title": "Python indentation rules", "summary": "Blocks by indentation.", "type": "fact"}
        )

    monkeypatch.setattr("ormah.background.llm_client.llm_generate", fake_llm)

    def consolidated_ids() -> list[str]:
        rows = engine.db.conn.execute(
            "SELECT node_id FROM node_tags WHERE tag = 'consolidated'"
        ).fetchall()
        return sorted(r[0] for r in rows)

    consolidator.run_consolidation(engine)
    first = consolidated_ids()
    assert len(first) == 2 and len(prompts) == 2

    consolidator.run_consolidation(engine)

    assert consolidated_ids() == first, "run 2 created a summary of summaries"
    assert len(prompts) == 2, "run 2 asked the LLM again"
    tiers = {
        r[0]
        for r in engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id IN (?, ?)", first
        ).fetchall()
    }
    assert tiers == {"working"}
```

Worked example, test 2 without the fix: run 1 → seed `Source 0` pulls `Source 1` (cap 2), seed `Source 2` pulls `Source 3` → N1, N2, both `working`, identical content. Run 2 → the only `working` nodes are N1 and N2, similarity 1.0 ≥ 0.6 → third LLM call, N3 created, N1/N2 demoted → `consolidated_ids()` has 3 entries and `prompts` has 3. With the fix run 2 selects nothing.

- [ ] **Step 2: Run both — they must fail on the bug, not on setup**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_background/test_consolidator.py -q -k "never_seed_nor_member or not_summarised_again" > /tmp/t2.txt 2>&1; echo "PYTEST_EXIT=$?" >> /tmp/t2.txt; cat /tmp/t2.txt
```
Expected: 2 failed, `PYTEST_EXIT=1`. Test 1 fails at `isdisjoint` ("a consolidated node entered a cluster"); test 2 fails at `consolidated_ids() == first`. If test 1 fails at `set(summaries) <= tagged` instead, the tag never reached `node_tags` — stop and report; the spec's fallback (read tags from markdown) applies. If test 2 fails at `len(first) == 2`, clustering did not happen — stop and report the actual `first`/`prompts`.

- [ ] **Step 3: Commit the red tests**

```bash
git add tests/test_background/test_consolidator.py
git commit -m "test(consolidator): red tests for consolidated nodes re-clustering (#261)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

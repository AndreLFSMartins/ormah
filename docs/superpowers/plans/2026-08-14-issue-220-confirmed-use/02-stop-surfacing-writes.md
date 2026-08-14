# Task 2: Surfacing stops writing lifecycle fields

**Files:**
- Create: `tests/test_engine/test_confirmed_use.py`
- Modify: `tests/test_engine/test_scoring_signals.py:365-460` (invert two existing tests)
- Modify: `tests/test_api/test_routes.py` (append one test)
- Modify: `src/ormah/engine/memory_engine.py:816-821` (signature), `:826-828` (docstring), `:909-913`, `:945-949`, `:1027-1029`, `:1073-1075`
- Modify: `src/ormah/engine/context_builder.py:525`, `:898`

**Interfaces:**
- Consumes: the worktree and baseline from Task 1.
- Produces: `recall_search_structured` without its `touch_access` parameter — signature becomes `(self, query, limit=10, default_space=None, min_relevance=None, auto_temporal=True, spread_activation=True, query_vec=None, **filters)`. Tasks 3–5 rely on this signature.

Two tests in `test_scoring_signals.py` currently assert the **opposite** of the new contract: `test_touch_access_skips_activated_nodes` ends with `assert node_a_after.access_count == initial_a + 1` for direct matches. They must be inverted, not deleted — the activated/conflict half of what they prove still matters.

- [ ] **Step 1: Write the failing contract tests**

Create `tests/test_engine/test_confirmed_use.py`:

```python
"""Contract tests for #220 — surfacing never writes lifecycle fields.

Confirmed use is the only lifecycle mutator. These tests assert the negative
half of the contract: appearing in a result set changes nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ormah.models.node import CreateNodeRequest

LIFECYCLE_FIELDS = ("access_count", "last_accessed", "last_review", "stability")


def _create(engine, title: str, content: str) -> str:
    node_id, _ = engine.remember(CreateNodeRequest(
        content=content, title=title, type="fact", tier="working",
    ))
    return node_id


def _snapshot(engine, node_ids: list[str]) -> dict:
    """Capture the four lifecycle fields per node, read from the markdown store."""
    return {
        node_id: {
            field: getattr(engine.file_store.load(node_id), field)
            for field in LIFECYCLE_FIELDS
        }
        for node_id in node_ids
    }


class TestSurfacingDoesNotMutate:
    """A memory appearing in a result set is not evidence it was used."""

    def test_hybrid_recall_leaves_lifecycle_untouched(self, engine):
        id_a = _create(engine, "Alpha", "Alpha direct match node about widgets")
        id_b = _create(engine, "Beta", "Beta direct match node about widgets")
        before = _snapshot(engine, [id_a, id_b])

        search_obj = engine._get_hybrid_search()
        if search_obj is None:
            pytest.skip("hybrid search unavailable; FTS fallback is covered separately")

        def mock_search(query, limit=10, **filters):
            return [
                {"node": engine.graph.get_node(id_a), "score": 1.0, "source": "hybrid"},
                {"node": engine.graph.get_node(id_b), "score": 0.8, "source": "hybrid"},
            ]

        with patch.object(search_obj, "search", side_effect=mock_search):
            engine.recall_search("widgets", limit=10)

        assert _snapshot(engine, [id_a, id_b]) == before

    def test_fts_fallback_leaves_lifecycle_untouched(self, engine):
        id_a = _create(engine, "Alpha", "Alpha direct match node about widgets")
        id_b = _create(engine, "Beta", "Beta direct match node about widgets")
        before = _snapshot(engine, [id_a, id_b])

        engine.graph.fts_search = MagicMock(return_value=[
            {"id": id_a, "score": 5.0},
            {"id": id_b, "score": 4.0},
        ])
        with patch.object(engine, "_get_hybrid_search", return_value=None):
            engine.recall_search("widgets", limit=10)

        assert _snapshot(engine, [id_a, id_b]) == before

    def test_structured_recall_leaves_lifecycle_untouched(self, engine):
        """The structured path had a touch_access flag; the default used to mutate."""
        id_a = _create(engine, "Alpha", "Alpha direct match node about widgets")
        before = _snapshot(engine, [id_a])

        engine.graph.fts_search = MagicMock(return_value=[{"id": id_a, "score": 5.0}])
        with patch.object(engine, "_get_hybrid_search", return_value=None):
            engine.recall_search_structured("widgets", limit=10)

        assert _snapshot(engine, [id_a]) == before

    def test_touch_access_is_not_a_parameter(self, engine):
        """The opt-out flag is gone — surfacing never mutates, for any caller."""
        import inspect

        params = inspect.signature(engine.recall_search_structured).parameters
        assert "touch_access" not in params

    def test_whisper_context_leaves_lifecycle_untouched(self, engine):
        """Whisper already passed touch_access=False; it must stay clean without it."""
        from ormah.engine.context_builder import ContextBuilder

        id_a = _create(engine, "Alpha", "Alpha whisperable node about widgets")
        before = _snapshot(engine, [id_a])

        builder = ContextBuilder(engine.graph, engine=engine)
        builder.build_whisper_context(prompt="widgets", min_score=0.0)

        assert _snapshot(engine, [id_a]) == before

- [ ] **Step 2: Invert the two stale tests in `test_scoring_signals.py`**

In `tests/test_engine/test_scoring_signals.py`, the class docstring and both tests assert the pre-#220 behaviour. Replace the class docstring:

```python
class TestSpreadingActivationAccessIsolation:
    """Neither direct matches nor activated/conflict neighbours get lifecycle
    writes from a search (#220). Before #220 direct matches were incremented;
    that was the bug."""
```

In `test_touch_access_skips_activated_nodes`, replace the final assertion block:

```python
        # Verify: after #220, NO node touched by a search changes — not the
        # direct matches, not the activated neighbour.
        assert engine.file_store.load(id_a).access_count == initial_a
        assert engine.file_store.load(id_c).access_count == initial_c
        assert engine.file_store.load(id_b).access_count == initial_b
```

Apply the same inversion to `test_touch_access_skips_conflict_nodes`: every `== initial_X + 1` becomes `== initial_X`.

- [ ] **Step 3: Add the UI search route test**

Append to `tests/test_api/test_routes.py` (the `client` fixture already builds an app with `ui_router`; the engine is reachable at `client.app.state.engine`, and the route is `GET /ui/search`):

```python
def test_ui_search_does_not_touch_lifecycle(client):
    """#220 — UI search is surfacing, not use."""
    from ormah.models.node import CreateNodeRequest

    engine = client.app.state.engine
    node_id, _ = engine.remember(CreateNodeRequest(
        content="Searchable content about widgets.",
        title="Widgets",
        type="fact",
        tier="working",
    ))
    fields = ("access_count", "last_accessed", "last_review", "stability")
    before = {f: getattr(engine.file_store.load(node_id), f) for f in fields}

    resp = client.get("/ui/search", params={"q": "widgets"})
    assert resp.status_code == 200

    after = {f: getattr(engine.file_store.load(node_id), f) for f in fields}
    assert after == before
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use.py \
                   tests/test_engine/test_scoring_signals.py::TestSpreadingActivationAccessIsolation \
                   tests/test_api/test_routes.py::test_ui_search_does_not_touch_lifecycle -v )
```

Expected failures — these four assert the new contract and must be red now:
`test_hybrid_recall_leaves_lifecycle_untouched`, `test_fts_fallback_leaves_lifecycle_untouched`,
`test_structured_recall_leaves_lifecycle_untouched`, `test_touch_access_is_not_a_parameter`,
plus `test_ui_search_does_not_touch_lifecycle` and the two inverted tests in
`test_scoring_signals.py`. The failure message should show `access_count` one higher than asserted.

Expected to **pass already**: `test_whisper_context_leaves_lifecycle_untouched`. Whisper has
always passed `touch_access=False`, so it is a regression guard, not a fix. If it fails here,
whisper *is* mutating today and the spec's premise is wrong — investigate before continuing.

If any of the four contract tests passes at this step, stop: the surfacing path is not mutating
what the spec says it does, and the rest of this task is built on a false premise.

- [ ] **Step 5: Remove the lifecycle writes from the four search call sites**

In `src/ormah/engine/memory_engine.py`, delete each of the four loops.

At `:907-913` (`recall_search_structured`, hybrid path) replace:

```python
            if spread_activation:
                results = self._spread_activation(results, limit)
            if touch_access:
                for r in results:
                    if r.get("source") not in ("activated", "conflict"):
                        self._touch_access(r["node"]["id"])
            return results
```

with:

```python
            if spread_activation:
                results = self._spread_activation(results, limit)
            return results
```

At `:943-950` (`recall_search_structured`, FTS fallback) replace:

```python
        if spread_activation:
            enriched = self._spread_activation(enriched, limit)
        if touch_access:
            for r in enriched:
                if r.get("source") not in ("activated", "conflict"):
                    self._touch_access(r["node"]["id"])

        return enriched
```

with:

```python
        if spread_activation:
            enriched = self._spread_activation(enriched, limit)

        return enriched
```

At `:1026-1030` (`recall_search`, hybrid path) replace:

```python
            results = self._spread_activation(results, limit)
            for r in results:
                if r.get("source") not in ("activated", "conflict"):
                    self._touch_access(r["node"]["id"])
            whisper_log_ids = self._log_feedback_candidates(
```

with:

```python
            results = self._spread_activation(results, limit)
            whisper_log_ids = self._log_feedback_candidates(
```

At `:1072-1076` (`recall_search`, FTS fallback) replace:

```python
        enriched = self._spread_activation(enriched, limit)
        for r in enriched:
            if r.get("source") not in ("activated", "conflict"):
                self._touch_access(r["node"]["id"])
        whisper_log_ids = self._log_feedback_candidates(
```

with:

```python
        enriched = self._spread_activation(enriched, limit)
        whisper_log_ids = self._log_feedback_candidates(
```

- [ ] **Step 6: Remove the `touch_access` parameter and its docstring paragraph**

At `src/ormah/engine/memory_engine.py:816-821`, replace:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        touch_access: bool = True, min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

with:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

In the same docstring, delete these two lines and the blank line that follows them:

```python
        When *touch_access* is False, access_count and last_accessed are not
        updated — useful for context loading that shouldn't inflate access stats.
```

- [ ] **Step 7: Remove the two `touch_access=False` arguments in `context_builder.py`**

At `src/ormah/engine/context_builder.py:525`, delete the line `"touch_access": False,` from the `search_kwargs` dict literal.

At `src/ormah/engine/context_builder.py:898`, delete the line `touch_access=False,` from the `recall_search_structured(...)` call.

Both were correct before and are now redundant: surfacing never mutates regardless of caller.

- [ ] **Step 8: Confirm no caller and no reference survives**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "touch_access" src/ tests/ docs/ | grep -v "FileStore\|file_store\|def touch_access" )
```

Expected: only hits in `docs/04 - Whisper - Involuntary Recall.md` (fixed in Task 6) and, if you kept it, the `test_touch_access_is_not_a_parameter` guard test. `src/ormah/store/file_store.py:202` (`FileStore.touch_access`) is unrelated dead code and stays.

- [ ] **Step 9: Run the tests to verify they pass**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use.py \
                   tests/test_engine/test_scoring_signals.py \
                   tests/test_api/test_routes.py -v )
```

Expected: all PASS, except any test ID already present in `/tmp/220-baseline-ids.txt`.

- [ ] **Step 10: Run the full suite and diff against the baseline**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/220-after-task2.txt )
diff /tmp/220-baseline-ids.txt /tmp/220-after-task2.txt
```

Expected: `diff` prints nothing, or prints only lines removed (`<`). Any line added (`>`) is a regression this task introduced — fix it before committing.

- [ ] **Step 11: Lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && ruff check src/ tests/ )
```

Expected: `All checks passed!`

- [ ] **Step 12: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add src/ormah/engine/memory_engine.py src/ormah/engine/context_builder.py \
          tests/test_engine/test_confirmed_use.py tests/test_engine/test_scoring_signals.py \
          tests/test_api/test_routes.py && \
  git commit -m "fix(lifecycle): surfaced results no longer count as memory use

Broad recall, the FTS fallback, structured recall and UI search all called
_touch_access once per returned node, so appearing in a list was indistinguishable
from being read. Remove the four loops and the touch_access parameter that only
existed to opt out of them.

Contract tests assert the four lifecycle fields are unchanged across every
surfacing path. Two tests in test_scoring_signals asserted the old behaviour for
direct matches and are inverted.

Refs #220" )
```

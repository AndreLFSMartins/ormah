# Task 1: Search stops writing lifecycle fields

**Files:**
- Create: `tests/test_engine/test_confirmed_use_contract.py`
- Modify: `src/ormah/engine/memory_engine.py` (four call sites, one signature, one rename)
- Modify: `src/ormah/engine/context_builder.py` (two `touch_access` references)
- Modify: `eval/recall/runner.py` (one `touch_access` kwarg)
- Modify: `docs/04 - Whisper - Involuntary Recall.md` (one stale reference)
- Modify: `tests/test_engine/test_memory_engine.py`, `tests/test_background/test_importance_scorer.py`, `tests/test_engine/test_scoring_signals.py`, `tests/test_engine/test_mutation_stamping.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MemoryEngine._record_confirmed_use(self, node_id: str) -> None` — the single lifecycle mutator, renamed from `_touch_access`, body unchanged. Task 2 calls this and nothing else.
- Produces: `MemoryEngine.recall_search_structured(self, query, limit=10, default_space=None, min_relevance=None, auto_temporal=True, spread_activation=True, query_vec=None, **filters) -> list[dict]` — note the removed `touch_access` parameter.

All line numbers are from `upstream/main` (`a28837b`) and shift as you edit. Locate code by the quoted snippet.

---

- [ ] **Step 1: Write the contract test file with the non-mutation cases**

Create `tests/test_engine/test_confirmed_use_contract.py`:

```python
"""Contract tests for issue #220: surfacing must not be confirmed use.

Every assertion reads the four lifecycle fields from BOTH the markdown file and
the SQLite row. A test that checked only the database would pass while the file
rotted, and vice versa.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_ui import router as ui_router
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.models.node import CreateNodeRequest

LIFECYCLE_FIELDS = ("access_count", "last_accessed", "stability", "last_review")


def _snapshot(engine, node_id):
    """Capture the four lifecycle fields from the markdown file and the DB row."""
    node = engine.file_store.load(node_id)
    row = engine.db.conn.execute(
        "SELECT access_count, last_accessed, stability, last_review FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    return {
        "file": tuple(getattr(node, f) for f in LIFECYCLE_FIELDS),
        "db": tuple(row[f] for f in LIFECYCLE_FIELDS),
    }


def _make_nodes(engine, count=2):
    """Create *count* nodes that a search for 'caching' will match."""
    ids = []
    for i in range(count):
        node_id, _ = engine.remember(CreateNodeRequest(
            content=f"caching architecture note number {i}",
            title=f"Caching {i}",
            type="fact",
            tier="working",
        ))
        ids.append(node_id)
    return ids


@pytest.fixture
def fts_only(engine):
    """Force the FTS fallback path by removing hybrid search."""
    with patch.object(engine, "_get_hybrid_search", return_value=None):
        yield engine


# --- Non-mutation contracts (issue #220 acceptance criteria) ---------------

def test_recall_search_does_not_write_lifecycle(engine):
    """Contract 1: broad formatted recall over N nodes mutates nothing."""
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id], (
            f"recall_search mutated lifecycle fields on {node_id}"
        )


def test_recall_search_fts_fallback_does_not_write_lifecycle(fts_only):
    """Contract 2: the FTS fallback path mutates nothing either."""
    engine = fts_only
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_recall_search_structured_does_not_write_lifecycle(engine):
    """Contract 3: called with no lifecycle kwarg — the default was the bug."""
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search_structured("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_recall_search_structured_fts_fallback_does_not_write_lifecycle(fts_only):
    """Contract 4: same for the FTS fallback."""
    engine = fts_only
    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    engine.recall_search_structured("caching architecture", limit=10)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]


def test_ui_search_route_does_not_write_lifecycle(tmp_memory_dir):
    """Contract 5: the UI search route.

    This is the test that fails on clean upstream/main: routes_ui.search_nodes
    calls recall_search_structured without the kwarg, so the True default
    reinforced every result. Exercised through the route, not the engine.
    """
    settings = Settings(memory_dir=tmp_memory_dir, backup_dir=tmp_memory_dir.parent / "backups")
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        ids = _make_nodes(engine)
        before = {i: _snapshot(engine, i) for i in ids}

        app = FastAPI()
        app.include_router(ui_router)
        app.state.engine = engine
        with TestClient(app) as client:
            resp = client.get("/ui/search", params={"q": "caching architecture"})
        assert resp.status_code == 200

        for node_id in ids:
            assert _snapshot(engine, node_id) == before[node_id], (
                f"UI search mutated lifecycle fields on {node_id}"
            )
    finally:
        engine.shutdown()


def test_whisper_does_not_write_lifecycle(engine):
    """Contract 6: whisper still mutates nothing after losing its flag.

    Whisper was already correct (it passed touch_access=False). This pins that
    it stays correct once the flag is gone.
    """
    from ormah.engine.context_builder import ContextBuilder

    ids = _make_nodes(engine)
    before = {i: _snapshot(engine, i) for i in ids}

    builder = ContextBuilder(engine.graph, engine=engine)
    builder.build_whisper_context("caching architecture", space=None, max_nodes=8)

    for node_id in ids:
        assert _snapshot(engine, node_id) == before[node_id]
```

The route path is verified: `routes_ui.py:7` declares `APIRouter(prefix="/ui", tags=["ui"])`, so `/ui/search` is correct as written.

- [ ] **Step 2: Run the new tests to see which fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected on clean `upstream/main`: contracts 1, 2, 3, 4 and 5 **FAIL** (lifecycle fields changed); contract 6 **PASSES** (whisper already passed `touch_access=False`). Record which failed — that is the defect, reproduced.

- [ ] **Step 3: Delete the four surfacing call sites**

In `src/ormah/engine/memory_engine.py`, `recall_search_structured`, hybrid path (`:772-775`) — delete these four lines entirely:

```python
            if touch_access:
                for r in results:
                    if r.get("source") not in ("activated", "conflict"):
                        self._touch_access(r["node"]["id"])
```

Same method, FTS fallback (`:808-811`) — delete:

```python
        if touch_access:
            for r in enriched:
                if r.get("source") not in ("activated", "conflict"):
                    self._touch_access(r["node"]["id"])
```

In `recall_search`, hybrid path (`:890-892`) — delete:

```python
            for r in results:
                if r.get("source") not in ("activated", "conflict"):
                    self._touch_access(r["node"]["id"])
```

Same method, FTS fallback (`:936-938`) — delete:

```python
        for r in enriched:
            if r.get("source") not in ("activated", "conflict"):
                self._touch_access(r["node"]["id"])
```

Leave every surrounding line alone — in particular the `_log_feedback_candidates` calls that follow two of these blocks. Observability is not part of this change.

- [ ] **Step 4: Remove the `touch_access` parameter**

In the same file, `recall_search_structured` signature (`:679-684`), change:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        touch_access: bool = True, min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

to:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

Then delete this docstring paragraph (`:689-691`):

```python
        When *touch_access* is False, access_count and last_accessed are not
        updated — useful for context loading that shouldn't inflate access stats.

```

- [ ] **Step 5: Rename the mutator**

Rename `_touch_access` to `_record_confirmed_use` at its definition (`:1936`) and at its one remaining caller in `recall_node` (`:646`). The body does not change — not one character.

```python
    def _record_confirmed_use(self, node_id: str) -> None:
        """Record a confirmed use: update access stats and FSRS stability on disk and DB."""
```

At `:645-646`, the comment goes with the name:

```python
        # Record confirmed use: this is a deliberate single-node fetch
        self._record_confirmed_use(resolved_node_id)
```

Verify nothing was missed:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && grep -rn "_touch_access" src/ )
```

Expected: no output. `src/ormah/background/forgetting_manager.py:54` mentions `_touch_access` in a comment — update that comment to the new name; it is documentation, not a call.

- [ ] **Step 6: Clean the consumers that passed the flag**

`src/ormah/engine/context_builder.py:523` — delete the dict key. This one is load-bearing: the dict is splatted as `**search_kwargs` at `:572`, so leaving it turns every whisper into a `TypeError`.

```python
            "tiers": ["core", "working"],
            "touch_access": False,      # <- delete this line
```

`src/ormah/engine/context_builder.py:896` — delete the kwarg:

```python
                    tiers=["core", "working"],
                    touch_access=False,      # <- delete this line
```

`eval/recall/runner.py:74` — delete the kwarg:

```python
                tiers=["core", "working"],
                touch_access=False,      # <- delete this line
```

- [ ] **Step 7: Run the contract tests — they must all pass now**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/test_engine/test_confirmed_use_contract.py -v )
```

Expected: 6 passed.

- [ ] **Step 8: Update the six existing test call sites that pass the kwarg**

Delete `touch_access=False,` from each — the behaviour is now the only behaviour:

- `tests/test_background/test_importance_scorer.py:304`
- `tests/test_engine/test_memory_engine.py:546, 569, 584, 597, 619`

- [ ] **Step 9: Replace the obsolete isolation tests**

`tests/test_engine/test_scoring_signals.py:366-495` holds `TestSpreadingActivationAccessIsolation`, whose two tests assert that `_touch_access` **is** called for direct matches and skipped for `activated`/`conflict` nodes. Search now calls nothing at all, so the premise is gone. Replace the whole class — do not delete it silently — with:

```python
class TestSearchDoesNotTouchLifecycle:
    """Issue #220: search writes no lifecycle fields, for any result source.

    This class replaces TestSpreadingActivationAccessIsolation, which asserted
    that direct matches WERE touched while activated/conflict nodes were not.
    Direct matches are no longer touched either, so the distinction is gone.
    """

    def test_direct_matches_and_activated_nodes_are_both_untouched(self, engine):
        from ormah.models.node import CreateNodeRequest

        id_a, _ = engine.remember(CreateNodeRequest(
            content="Alpha direct match node", title="Alpha", type="fact", tier="working",
        ))
        id_b, _ = engine.remember(CreateNodeRequest(
            content="Beta neighbor node", title="Beta", type="fact", tier="working",
        ))

        initial_a = engine.file_store.load(id_a).access_count
        initial_b = engine.file_store.load(id_b).access_count

        def mock_spread(results, limit):
            out = list(results)
            out.append({
                "node": engine.graph.get_node(id_b),
                "score": 0.5,
                "source": "activated",
                "activated_by": id_a,
                "activation_edge": "related_to",
            })
            return out

        def mock_search(query, limit=10, **filters):
            return [{"node": engine.graph.get_node(id_a), "score": 1.0, "source": "hybrid"}]

        search_obj = engine._get_hybrid_search()
        if search_obj is not None:
            with patch.object(search_obj, "search", side_effect=mock_search), \
                 patch.object(engine, "_spread_activation", side_effect=mock_spread):
                engine.recall_search_structured("test query", limit=10)
        else:
            engine.graph.fts_search = MagicMock(return_value=[{"id": id_a, "score": 5.0}])
            with patch.object(engine, "_spread_activation", side_effect=mock_spread):
                engine.recall_search_structured("test query", limit=10)

        assert engine.file_store.load(id_a).access_count == initial_a, (
            "the direct match was touched — search must not confirm use"
        )
        assert engine.file_store.load(id_b).access_count == initial_b
```

- [ ] **Step 10: Follow the rename in the stamping test**

`tests/test_engine/test_mutation_stamping.py:146` — `engine._touch_access(node_id)` becomes `engine._record_confirmed_use(node_id)`. Rename the enclosing test function to match if its name mentions `touch_access`.

**Do not touch** `tests/test_engine/test_mutation_stamping.py:95-102` or `tests/test_store/test_file_store.py:121-130` — those exercise `FileStore.touch_access`, the namesake, which is out of scope.

- [ ] **Step 11: Correct the stale doc reference**

`docs/04 - Whisper - Involuntary Recall.md:101` refers to `touch_access = False` as whisper's mechanism for not inflating access stats. The parameter no longer exists; search never writes lifecycle fields. Rewrite that line to say so, keeping the surrounding prose intact.

- [ ] **Step 12: Full suite against the baseline, then lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort ) \
  > /private/tmp/claude-501/220-task1.txt
diff /private/tmp/claude-501/220-baseline-ids.txt /private/tmp/claude-501/220-task1.txt
```

Expected: **no output from `diff`**. Any line prefixed `>` is a test this task broke — fix it before committing. Then:

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && make lint )
```

- [ ] **Step 13: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add -A && \
  git commit -m "fix(lifecycle): stop treating surfaced results as memory use

Search paths lose their lifecycle writes entirely rather than being guarded by
a flag: recall_search wrote unguarded on both its hybrid and FTS paths, and
recall_search_structured defaulted touch_access=True, so the UI search route —
which never passed the kwarg — reinforced every result it displayed.

_touch_access becomes _record_confirmed_use with an unchanged body, leaving
recall_node as its only caller. Retrieval and whisper event logging are
untouched, so ignored appearances remain observable.

Refs #220" )
```

# Task 1 — Backend: `/ui/graph` active-first + drill + `all_spaces`

**Files:**
- Modify: `src/ormah/api/routes_ui.py:10-21` (`get_graph`)
- Test: `tests/test_api/test_routes_graph.py` (create)

Rodar pytest via `.venv/bin/python -m pytest`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_routes_graph.py`:

```python
"""Tests for /ui/graph active-first gating and space drill-down."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_ui import router as ui_router
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine


@pytest.fixture
def ui_app(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir, backup_dir=tmp_memory_dir.parent / "backups")
    engine = MemoryEngine(settings)
    engine.startup()
    app = FastAPI()
    app.include_router(ui_router)
    app.state.engine = engine
    yield app, engine
    engine.shutdown()


def _insert_node(engine, node_id, *, tier="working", space=None, type_="fact"):
    engine.db.conn.execute(
        """INSERT INTO nodes (id, type, tier, content, title, source, space,
           created, updated, last_accessed, access_count, importance, confidence,
           file_path, file_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
           datetime('now'), 0, 0.5, 1.0, '/fake/path', 'abc123')""",
        (node_id, type_, tier, "c", "t", "test", space),
    )
    engine.db.conn.commit()


def _insert_edge(engine, src, tgt, edge_type="related_to"):
    engine.db.conn.execute(
        "INSERT INTO edges (source_id, target_id, edge_type, weight, created) "
        "VALUES (?, ?, ?, 1.0, datetime('now'))",
        (src, tgt, edge_type),
    )
    engine.db.conn.commit()


def test_default_excludes_archival(ui_app):
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "work1", tier="working", space="work")
    _insert_node(engine, "arch1", tier="archival", space="work")
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert {n["id"] for n in body["nodes"]} == {"core1", "work1"}


def test_default_includes_user_node_even_if_archival(ui_app):
    app, engine = ui_app
    _insert_node(engine, "self", tier="archival", space=None)
    engine.user_node_id = "self"
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert "self" in {n["id"] for n in body["nodes"]}


def test_default_all_spaces_includes_archival_only_space(ui_app):
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="active-space")
    _insert_node(engine, "arch1", tier="archival", space="dead-space")
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert body["all_spaces"] == ["active-space", "dead-space"]
    assert "dead-space" not in {n["space"] for n in body["nodes"]}


def test_default_signals_no_space_group_even_if_archival_only(ui_app):
    # F1: a no-space node exists only in archival → default omits it from nodes,
    # but has_no_space must be True so the "(no space)" chip stays drillable.
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "arch_ns", tier="archival", space=None)
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert body["has_no_space"] is True
    assert "arch_ns" not in {n["id"] for n in body["nodes"]}


def test_default_no_space_false_when_all_nodes_have_space(ui_app):
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert body["has_no_space"] is False


def test_edges_pruned_to_returned_nodes(ui_app):
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "arch1", tier="archival", space="work")
    _insert_edge(engine, "core1", "arch1")
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert body["edges"] == []


def test_space_drill_includes_archival_of_that_space(ui_app):
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "arch1", tier="archival", space="work")
    _insert_node(engine, "other", tier="core", space="personal")
    with TestClient(app) as c:
        body = c.get("/ui/graph?space=work").json()
    assert {n["id"] for n in body["nodes"]} == {"core1", "arch1"}


def test_space_empty_selects_no_space_group(ui_app):
    app, engine = ui_app
    _insert_node(engine, "nospace", tier="core", space=None)
    _insert_node(engine, "spaced", tier="core", space="work")
    with TestClient(app) as c:
        body = c.get("/ui/graph?space=").json()
    assert {n["id"] for n in body["nodes"]} == {"nospace"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api/test_routes_graph.py -v`
Expected: FAIL (default still returns archival; no `all_spaces` key; `?space` ignored).

- [ ] **Step 3: Implement the gating**

Replace `get_graph` in `src/ormah/api/routes_ui.py` (lines 10-21):

```python
@router.get("/graph")
def get_graph(request: Request, space: str | None = None):
    """Graph data for the explorer.

    Default (no ``space``): the *active graph* — non-archival nodes plus the
    self/user node — so the overview never loads the whole archival history.
    ``?space=<S>``: the full set for one space (active + archival) for
    drill-down. ``?space=`` (empty) selects the no-space group.
    """
    engine = request.app.state.engine
    conn = engine.db.conn
    user_node_id = getattr(engine, "user_node_id", None)

    if space is None:
        rows = conn.execute(
            "SELECT * FROM nodes WHERE tier != 'archival' OR id = ?",
            (user_node_id,),
        ).fetchall()
    elif space == "":
        rows = conn.execute(
            "SELECT * FROM nodes WHERE space IS NULL OR space = ''"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM nodes WHERE space = ?", (space,)).fetchall()

    nodes = [dict(r) for r in rows]
    node_ids = {n["id"] for n in nodes}
    # ponytail: load-all-edges then filter in Python. At ~14k edges this is µs and
    # the issue states the backend is not the bottleneck. Upgrade path if edge
    # volume grows: constrain in SQL via a temp table of node_ids (a 1.6k-id IN
    # list would blow SQLite's ~999 bind-param limit).
    edges = [
        e
        for e in engine.graph.get_all_edges()
        if e["source_id"] in node_ids and e["target_id"] in node_ids
    ]
    all_spaces = [
        r["space"]
        for r in conn.execute(
            "SELECT DISTINCT space FROM nodes "
            "WHERE space IS NOT NULL AND space != '' ORDER BY space"
        ).fetchall()
    ]
    # F1 (council): signal the no-space group's existence over ALL nodes so the
    # "(no space)" chip stays drillable even when no active no-space node loaded.
    has_no_space = (
        conn.execute(
            "SELECT 1 FROM nodes WHERE space IS NULL OR space = '' LIMIT 1"
        ).fetchone()
        is not None
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "user_node_id": user_node_id,
        "all_spaces": all_spaces,
        "has_no_space": has_no_space,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api/test_routes_graph.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_api/test_routes_graph.py src/ormah/api/routes_ui.py
git commit -m "feat(ui-api): active-graph-first default + space drill-down for /ui/graph (#22)"
```

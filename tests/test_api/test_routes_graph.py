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
    user_id = engine.user_node_id  # startup creates a core user node
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "work1", tier="working", space="work")
    _insert_node(engine, "arch1", tier="archival", space="work")
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    returned = {n["id"] for n in body["nodes"]} - {user_id}
    assert returned == {"core1", "work1"}
    assert "arch1" not in returned


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
    app, engine = ui_app
    _insert_node(engine, "core1", tier="core", space="work")
    _insert_node(engine, "arch_ns", tier="archival", space=None)
    with TestClient(app) as c:
        body = c.get("/ui/graph").json()
    assert body["has_no_space"] is True
    assert "arch_ns" not in {n["id"] for n in body["nodes"]}


def test_default_no_space_false_when_all_nodes_have_space(ui_app):
    app, engine = ui_app
    # Give the startup user node a space too so no spaceless nodes exist
    engine.db.conn.execute(
        "UPDATE nodes SET space = 'work' WHERE id = ?", (engine.user_node_id,)
    )
    engine.db.conn.commit()
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
    user_id = engine.user_node_id  # startup user node also has space=None
    _insert_node(engine, "nospace", tier="core", space=None)
    _insert_node(engine, "spaced", tier="core", space="work")
    with TestClient(app) as c:
        body = c.get("/ui/graph?space=").json()
    returned = {n["id"] for n in body["nodes"]} - {user_id}
    assert returned == {"nospace"}
    assert "spaced" not in returned

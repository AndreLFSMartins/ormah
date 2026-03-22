"""Tests for engine.submit_feedback and POST /agent/feedback route."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_whisper_log(conn, node_id: str, session_id: str = "sess-abc", space: str = "myspace") -> None:
    conn.execute(
        "INSERT INTO whisper_log "
        "(node_id, score, session_id, space, prompt_text, prompt_vec, prompt_hash, was_injected, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (node_id, 0.48, session_id, space, "how does auth work", b"", "hash-abc", 0),
    )
    conn.commit()


def _insert_review_log(conn, node_id: str, session_id: str = "sess-abc") -> int:
    cursor = conn.execute(
        "INSERT INTO review_log (node_id, session_id, surfaced_at, answered) "
        "VALUES (?, ?, datetime('now'), 0)",
        (node_id, session_id),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# TestSubmitFeedbackBasic
# ---------------------------------------------------------------------------


class TestSubmitFeedbackBasic:

    def test_no_whisper_log_returns_error(self, engine):
        result = engine.submit_feedback("nonexistent-id", 1)
        assert "No whisper_log entry" in result

    def test_explicit_feedback_inserts_affinity(self, engine):
        node_id = "node-explicit-001"
        _insert_whisper_log(engine.db.conn, node_id)
        engine.submit_feedback(node_id, 1, "explicit")

        row = engine.db.conn.execute(
            "SELECT * FROM affinity WHERE node_id = ?", (node_id,)
        ).fetchone()
        assert row is not None
        assert row["signal"] == 1
        assert row["source"] == "explicit"

    def test_implicit_feedback_inserts_affinity(self, engine):
        node_id = "node-implicit-001"
        _insert_whisper_log(engine.db.conn, node_id)
        engine.submit_feedback(node_id, 1, "implicit")

        row = engine.db.conn.execute(
            "SELECT * FROM affinity WHERE node_id = ?", (node_id,)
        ).fetchone()
        assert row is not None
        assert row["source"] == "implicit"

    def test_idempotent_same_session(self, engine):
        node_id = "node-idempotent-001"
        _insert_whisper_log(engine.db.conn, node_id, session_id="sess-1")
        engine.submit_feedback(node_id, 1, "explicit")
        engine.submit_feedback(node_id, 1, "explicit")

        rows = engine.db.conn.execute(
            "SELECT * FROM affinity WHERE node_id = ?", (node_id,)
        ).fetchall()
        assert len(rows) == 1

    def test_explicit_updates_review_log(self, engine):
        node_id = "node-review-001"
        _insert_whisper_log(engine.db.conn, node_id)
        review_id = _insert_review_log(engine.db.conn, node_id)

        engine.submit_feedback(node_id, 1, "explicit")

        row = engine.db.conn.execute(
            "SELECT answered FROM review_log WHERE id = ?", (review_id,)
        ).fetchone()
        assert row["answered"] == 1

    def test_implicit_does_not_update_review_log(self, engine):
        node_id = "node-review-implicit-001"
        _insert_whisper_log(engine.db.conn, node_id)
        review_id = _insert_review_log(engine.db.conn, node_id)

        engine.submit_feedback(node_id, 1, "implicit")

        row = engine.db.conn.execute(
            "SELECT answered FROM review_log WHERE id = ?", (review_id,)
        ).fetchone()
        assert row["answered"] == 0

    def test_returns_success_message(self, engine):
        node_id = "node-success-001"
        _insert_whisper_log(engine.db.conn, node_id)
        result = engine.submit_feedback(node_id, 1, "explicit")
        assert "Feedback recorded" in result


# ---------------------------------------------------------------------------
# TestSubmitFeedbackRoute
# ---------------------------------------------------------------------------


class TestSubmitFeedbackRoute:

    @pytest.fixture
    def client(self, tmp_memory_dir):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ormah.api.routes_agent import router as agent_router
        from ormah.config import Settings
        from ormah.engine.memory_engine import MemoryEngine

        settings = Settings(memory_dir=tmp_memory_dir)
        eng = MemoryEngine(settings)
        eng.startup()

        test_app = FastAPI()
        test_app.include_router(agent_router)
        test_app.state.engine = eng

        with TestClient(test_app) as c:
            yield c, eng

        eng.shutdown()

    def test_route_no_whisper_log(self, client):
        c, eng = client
        resp = c.post("/agent/feedback", json={"node_id": "nonexistent", "signal": 1})
        assert resp.status_code == 200
        assert "No whisper_log entry" in resp.json()["text"]

    def test_route_explicit_feedback(self, client):
        c, eng = client
        node_id = "route-node-001"
        _insert_whisper_log(eng.db.conn, node_id)

        resp = c.post("/agent/feedback", json={"node_id": node_id, "signal": 1, "source": "explicit"})
        assert resp.status_code == 200
        assert "Feedback recorded" in resp.json()["text"]

        row = eng.db.conn.execute(
            "SELECT * FROM affinity WHERE node_id = ?", (node_id,)
        ).fetchone()
        assert row is not None
        assert row["signal"] == 1

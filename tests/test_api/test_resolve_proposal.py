"""The proposal resolution endpoint carries no merge-specific handling (#10, ADR-0006).

After the merge Review queue is retired no merge proposal has a producer, so the endpoint
keeps only the branches whose proposal types still exist.

Two of the tests here are sensitive to the target defect — they fail if either removed
merge branch comes back:

- ``test_rejecting_a_merge_proposal_records_no_veto_anywhere``
- ``test_approving_a_merge_proposal_executes_no_merge``

The other three cover behaviour this ticket must leave alone; they pass against the
pre-refactor endpoint too, by design.

That sensitivity has to be built rather than assumed. The endpoint wraps its writes in a
broad ``except Exception`` that logs and continues, so a leftover write against a table
that #12 drops would be swallowed rather than failing anything — which is why the
rejection test asserts on the swallowing log as well as on the rows.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_agent import router as agent_router
from ormah.models.node import CreateNodeRequest, NodeType

_ENDPOINT_LOGGER = "ormah.api.routes_agent"


@pytest.fixture
def client(engine):
    test_app = FastAPI()
    test_app.include_router(agent_router)
    test_app.state.engine = engine
    with TestClient(test_app) as c:
        yield c


def _create_pair(engine):
    id_a, _ = engine.remember(
        CreateNodeRequest(content="Python is a programming language.", type=NodeType.fact,
                          title="Python language", tags=["test"]),
        agent_id="test",
    )
    id_b, _ = engine.remember(
        CreateNodeRequest(content="Python is a popular programming language.", type=NodeType.fact,
                          title="Python lang", tags=["test"]),
        agent_id="test",
    )
    return id_a, id_b


def _file_proposal(engine, proposal_type: str, node_ids: list[str]) -> str:
    proposal_id = str(uuid.uuid4())
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO proposals (id, type, status, source_nodes, proposed_action, "
            "reason, created) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
            (
                proposal_id,
                proposal_type,
                json.dumps(node_ids),
                f"Resolve two fact memories ({proposal_type})",
                "test fixture",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return proposal_id


def _row_counts(engine) -> dict[str, int]:
    """Row count of every table in the store.

    Table-agnostic on purpose: it catches a Veto written into *any* table, not only into
    the one the removed branch named. It does not, on its own, survive #12 dropping
    `duplicate_checked` — a restored INSERT against a missing table raises, the endpoint
    swallows it, and the counts stay equal. The log assertion is what covers that.
    """
    tables = [
        r["name"]
        for r in engine.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    return {
        t: engine.db.conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
        for t in tables
    }


def _swallowed_errors(caplog) -> list[str]:
    """What the endpoint's broad `except Exception` logged, if anything."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _ENDPOINT_LOGGER and r.levelno >= logging.ERROR
    ]


def _status_of(engine, proposal_id: str) -> str:
    return engine.db.conn.execute(
        "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()["status"]


def test_rejecting_a_merge_proposal_records_no_veto_anywhere(client, engine, caplog):
    id_a, id_b = _create_pair(engine)
    proposal_id = _file_proposal(engine, "merge", [id_a, id_b])

    before = _row_counts(engine)
    with caplog.at_level(logging.ERROR, logger=_ENDPOINT_LOGGER):
        resp = client.post(f"/agent/proposals/{proposal_id}", json={"action": "rejected"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert _status_of(engine, proposal_id) == "rejected"
    # The resolution writes the proposal's own status and nothing else...
    assert _row_counts(engine) == before
    # ...and it did not *try* to write a Veto and have the attempt swallowed, which is how
    # a restored branch would look once #12 has dropped the table it wrote to.
    assert _swallowed_errors(caplog) == []


def test_approving_a_merge_proposal_executes_no_merge(client, engine, caplog):
    id_a, id_b = _create_pair(engine)
    proposal_id = _file_proposal(engine, "merge", [id_a, id_b])

    before = _row_counts(engine)
    with caplog.at_level(logging.ERROR, logger=_ENDPOINT_LOGGER):
        resp = client.post(f"/agent/proposals/{proposal_id}", json={"action": "approved"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["merge_result"] is None
    assert _status_of(engine, proposal_id) == "approved"
    # Both memories survive, untouched — a merge would have consumed one of them.
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None
    assert _row_counts(engine) == before
    assert _swallowed_errors(caplog) == []


def test_approving_a_conflict_proposal_still_connects_the_two_nodes(client, engine):
    """The conflict branch is untouched by #10 and keeps behaving as it does today.

    Deliberately not asserted here: the *type* of the edge. The branch builds a
    `ConnectRequest(edge_type=...)` while the model's field is `edge`, so the edge it
    writes is a plain `related_to` — a pre-existing defect, out of scope for this ticket
    and not blessed by this test.
    """
    id_a, id_b = _create_pair(engine)
    proposal_id = _file_proposal(engine, "conflict", [id_a, id_b])

    edges_before = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM edges WHERE source_id = ? AND target_id = ?",
        (id_a, id_b),
    ).fetchone()["c"]

    resp = client.post(f"/agent/proposals/{proposal_id}", json={"action": "approved"})

    assert resp.status_code == 200
    assert resp.json()["conflict_result"] == (
        f"Created contradicts edge between {id_a[:8]} and {id_b[:8]}"
    )
    assert _status_of(engine, proposal_id) == "approved"
    edges_after = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM edges WHERE source_id = ? AND target_id = ?",
        (id_a, id_b),
    ).fetchone()["c"]
    assert edges_after == edges_before + 1


def test_rejecting_a_non_merge_proposal_only_resolves_it(client, engine):
    id_a, id_b = _create_pair(engine)
    proposal_id = _file_proposal(engine, "pattern", [id_a, id_b])

    before = _row_counts(engine)
    resp = client.post(f"/agent/proposals/{proposal_id}", json={"action": "rejected"})

    assert resp.status_code == 200
    assert _status_of(engine, proposal_id) == "rejected"
    assert _row_counts(engine) == before


def test_resolving_an_unknown_proposal_is_a_404(client):
    resp = client.post("/agent/proposals/does-not-exist", json={"action": "approved"})
    assert resp.status_code == 404

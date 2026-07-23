"""Tests for POST /ingest/nudge (ADR-0004 slice 1, Task 3).

The endpoint enqueues a durable spool job and answers 202 — it never touches the cursor,
never schedules a timer, never waits on extraction. The job must be on disk BEFORE the 202,
because the client hook drops its outbox record on that response and never retries.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_ingest import router as ingest_router
from ormah.background.ingest_spool import IngestSpool


@pytest.fixture
def app():
    # The nudge route is a pure spool producer: it needs no engine, only
    # app.state.session_watches, which each test populates with a stub.
    test_app = FastAPI()
    test_app.include_router(ingest_router)
    return test_app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def _watch_stub(watch_dir: Path, spool: IngestSpool):
    w = MagicMock()
    w.watch_dir = watch_dir
    w.spool = spool
    return w


def test_nudge_enqueues_and_accepts(client, app, tmp_path):
    t = tmp_path / "proj" / "session.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user"}\n')
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]

    r = client.post("/ingest/nudge", json={"path": str(t)})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}

    job = spool.claim_next()
    assert job is not None
    assert job.path == t.resolve()
    assert job.boundary == t.stat().st_size, "the boundary is the EOF at acceptance"
    assert job.reason == "nudge"
    assert job.force_flush is True, (
        "a nudge is an explicit SessionEnd/PreCompact ask -- it must enqueue force_flush=True "
        "so a short just-ended session flushes past the min_turns/idle gates (council-pr R4)"
    )


def test_the_job_is_durable_BEFORE_the_202(client, app, tmp_path):
    """The hook drops its outbox record on a 202. If the file is not on disk by then,
    the boundary is lost on a crash. Assert against the filesystem, not a mock."""
    t = tmp_path / "p" / "s.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user"}\n')
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    assert client.post("/ingest/nudge", json={"path": str(t)}).status_code == 202
    assert spool.pending_count() == 1


def test_nudge_returns_503_when_the_spool_write_fails(client, app, tmp_path, monkeypatch):
    """council R5/R11: never acknowledge what we could not record. A 202 the hook cannot
    trust is worse than an error it will retry."""
    t = tmp_path / "p" / "s.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text("x")
    spool = IngestSpool(tmp_path / "queue")
    monkeypatch.setattr(spool, "enqueue", MagicMock(side_effect=OSError("disk full")))
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    assert client.post("/ingest/nudge", json={"path": str(t)}).status_code == 503


def test_nudge_rejects_path_outside_acceptance_roots(client, app, tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(watched, spool)]
    outside = tmp_path / "evil.jsonl"
    outside.write_text("x")
    assert client.post("/ingest/nudge", json={"path": str(outside)}).status_code == 422
    assert spool.pending_count() == 0


def test_nudge_404_on_missing_file(client, app, tmp_path):
    app.state.session_watches = [_watch_stub(tmp_path, IngestSpool(tmp_path / "q"))]
    assert client.post(
        "/ingest/nudge", json={"path": str(tmp_path / "gone.jsonl")}).status_code == 404


def test_symlinked_spellings_do_not_double_enqueue(client, app, tmp_path):
    """Two paths for one transcript must not become two independent ingests."""
    real = tmp_path / "p" / "s.jsonl"
    real.parent.mkdir(parents=True)
    real.write_text("x")
    link = tmp_path / "p" / "alias.jsonl"
    link.symlink_to(real)
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    client.post("/ingest/nudge", json={"path": str(real)})
    client.post("/ingest/nudge", json={"path": str(link)})
    jobs = []
    while (j := spool.claim_next()) is not None:
        jobs.append(j)
        spool.complete(j)
    assert len({j.path for j in jobs}) == 1

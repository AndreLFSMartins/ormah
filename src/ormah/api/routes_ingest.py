"""Ingest API routes for bulk conversation import."""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

router = APIRouter(prefix="/ingest", tags=["ingest"])


class ConversationLog(BaseModel):
    agent_id: str | None = None
    content: str


class NudgeRequest(BaseModel):
    path: str
    session_id: str | None = None


@router.post("/nudge", status_code=202)
def ingest_nudge(req: NudgeRequest, request: Request):
    """ADR-0004: fire-and-forget ingest trigger. The server owns the cursor; the worker
    drains the spool on its own schedule. The client never waits on extraction."""
    watches = getattr(request.app.state, "session_watches", [])
    path = Path(req.path).resolve()
    for w in watches:
        try:
            path.relative_to(Path(w.watch_dir).resolve())
        except ValueError:
            continue
        try:
            boundary = path.stat().st_size
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="transcript not found")
        try:
            # DURABLE BEFORE THE 202: the hook drops its outbox record on this response
            # and never retries, so an unrecorded nudge is a lost session.
            # force_flush=True: a nudge is an explicit SessionEnd/PreCompact ask -- it must
            # flush a short just-ended session past the min_turns/idle gates (council-pr R2).
            w.spool.enqueue(path, boundary=boundary, reason="nudge", force_flush=True)
        except OSError as e:
            raise HTTPException(status_code=503, detail=f"could not accept nudge: {e}")
        w.handler.wake()          # Task 2: nudge the worker loop; never blocks
        return {"status": "accepted"}
    raise HTTPException(status_code=422, detail="path outside watched directories")


@router.post("/conversation")
def ingest_conversation(
    log: ConversationLog,
    request: Request,
    default_space: str | None = Query(None, description="Default space for extracted memories"),
    dry_run: bool = Query(False, description="Extract but don't store — return what would be ingested"),
    extra_tags: str | None = Query(None, description="Comma-separated extra tags to apply to extracted memories"),
):
    """Submit raw conversation text for server-side memory extraction.

    Uses the configured LLM to identify memorable information,
    deduplicates against existing memories, and stores new nodes.

    When dry_run=true, runs extraction and dedup but skips storage.
    """
    tag_list = [t.strip() for t in extra_tags.split(",") if t.strip()] if extra_tags else None
    engine = request.app.state.engine
    result = engine.ingest_conversation(
        content=log.content,
        space=default_space,
        agent_id=log.agent_id,
        dry_run=dry_run,
        extra_tags=tag_list,
    )
    if isinstance(result, str):
        return {"status": "error", "result": result, "extracted": 0, "memories": []}
    return {
        "status": "dry_run" if dry_run else "processed",
        "extracted": len(result),
        "memories": result,
    }


@router.post("/file")
async def ingest_file(request: Request, file: UploadFile = File(...)):
    """Upload a conversation log file for server-side memory extraction."""
    engine = request.app.state.engine
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    content = raw.decode("utf-8")
    filename = file.filename
    result = await anyio.to_thread.run_sync(
        lambda: engine.ingest_conversation(
            content=content,
            agent_id=f"file:{filename}",
        )
    )
    if isinstance(result, str):
        return {"status": "error", "result": result, "extracted": 0, "memories": []}
    return {
        "status": "processed",
        "extracted": len(result),
        "memories": result,
    }

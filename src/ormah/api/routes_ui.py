"""UI API routes for the web graph explorer."""

from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/graph")
def get_graph(request: Request, space: str | None = None, scope: str | None = None):
    """Graph data for the explorer.

    Default (no ``space``): the *active graph* — non-archival nodes plus the
    self/user node — so the overview never loads the whole archival history.
    ``?space=<S>``: the full set for one space (active + archival) for
    drill-down. ``?space=`` (empty) selects the no-space group.
    ``?scope=all``: every node across all tiers and spaces (explicit
    opt-in "show all"); takes precedence over ``space``.
    """
    engine = request.app.state.engine
    conn = engine.db.conn
    user_node_id = getattr(engine, "user_node_id", None)

    if scope == "all":
        rows = conn.execute("SELECT * FROM nodes").fetchall()
    elif space is None:
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
    # Signal the no-space group's existence over ALL nodes so the
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


@router.get("/graph/node/{node_id}")
def get_node_detail(node_id: str, request: Request):
    """Get detailed node info for the side panel."""
    engine = request.app.state.engine
    node = engine.graph.get_node(node_id)
    if node is None:
        return {"error": "not found"}

    edges = engine.graph.get_edges_for(node_id)
    neighbors = engine.graph.get_neighbors(node_id, depth=1)
    tags = [
        r["tag"]
        for r in engine.db.conn.execute(
            "SELECT tag FROM node_tags WHERE node_id = ?", (node_id,)
        ).fetchall()
    ]

    return {
        "node": node,
        "edges": edges,
        "neighbors": [dict(n) for n in neighbors],
        "tags": tags,
    }


@router.get("/search")
def search_nodes(q: str, request: Request, limit: int = 20):
    """Search nodes for the UI, returning structured results.

    Uses the same hybrid search (FTS + vector) as the MCP agent path
    so that results are consistent everywhere.
    """
    engine = request.app.state.engine
    if not q.strip():
        return []

    results = engine.recall_search_structured(q, limit=limit)
    # Flatten: return node dicts with _score for the UI
    out = []
    for r in results:
        node = r["node"]
        node["_score"] = r.get("score", 0)
        out.append(node)
    return out


@router.get("/insights")
def get_insights(request: Request):
    """Get belief evolutions and unresolved tensions for the insights panel."""
    engine = request.app.state.engine
    conn = engine.db.conn

    # Fetch evolved_from edges joined with both nodes
    evolutions_rows = conn.execute(
        """
        SELECT
            e.source_id AS newer_id, e.target_id AS older_id, e.reason,
            n1.title AS newer_title, n1.type AS newer_type, n1.tier AS newer_tier,
            n1.content AS newer_content, n1.created AS newer_created,
            n2.title AS older_title, n2.type AS older_type, n2.tier AS older_tier,
            n2.content AS older_content, n2.created AS older_created
        FROM edges e
        JOIN nodes n1 ON n1.id = e.source_id
        JOIN nodes n2 ON n2.id = e.target_id
        WHERE e.edge_type = 'evolved_from'
        ORDER BY n1.created DESC
        """
    ).fetchall()

    evolutions = [
        {
            "newer": {
                "id": r["newer_id"], "title": r["newer_title"], "type": r["newer_type"],
                "tier": r["newer_tier"], "content": r["newer_content"], "created": r["newer_created"],
            },
            "older": {
                "id": r["older_id"], "title": r["older_title"], "type": r["older_type"],
                "tier": r["older_tier"], "content": r["older_content"], "created": r["older_created"],
            },
            "explanation": r["reason"] or "",
        }
        for r in evolutions_rows
    ]

    # Fetch contradicts edges joined with both nodes
    tensions_rows = conn.execute(
        """
        SELECT
            e.source_id, e.target_id, e.reason,
            n1.title AS title_a, n1.type AS type_a, n1.tier AS tier_a,
            n1.content AS content_a, n1.created AS created_a,
            n2.title AS title_b, n2.type AS type_b, n2.tier AS tier_b,
            n2.content AS content_b, n2.created AS created_b
        FROM edges e
        JOIN nodes n1 ON n1.id = e.source_id
        JOIN nodes n2 ON n2.id = e.target_id
        WHERE e.edge_type = 'contradicts'
        ORDER BY e.created DESC
        """
    ).fetchall()

    tensions = [
        {
            "node_a": {
                "id": r["source_id"], "title": r["title_a"], "type": r["type_a"],
                "tier": r["tier_a"], "content": r["content_a"], "created": r["created_a"],
            },
            "node_b": {
                "id": r["target_id"], "title": r["title_b"], "type": r["type_b"],
                "tier": r["tier_b"], "content": r["content_b"], "created": r["created_b"],
            },
            "explanation": r["reason"] or "",
        }
        for r in tensions_rows
    ]

    return {"evolutions": evolutions, "tensions": tensions}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time graph updates."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Future: handle real-time subscriptions
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        pass

"""Seed the isolated recall eval DB with memories from a corpus case."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ormah.models.node import Connection, EdgeType, MemoryNode, NodeType, Tier


def _seed_created(mem: dict) -> datetime | None:
    """Return a created datetime for *mem*, or None for 'now'.

    Supports ``created`` (ISO string) or ``created_days_ago`` (number).
    """
    days_ago = mem.get("created_days_ago")
    if days_ago is not None:
        return datetime.now(timezone.utc) - timedelta(days=float(days_ago))
    iso = mem.get("created")
    if iso:
        s = str(iso).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def seed_case(engine, case: dict) -> None:
    """Clear eval DB and seed with memories from *case*.

    Memories are inserted with their corpus node_id preserved — no UUID generation.
    Skips auto-linking and core-cap enforcement (not relevant for eval).
    """
    clear_eval_db(engine)
    for mem in case.get("memories", []):
        connections: list[Connection] = []
        for c in mem.get("connections", []) or []:
            if not isinstance(c, dict) or not c.get("target"):
                continue
            try:
                connections.append(Connection(
                    target=c["target"],
                    edge=EdgeType(c.get("edge", "related_to")),
                    weight=float(c.get("weight", 0.5)),
                ))
            except Exception:
                continue

        # created may be backdated, but updated/last_accessed stay "now" so
        # FSRS decay does not silently drop backdated nodes from retrieval.
        # Cases that want decayed nodes set stability explicitly.
        created = _seed_created(mem)
        now = datetime.now(timezone.utc)
        node = MemoryNode(
            id=mem["node_id"],
            type=NodeType(mem.get("type", "fact")),
            tier=Tier(mem.get("tier", "working")),
            title=mem.get("title"),
            content=mem.get("content", ""),
            space=mem.get("space"),
            tags=mem.get("tags", []),
            connections=connections,
            source="eval:corpus",
            confidence=float(mem.get("confidence", 1.0)),
            stability=float(mem.get("stability", 1.0)),
            created=created or now,
            updated=now,
            last_accessed=now,
        )
        path = engine.file_store.save(node)
        engine.builder.index_single(path)
        engine._index_embedding(node)


def clear_eval_db(engine) -> None:
    """Remove all nodes from the eval DB and file store."""
    nodes_dir = engine.file_store.nodes_dir
    for md_file in nodes_dir.glob("*.md"):
        md_file.unlink()
    engine.file_store._id_cache.clear()
    engine.file_store._cache_built = False
    engine.builder.full_rebuild()
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

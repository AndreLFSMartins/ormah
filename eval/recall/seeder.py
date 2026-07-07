"""Seed the isolated recall eval DB with memories from a corpus case."""

from __future__ import annotations

from ormah.models.node import MemoryNode, NodeType, Tier


def seed_case(engine, case: dict) -> None:
    """Clear eval DB and seed with memories from *case*.

    Memories are inserted with their corpus node_id preserved — no UUID generation.
    Skips auto-linking and core-cap enforcement (not relevant for eval).
    """
    clear_eval_db(engine)
    for mem in case.get("memories", []):
        node = MemoryNode(
            id=mem["node_id"],
            type=NodeType(mem.get("type", "fact")),
            tier=Tier(mem.get("tier", "working")),
            title=mem.get("title"),
            content=mem.get("content", ""),
            space=mem.get("space"),
            tags=mem.get("tags", []),
            source="eval:corpus",
            confidence=float(mem.get("confidence", 1.0)),
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

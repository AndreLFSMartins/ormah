"""Background job: consolidate clusters of similar working-tier memories via LLM."""

from __future__ import annotations

import hashlib
import json
import logging
import time

from ormah.background.memory_lock import serialized_memory_job

logger = logging.getLogger(__name__)

_VALID_NODE_TYPES = ("fact", "decision", "preference", "event", "person",
                     "project", "concept", "procedure", "goal", "observation")

_CONSOLIDATE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "type": {
            "type": "string",
            "enum": list(_VALID_NODE_TYPES),
        },
    },
    "required": ["title", "summary", "type"],
    "additionalProperties": False,
}


def _cluster_signature(cluster: list[dict]) -> str:
    """Content signature of a cluster: changes if any member's id/title/content/
    space/type changes, so an unchanged cluster is skipped but any edit re-triggers
    evaluation (self-invalidating — no explicit invalidation site needed)."""
    def _fields(n: dict) -> str:
        return "|".join(str(n.get(k) or "") for k in ("id", "title", "content", "space", "type"))
    parts = sorted(hashlib.sha256(_fields(n).encode()).hexdigest() for n in cluster)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
_CONSOLIDATE_PROMPT = """\
You are consolidating a cluster of semantically similar memories into a single, richer memory. The consolidated memory will be stored as a new working-tier node, and the originals will be demoted to archival (still searchable but deprioritized). This means your output becomes the PRIMARY representation of this knowledge — it must be complete.

Memories to consolidate:
{items_text}

## Your task

Synthesize these into ONE memory that is better than any individual original. The result should read as a well-written knowledge base entry — not a list of bullet points stitched together, but a coherent narrative.

## Rules

1. **Preserve every concrete detail**: Names, versions, paths, numbers, dates, specific choices, file locations, command flags. If any original says "bge-base-en-v1.5" or "port 8787", the consolidated version must include it. Never generalize specifics — "chose SQLite" must stay "chose SQLite", not "chose a database".

2. **Preserve all reasoning**: If any memory explains WHY something was decided, what alternative was rejected, or what constraint drove the design, that reasoning MUST appear. Reasoning is the most valuable part of memory — it prevents re-litigating decisions.

3. **Eliminate only true redundancy**: If three memories all state "uses FastAPI", say it once. But if they say different things about FastAPI (routing patterns, middleware choices, deployment config), keep ALL of those distinct facts.

4. **Choose the most valuable type**: Priority order: decision > procedure > observation > concept > fact. If the cluster contains a decision and supporting facts, the consolidated type should be "decision" because that's what makes the memory actionable.

5. **Title for searchability**: Titles get 10x weight in full-text search. Make it specific and keyword-rich. BAD: "Project architecture". GOOD: "Ormah uses FastAPI + SQLite with hybrid FTS/vector search". The title should let someone find this memory by searching for any of its key topics.

6. **Content length**: 3-8 sentences. Long enough to be self-contained, short enough to be scannable. This will be displayed to an AI assistant as context — it needs to absorb it quickly.

Return a JSON object:
{{
  "title": "specific, keyword-rich title, 5-15 words",
  "summary": "consolidated content as a coherent narrative, preserving all unique details",
  "type": "fact|decision|preference|event|person|project|concept|procedure|goal|observation"
}}"""


def _prompt_overhead_chars() -> int:
    """Chars the template costs around the items block.

    Computed from the template itself so it cannot go stale when the prompt is edited -- this
    number is subtracted from the operator's budget, so a hardcoded copy that drifted would
    silently overrun the window the consolidation route asks for.
    """
    return len(_CONSOLIDATE_PROMPT.format(items_text=""))


def _render_item(node: dict) -> str:
    """One source as it appears in the items block. FULL content -- never a slice (#192)."""
    title = node.get("title") or "Untitled"
    content = node.get("content", "")
    return f"- [{title}]: {content}"


def _item_chars(node: dict) -> int:
    """What one source costs in the prompt: its rendered line plus the newline that joins it."""
    return len(_render_item(node)) + 1


def _split_cluster_to_fit(cluster: list[dict], budget_chars: int) -> list[list[dict]]:
    """Split *cluster* into sub-clusters whose rendered items fit within *budget_chars*.

    Greedy, in the order given -- which is the order ``_find_consolidation_clusters`` produces
    (seed first, then descending similarity), so the most similar sources stay together in the
    first sub-cluster.

    A source is NEVER truncated (#192): one that does not fit the remainder opens a new
    sub-cluster, and one larger than the whole budget is dropped entirely and left where it is.
    Losing a consolidation is recoverable -- the node stays working and keeps being whispered.
    Summarizing from a partial view is not, because the sources are demoted to archival the
    moment the summary is written.

    Sub-clusters shorter than ``consolidation_min_cluster_size`` are NOT filtered here; that is
    the caller's decision, which keeps this function pure and settings-free.
    """
    if budget_chars <= 0:
        logger.warning(
            "consolidation prompt budget is %d chars after the template's own overhead; "
            "raise ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS -- nothing can be consolidated",
            budget_chars,
        )
        return []

    parts: list[list[dict]] = []
    current: list[dict] = []
    used = 0

    for node in cluster:
        cost = _item_chars(node)
        if cost > budget_chars:
            logger.warning(
                "consolidation source %s costs %d chars, more than the whole prompt budget "
                "(%d); it stays put rather than being summarized from a partial view",
                node.get("id"), cost, budget_chars,
            )
            continue
        if current and used + cost > budget_chars:
            parts.append(current)
            current = []
            used = 0
        current.append(node)
        used += cost

    if current:
        parts.append(current)
    return parts


def _find_consolidation_clusters(engine, limit: int = 4) -> list[list[dict]]:
    """Find clusters of similar working-tier nodes for consolidation.

    Returns up to *limit* clusters, each a list of node dicts (max
    ``engine.settings.consolidation_max_cluster_nodes`` nodes).
    Does NOT call the LLM — pure similarity-based clustering.
    """
    try:
        from ormah.embeddings.vector_store import VectorStore
    except ImportError:
        return []

    conn = engine.db.conn
    s = engine.settings
    min_size = s.consolidation_min_cluster_size
    max_nodes = s.consolidation_max_cluster_nodes
    threshold = s.consolidation_cluster_threshold

    if max_nodes < min_size:
        logger.warning(
            "consolidation_max_cluster_nodes (%d) < consolidation_min_cluster_size (%d); "
            "no cluster can ever be emitted",
            max_nodes, min_size,
        )
        return []

    rows = conn.execute(
        "SELECT id, title, content, space, type FROM nodes WHERE tier = 'working'"
    ).fetchall()
    if len(rows) < min_size:
        return []

    vec_store = VectorStore(engine.db)

    clustered_ids: set[str] = set()
    clusters: list[list[dict]] = []

    for row in rows:
        if len(clusters) >= limit:
            break

        nid = row["id"]
        if nid in clustered_ids:
            continue

        node_vec = vec_store.get(nid)
        if node_vec is None:
            continue

        similar = vec_store.search(node_vec, limit=20)
        cluster = [dict(row)]
        clustered_ids.add(nid)

        for match in similar:
            if len(cluster) >= max_nodes:
                break
            mid = match["id"]
            if mid == nid or mid in clustered_ids:
                continue
            if match["similarity"] < threshold:
                continue
            m_row = conn.execute(
                "SELECT id, title, content, space, type, tier FROM nodes WHERE id = ?",
                (mid,),
            ).fetchone()
            if m_row is None or m_row["tier"] != "working":
                continue
            cluster.append(dict(m_row))
            clustered_ids.add(mid)

        if len(cluster) >= min_size:
            clusters.append(cluster)

    return clusters


def _apply_consolidation(
    engine,
    node_ids: list[str],
    title: str,
    content: str,
    node_type: str,
) -> str:
    """Create a consolidated node, link originals, and demote them to archival.

    Returns the new node's ID.
    """
    from ormah.models.node import (
        ConnectRequest,
        CreateNodeRequest,
        EdgeType,
        Tier,
        UpdateNodeRequest,
    )

    conn = engine.db.conn
    placeholders = ",".join("?" * len(node_ids))

    # Fetch cluster nodes for space determination and identity transfer
    cluster_rows = conn.execute(
        f"SELECT id, space FROM nodes WHERE id IN ({placeholders})",
        node_ids,
    ).fetchall()
    cluster = [dict(r) for r in cluster_rows]

    # Determine space by majority vote
    space_counts: dict[str | None, int] = {}
    for node in cluster:
        sp = node.get("space")
        space_counts[sp] = space_counts.get(sp, 0) + 1
    space = max(space_counts, key=space_counts.get)  # type: ignore[arg-type]

    # Create consolidated node
    req = CreateNodeRequest(
        content=content,
        type=node_type,
        title=title,
        space=space,
        tags=["consolidated"],
    )
    new_id, _ = engine.remember(req, agent_id="consolidator")

    # Transfer identity edges
    if engine.user_node_id:
        has_identity = conn.execute(
            f"SELECT 1 FROM edges WHERE source_id = ? AND edge_type = 'defines' "
            f"AND target_id IN ({placeholders}) LIMIT 1",
            [engine.user_node_id] + node_ids,
        ).fetchone()
        if has_identity:
            try:
                engine.connect(ConnectRequest(
                    source_id=engine.user_node_id,
                    target_id=new_id,
                    edge=EdgeType.defines,
                    weight=1.0,
                ))
            except Exception:
                pass
            new_node = engine.file_store.load(new_id)
            if new_node and "about_self" not in new_node.tags:
                new_node.tags.append("about_self")
                new_node.touch_updated()
                engine.file_store.save(new_node)
                with engine.db.transaction() as tx_conn:
                    tx_conn.execute(
                        "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, 'about_self')",
                        (new_id,),
                    )

    # Create derived_from edges, record supersession, then demote originals to archival.
    # Mark BEFORE demoting (#223): crashing between the two leaves the node working +
    # marked, which is harmless because the marker only blocks automatic promotion.
    # The reverse order would leave it archival + unmarked — a promotable node.
    for node_id in node_ids:
        try:
            engine.connect(ConnectRequest(
                source_id=new_id,
                target_id=node_id,
                edge=EdgeType.derived_from,
                weight=1.0,
            ))
        except Exception:
            pass
        engine._mark_superseded(node_id, new_id)
        engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))

    return new_id


@serialized_memory_job
def run_consolidation(engine) -> dict | None:
    """Find clusters of similar working memories and consolidate via LLM."""
    t0 = time.monotonic()
    settings = engine.settings
    if not settings.llm_enabled:
        return {"skipped": "llm_disabled"}

    clusters = _find_consolidation_clusters(
        engine, limit=settings.consolidation_max_clusters_per_run
    )
    if not clusters:
        return {
            "clusters_found": 0,
            "clusters_consolidated": 0,
            "duration_s": round(time.monotonic() - t0, 3),
        }

    consolidated_count = 0
    for cluster in clusters:
        try:
            _consolidate_cluster(engine, cluster)
            consolidated_count += 1
        except Exception as e:
            logger.warning("Failed to consolidate cluster: %s", e)

    stats = {
        "clusters_found": len(clusters),
        "clusters_consolidated": consolidated_count,
        "duration_s": round(time.monotonic() - t0, 3),
    }
    logger.info("consolidator run: %s", stats)
    return stats


def _consolidate_cluster(engine, cluster: list[dict]) -> None:
    """Consolidate a single cluster using LLM summarization."""
    from ormah.background.llm_client import extract_json, llm_generate

    sig = _cluster_signature(cluster)
    seen = engine.db.conn.execute(
        "SELECT 1 FROM consolidation_checked WHERE signature = ?", (sig,)
    ).fetchone()
    if seen:
        return

    # Build prompt from FULL content, never a slice (#192). The prompt below tells the model its
    # output "becomes the PRIMARY representation of this knowledge" and that it must "preserve
    # every concrete detail" -- instructions that are meaningless about text the model was never
    # shown, and destructive here because _apply_consolidation demotes every source to archival
    # immediately afterwards. A cluster too large for the prompt is split upstream in
    # run_consolidation; it is never trimmed.
    items_text = "\n".join(_render_item(node) for node in cluster)

    prompt = _CONSOLIDATE_PROMPT.format(items_text=items_text)

    raw = llm_generate(
        engine.settings, prompt, json_mode=True,
        response_format={"type": "json_schema", "json_schema": {"schema": _CONSOLIDATE_RESPONSE_SCHEMA}},
    )
    if raw is None:
        return  # LLM unavailable — transient, do NOT record, must retry next run

    try:
        result = json.loads(extract_json(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        # ponytail: transient parse failure -> retry next run (do NOT record). Now rare thanks to
        # the adapter result-fallback. Ceiling: a cluster whose content DETERMINISTICALLY fails to
        # parse is retried every run (bounded by consolidation_max_clusters_per_run); add a checked_at backoff
        # column if that ever bleeds.
        logger.warning("LLM returned unparseable JSON for consolidation; will retry next run")
        return

    title = result.get("title", "Consolidated memory")
    summary = result.get("summary", "")
    node_type = result.get("type", "fact")
    if node_type not in _VALID_NODE_TYPES:
        node_type = "fact"

    if not summary:
        _record_signature(engine, sig)
        return

    node_ids = [n["id"] for n in cluster]
    new_id = _apply_consolidation(engine, node_ids, title, summary, node_type)
    # Audit trail (#192): the sources are demoted to archival by the call above, so this summary
    # becomes what gets read instead of them. Recording both sizes makes a consolidation that
    # shed too much visible in the logs without re-measuring the store by hand.
    #
    # Logged BEFORE _record_signature: the consolidation has already happened by this point, so a
    # failure to mark the cluster checked must not also cost us the audit line for it.
    logger.info(
        "consolidated %d sources into %s: source_chars=%d summary_chars=%d sources=%s",
        len(node_ids), new_id,
        sum(len(n.get("content") or "") for n in cluster), len(summary),
        ",".join(node_ids),
    )
    _record_signature(engine, sig)


def _record_signature(engine, sig: str) -> None:
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO consolidation_checked (signature, checked_at) "
            "VALUES (?, datetime('now'))", (sig,))

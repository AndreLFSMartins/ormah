"""Detect contradictions between memory nodes."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from ormah.background.llm import normalize_conflict_type
from ormah.background.memory_lock import serialized_memory_job
from ormah.models.node import Connection, EdgeType

logger = logging.getLogger(__name__)

_LLM_CONFLICT_INTRO = """\
You are checking whether two memories genuinely contradict each other. False positives create noise in the graph and waste the user's time resolving non-conflicts. Be very conservative — only flag true contradictions."""

_LLM_CONFLICT_PAIR = """\
Memory A (created: {created_a}, space: {space_a}): "{title_a}"
{content_a}

Memory B (created: {created_b}, space: {space_b}): "{title_b}"
{content_b}"""

_LLM_CONFLICT_RULES = """\
## Decision process (stop at first "no")

**1. Same space AND same specific subject?**
- Different spaces/projects → NEVER a conflict. Full stop. A choice in project X says nothing about project Y.
- Same project but different components, features, or layers → NOT a conflict. Systems have many parts.
- Same project and same specific topic (e.g., both about "the database choice for project X's API") → continue.

**2. Are they genuinely incompatible?**
Both claims CANNOT be true simultaneously in the same context:
- "Uses Postgres for the API" + "Uses SQLite for the API" → YES, incompatible (same role, same system)
- "Dislikes tabs" + "Prefers 2-space indent" → NO, compatible (both anti-tab)
- "Prefers REST" + "Chose GraphQL for project X" → NO, preference vs specific decision coexist
- Architectural overview + pivot/redesign of that architecture → NOT a contradiction. The pivot supersedes the overview — that's an evolution, not a tension. An overview describing the system and a later decision changing the system are compatible in time.
- Implementation detail + high-level description of the same system → NOT a contradiction. Different granularity levels coexist.
- Config change (e.g., "intervals changed to daily") + description of what a job does → NOT a contradiction. Changing how often something runs doesn't conflict with what it does.

**3. If genuinely incompatible: evolution or tension?**
- **Evolution**: The person's view changed over time. The newer memory supersedes the older. Use creation dates. Example: "Uses Vim" (2024) → "Switched to VS Code" (2025). This is the most common case.
- **Tension**: Both are simultaneously held beliefs that genuinely pull in opposite directions. Rare. Example: "prefers minimal dependencies" + "keeps adding npm packages".

## Critical: these are NOT conflicts
- A project overview and a later architectural pivot → evolution at most, never tension
- A description of system behavior and a config change to that system → not a conflict
- Two memories about the same technology used in DIFFERENT projects
- A general preference and a project-specific exception
- Two memories at different abstraction levels (architecture doc vs implementation detail)

Return JSON only:
{{
  "same_subject": true or false,
  "conflict": true or false,
  "type": "evolution" or "tension" or "none",
  "evolved_node": "a" or "b" (the NEWER view per creation dates — only if type=evolution),
  "explanation": "one sentence using actual memory titles"
}}"""

_LLM_CONFLICT_PROMPT = _LLM_CONFLICT_INTRO + "\n\n" + _LLM_CONFLICT_PAIR + "\n\n" + _LLM_CONFLICT_RULES
_LLM_CONFLICT_INSTRUCTIONS = _LLM_CONFLICT_INTRO + "\n\n" + _LLM_CONFLICT_RULES  # sent once per batch


def _render_conflict_pair(pair: dict) -> str:
    """Render one candidate pair for a batched conflict prompt (#87)."""
    a, b = pair["node_a"], pair["node_b"]
    return _LLM_CONFLICT_PAIR.format(
        title_a=a["title"] or "(untitled)", content_a=a["content"][:500],
        created_a=a.get("created", "unknown"), space_a=a.get("space") or "global",
        title_b=b["title"] or "(untitled)", content_b=b["content"][:500],
        created_b=b.get("created", "unknown"), space_b=b.get("space") or "global",
    )


def _llm_check_conflict(settings, node_row, other_row) -> dict | None:
    """Ask LLM whether two nodes contradict each other.

    Returns parsed dict or None if the LLM is unavailable or returns
    invalid output.
    """
    from ormah.background.llm_client import extract_json, llm_generate

    def _get(row, key, default="unknown"):
        try:
            return row[key]
        except (KeyError, IndexError):
            return default

    prompt = _LLM_CONFLICT_PROMPT.format(
        title_a=node_row["title"] or "(untitled)",
        content_a=node_row["content"][:500],
        created_a=_get(node_row, "created"),
        space_a=_get(node_row, "space", "global"),
        title_b=other_row["title"] or "(untitled)",
        content_b=other_row["content"][:500],
        created_b=_get(other_row, "created"),
        space_b=_get(other_row, "space", "global"),
    )

    raw = llm_generate(settings, prompt, json_mode=True)
    if raw is None:
        return None

    try:
        result = json.loads(extract_json(raw))
        if "conflict" not in result:
            return None
        if "type" in result:
            result["type"] = normalize_conflict_type(result["type"])
        return result
    except (json.JSONDecodeError, TypeError):
        logger.warning("LLM returned invalid JSON for conflict check")
        return None


_BELIEF_TYPES = ('preference', 'fact', 'observation', 'goal')

CONFLICT_SCOPE_STAMP_KEY = "conflict_check_watermark_scope"


def _conflict_scope_value(settings) -> str:
    return "all" if settings.conflict_check_all_spaces else "global"


def _find_conflict_candidates(
    engine,
    limit: int = 8,
    *,
    max_seeds: int | None = None,
    delta: bool = False,
):
    """Find node pairs that might contradict each other.

    ``delta=False`` (default — the agent/two-call path): today's selection,
    unchanged: full ``ORDER BY RANDOM()`` fetch, returns a candidate list.

    ``delta=True`` (background run only, #81): seeds are nodes with ``seq``
    above the ``conflict_check_watermark``, oldest-first, bounded by
    *max_seeds* (default: ``conflict_check_max_nodes_per_run``). Vector
    neighbors are NOT filtered by age — a new seed pairs against neighbors of
    any age. Returns ``(candidates, drained_seeds)``; ``drained_seeds`` is
    ``[(node_id, seq), ...]`` ascending, containing only seeds whose neighbor
    loop completed (a seed cut short by the pair *limit* is excluded so the
    cursor never passes it). Candidates each carry ``seed_seq``. A scope-stamp
    mismatch (``conflict_check_all_spaces`` changed since the last advance)
    treats the watermark as 0. Only ``run_conflict_detection`` advances the
    watermark; this function never writes it. ``limit`` stays pair-denominated
    in both modes.
    """
    drained_seeds: list[tuple[str, int]] = []
    from ormah.embeddings.encoder import get_encoder
    from ormah.embeddings.vector_store import VectorStore, stored_or_encoded

    settings = engine.settings
    encoder = get_encoder(settings)
    vec_store = VectorStore(engine.db)

    space_filter = "" if settings.conflict_check_all_spaces else \
        "AND (space IS NULL OR space = 'null') "

    if delta:
        from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

        if max_seeds is None:
            max_seeds = settings.conflict_check_max_nodes_per_run
        watermark = get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY)
        stamp = engine.db.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (CONFLICT_SCOPE_STAMP_KEY,)
        ).fetchone()
        if stamp is not None and stamp["value"] != _conflict_scope_value(settings):
            watermark = 0  # scope changed: older nodes are newly in scope

        nodes = engine.db.conn.execute(
            "SELECT id, content, title, type, created, space, seq FROM nodes "
            f"WHERE type IN (?, ?, ?, ?) {space_filter}AND seq > ? "
            "ORDER BY seq ASC LIMIT ?",
            (*_BELIEF_TYPES, watermark, max_seeds),
        ).fetchall()
    else:
        # Legacy selection — byte-for-byte today's queries (agent path).
        nodes = engine.db.conn.execute(
            "SELECT id, content, title, type, created, space, seq FROM nodes "
            f"WHERE type IN (?, ?, ?, ?) {space_filter}ORDER BY RANDOM()",
            _BELIEF_TYPES,
        ).fetchall()

    checked: set[tuple[str, str]] = set()
    candidates: list[dict] = []
    barrier_hit = False

    for node in nodes:
        if len(candidates) >= limit:
            break  # pair budget hit before this seed: not drained

        text = f"{node['title'] or ''} {node['content']}".strip()
        if not text:
            if not barrier_hit:
                drained_seeds.append((node["id"], node["seq"]))
            continue

        # DRAIN BARRIER (overview invariant, mirrors upstream
        # auto_linker.py): a seed with text but no persisted vector must
        # not let the cursor advance past it — its pairs would be
        # permanently skipped once the vector is backfilled. `continue`,
        # not `break`: later seeds are still PROCESSED (liveness, mirrors
        # auto_linker) but no further seed drains once the barrier is hit.
        if delta and vec_store.get(node["id"]) is None:
            if not barrier_hit:
                logger.warning(
                    "conflict delta stalled: node %s has no persisted vector (embedding "
                    "backfill pending?); cursor parked at seq %s until it embeds",
                    node["id"][:8], node["seq"],
                )
            barrier_hit = True
            continue

        query_vec = stored_or_encoded(
            vec_store,
            encoder,
            node["id"],
            node["title"],
            node["content"],
            settings.embedding_max_content_chars,
        )
        similar = vec_store.search(query_vec, limit=15)

        for match in similar:
            if len(candidates) >= limit:
                break
            if match["id"] == node["id"]:
                continue

            pair = tuple(sorted([node["id"], match["id"]]))
            if pair in checked:
                continue
            checked.add(pair)

            already_checked = engine.db.conn.execute(
                "SELECT 1 FROM auto_link_checked WHERE node_a = ? AND node_b = ?", pair
            ).fetchone()
            if already_checked:
                continue

            similarity = match["similarity"]
            if similarity < 0.4:
                continue

            other = engine.db.conn.execute(
                "SELECT id, title, content, type, created, space FROM nodes WHERE id = ?",
                (match["id"],),
            ).fetchone()
            if other is None:
                continue
            if other["type"] not in _BELIEF_TYPES:
                continue

            has_edge = engine.db.conn.execute(
                "SELECT 1 FROM edges WHERE edge_type IN ('contradicts', 'evolved_from') AND "
                "((source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?))",
                (node["id"], match["id"], match["id"], node["id"]),
            ).fetchone()
            if has_edge:
                continue

            def _nd(row) -> dict:
                return {
                    "id": row["id"],
                    "title": row["title"] or "",
                    "type": row["type"] or "",
                    "space": row["space"] or "",
                    "content": (row["content"] or "")[:400],
                    "created": row["created"] or "",
                }

            candidates.append({
                "node_a": _nd(node),
                "node_b": _nd(other),
                "similarity": round(similarity, 3),
                "seed_seq": node["seq"],
            })

        if len(candidates) >= limit:
            break  # pair budget hit mid-seed: possibly partial, not drained
        if not barrier_hit:
            drained_seeds.append((node["id"], node["seq"]))

    if delta:
        return candidates, drained_seeds
    return candidates


@serialized_memory_job
def run_conflict_detection(engine) -> dict | None:
    """Find potentially contradicting nodes and create edges.

    Seeds are delta-selected via a seq watermark (#81): only nodes newer than
    the last successfully-drained seed are scanned each run, so coverage
    converges instead of re-scanning the whole store every time. Candidate
    pairs from _find_conflict_candidates are then judged in K-sized LLM
    calls (#87). At K=1 the judge is a pure map — one _llm_check_conflict per
    candidate, exactly as before — so the existing suite is the K=1 regression
    net.
    """
    t0 = time.monotonic()
    try:
        from ormah.background.llm.pair_batch import judge_pairs
        from ormah.background.watermark import (
            CONFLICT_WATERMARK_KEY, get_watermark, set_watermark,
        )

        settings = engine.settings

        if not settings.llm_enabled:
            logger.debug("Conflict detection skipped: LLM not enabled")
            return {"skipped": "llm_disabled"}

        # Durably reset the cursor on a scope change BEFORE selection (#81) —
        # so an expanded scope re-examines older nodes even if THIS run cannot
        # drain the first seed (vectorless barrier) or the finder returns
        # empty on a transient error. Persisting here (not just ephemerally in
        # the finder) is what makes the reset survive to the next run: the
        # advance loop below reloads the persisted watermark.
        _stamp = engine.db.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (CONFLICT_SCOPE_STAMP_KEY,)
        ).fetchone()
        if _stamp is not None and _stamp["value"] != _conflict_scope_value(settings):
            set_watermark(engine, CONFLICT_WATERMARK_KEY, 0)

        # Pair-denominated cap (#87): default 10000 == the previous hardcoded
        # limit, so out-of-the-box behavior is unchanged; now operator-
        # configurable. Seed selection (which nodes are scanned) is bounded
        # separately by conflict_check_max_nodes_per_run (#81).
        max_pairs = settings.conflict_check_max_pairs_per_run
        candidates, drained_seeds = _find_conflict_candidates(
            engine, limit=max_pairs, delta=True,
        )
        k = max(settings.conflict_check_pairs_per_call or settings.maintenance_pairs_per_call, 1)

        verdicts = judge_pairs(
            settings, _LLM_CONFLICT_INSTRUCTIONS, candidates, _render_conflict_pair,
            judge_single=lambda c: _llm_check_conflict(settings, c["node_a"], c["node_b"]),
            k=k,
        )

        edges_created = 0
        pairs_attempted = 0
        pairs_evaluated = 0
        failed_seed_seqs: set[int] = set()
        dirty_nodes: dict[str, list[Connection]] = {}

        for candidate, llm_result in zip(candidates, verdicts):
            node_a = candidate["node_a"]
            node_b = candidate["node_b"]

            pairs_attempted += 1
            if llm_result is None:
                failed_seed_seqs.add(candidate["seed_seq"])
                continue
            pairs_evaluated += 1
            if not llm_result.get("conflict"):
                continue
            if not llm_result.get("same_subject", True):
                continue
            # Batch verdicts arrive un-normalized; the single path already
            # normalized inside _llm_check_conflict (double-normalize is idempotent).
            if "type" in llm_result:
                llm_result["type"] = normalize_conflict_type(llm_result["type"])

            explanation = llm_result.get("explanation", "")
            now = datetime.now(timezone.utc).isoformat()
            conflict_type = llm_result.get("type", "tension")

            with engine.db.transaction() as db_conn:
                if conflict_type == "evolution":
                    evolved = llm_result.get("evolved_node", "b")
                    if evolved == "a":
                        newer_id, older_id = node_a["id"], node_b["id"]
                    else:
                        newer_id, older_id = node_b["id"], node_a["id"]

                    # OR IGNORE: auto_linker also emits contradicts, and both jobs run
                    # concurrently over overlapping pairs. A concurrent writer may have
                    # created this exact edge while the LLM was judging — same race as #117.
                    cur = db_conn.execute(
                        "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                        "VALUES (?, ?, 'evolved_from', 0.9, ?, ?)",
                        (newer_id, older_id, now, explanation),
                    )
                    edge_type_str = "evolved_from"
                    source_id, target_id = newer_id, older_id
                else:
                    cur = db_conn.execute(
                        "INSERT OR IGNORE INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                        "VALUES (?, ?, 'contradicts', 0.9, ?, ?)",
                        (node_a["id"], node_b["id"], now, explanation),
                    )
                    edge_type_str = "contradicts"
                    source_id, target_id = node_a["id"], node_b["id"]

            # Queue the markdown connection UNCONDITIONALLY, not only when we won the
            # insert (Codex R2, critical #1 — the same data-loss path Task 1 closes).
            # The file is the source of truth; if the writer that won the row failed to
            # save its markdown, this is the only chance to repair it. rowcount only
            # decides whether this run *created* an edge, i.e. the metric.
            md_conn = Connection(
                target=target_id,
                edge=EdgeType(edge_type_str),
                weight=0.9,
                # Coerce for the same reason as auto_linker: a non-string LLM explanation
                # would raise on Connection and cost us the markdown connection.
                reason=str(explanation) if explanation else None,
            )
            dirty_nodes.setdefault(source_id, []).append(md_conn)
            if cur.rowcount > 0:
                edges_created += 1

        # Persist new connections to markdown files
        for nid, new_connections in dirty_nodes.items():
            try:
                mem_node = engine.file_store.load(nid)
                if mem_node is None:
                    continue
                existing = {(c.target, c.edge.value) for c in mem_node.connections}
                fresh = [
                    c for c in new_connections if (c.target, c.edge.value) not in existing
                ]
                if not fresh:
                    continue
                mem_node.connections.extend(fresh)
                mem_node.touch_updated()
                engine.file_store.save(mem_node)
            except Exception as e:
                logger.debug("Failed to persist conflict edge to markdown for %s: %s", nid[:8], e)

        # ponytail: contiguous-prefix advance; a deterministically failing seed
        # parks the cursor — dead-letter escape hatch is upstream #122.
        new_watermark = get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY)
        for _seed_id, seed_seq in drained_seeds:  # ascending seq
            if seed_seq in failed_seed_seqs:
                break
            new_watermark = seed_seq
        set_watermark(engine, CONFLICT_WATERMARK_KEY, new_watermark)
        # Stamp the scope this cursor was advanced under (finder resets on mismatch)
        with engine.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (CONFLICT_SCOPE_STAMP_KEY, _conflict_scope_value(settings)),
            )

        duration = time.monotonic() - t0
        stats = {
            "candidates_found": len(candidates),
            "pairs_attempted": pairs_attempted,
            "pairs_evaluated": pairs_evaluated,
            "edges_created": edges_created,
            "cap_hit": len(candidates) >= max_pairs,
            "duration_s": round(duration, 3),
            "pairs_per_s": round(pairs_evaluated / duration, 2) if duration > 0 else 0.0,
        }
        logger.info("conflict_detector run: %s", stats)
        return stats

    except Exception as e:
        logger.warning("Conflict detection failed: %s", e)
        return {"error": str(e)}

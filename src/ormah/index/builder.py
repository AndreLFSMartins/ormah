"""Index builder: full rebuild and incremental updates from markdown files."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ormah.index.db import Database
from ormah.index.fingerprint import content_fingerprint
from ormah.store.file_store import FileStore
from ormah.store.markdown import parse_node

logger = logging.getLogger(__name__)


class IndexBuilder:
    """Builds and updates the SQLite index from markdown source files."""

    def __init__(self, db: Database, file_store: FileStore) -> None:
        self.db = db
        self.file_store = file_store

    def full_rebuild(self, *, allow_partial: bool = False) -> int:
        """Drop and rebuild the entire index from markdown files. Returns node count.

        Atomic: DELETE + both insert passes run in ONE transaction, and the method aborts
        (-> ROLLBACK) rather than commit a partial index when any source file fails to
        index. A partial failure or an fd-exhaustion storm therefore preserves the prior
        committed state instead of persisting a truncated index. Pass allow_partial=True
        to accept a partial rebuild anyway (e.g. known-corrupt files that should be skipped).
        """
        paths = list(self.file_store.list_paths())
        # FileStore calls take L_mem. Complete them before the write transaction so no builder
        # path requests L_mem while holding L_db, the reverse of the order used by memory jobs.
        hashes: dict[Path, str] = {}
        for path in paths:
            try:
                hashes[path] = self.file_store.file_hash(path)
            except Exception as e:
                logger.warning("Failed to hash %s: %s", path, e)

        count = 0
        with self.db.transaction() as conn:
            # #126: capture the fingerprints BEFORE the wipe. A rebuild over CHANGED content
            # (a restore from an older/newer backup, an edited file) must drop that node's
            # cached pair verdicts, or the fresh seq is useless — auto_linker skips any pair
            # already in auto_link_checked, so the old content's link decisions would silently
            # carry over to the new content. Unchanged nodes keep their verdicts: re-judging an
            # untouched store with the LLM would be an enormous, pointless cost.
            prior_fps = {
                row["id"]: row["content_fingerprint"]
                for row in conn.execute("SELECT id, content_fingerprint FROM nodes")
            }
            conn.execute("DELETE FROM node_tags")
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes_fts")
            conn.execute("DELETE FROM nodes")
            try:
                conn.execute("DELETE FROM node_vectors")
            except Exception:
                pass  # table may not exist

            # Mass reindex re-allocates seq from the durable counter; clear the watermarks so
            # the rebuilt store is reprocessed even if the counter was also reset (wiped meta).
            # Also clear the conflict scope-stamp so post-rebuild state is fully coherent
            # (the stamp would otherwise linger and describe a scope for a watermark of 0).
            conn.execute(
                "DELETE FROM meta WHERE key IN "
                "('auto_link_watermark', 'duplicate_check_watermark', 'conflict_check_watermark', "
                "'conflict_check_watermark_scope')"
            )

            # Two-pass: nodes first, then edges (to satisfy FK constraints)
            for path in paths:
                if path not in hashes:
                    continue  # hashing failed above; already logged
                try:
                    self._index_file_nodes_only(path, hashes[path], prior_fingerprints=prior_fps)
                    count += 1
                except Exception as e:
                    logger.warning("Failed to index %s: %s", path, e)

            # Never commit a partial index when the source-of-truth files exist. A mass or
            # partial failure (e.g. fd exhaustion) would otherwise persist a truncated index —
            # the exact 2026-07-05 incident. Raising here rolls the whole transaction back.
            if paths and not allow_partial and count != len(paths):
                failed = len(paths) - count
                raise RuntimeError(
                    f"full_rebuild indexed {count}/{len(paths)} files ({failed} failed); "
                    "aborting to avoid persisting a partial index (pass allow_partial=True "
                    "to override)"
                )

            edge_failures = 0
            for path in paths:
                try:
                    self._index_file_edges(path)
                except Exception as e:
                    edge_failures += 1
                    logger.warning("Failed to index edges for %s: %s", path, e)
            if edge_failures:
                # Edges are DERIVED (auto_linker regenerates them; the watermark was cleared above),
                # so a per-file edge failure is best-effort and must NOT abort the rebuild the way a
                # missing node does — aborting on one bad link would roll back every good node and
                # could leave the store empty, the exact failure this rebuild guards against. Surface
                # the aggregate so the loss is not swallowed silently (council-pr H1).
                logger.error(
                    "full_rebuild: %d/%d files failed edge indexing; nodes are complete, edges are "
                    "best-effort and will be rebuilt by auto_linker",
                    edge_failures, len(paths),
                )

        return count

    def incremental_update(self) -> tuple[int, int]:
        """Update index for changed/new files. Returns (added, updated) counts."""
        conn = self.db.conn
        added = 0
        updated = 0

        indexed: dict[str, str] = {}
        for row in conn.execute("SELECT id, file_hash FROM nodes").fetchall():
            indexed[row["id"]] = row["file_hash"]

        indexed_ids = set(indexed.keys())
        disk_ids: set[str] = set()

        # FileStore calls take L_mem. Complete them before the write transaction so no builder
        # path requests L_mem while holding L_db, the reverse of the order used by memory jobs.
        paths = list(self.file_store.list_paths())
        hashes: dict[Path, str] = {}
        scan_complete = True
        for path in paths:
            try:
                hashes[path] = self.file_store.file_hash(path)
            except FileNotFoundError:
                # Genuinely gone between listing and hashing. Letting it fall out of disk_ids is
                # the correct signal: the removal phase below should drop its node.
                logger.info("Skipping %s: removed between listing and hashing", path)
            except Exception as e:
                # EMFILE, EIO, EACCES — the file is very likely still there. Absence is NOT
                # established, so the removal phase must not run (council 2026-08-12, both peers).
                scan_complete = False
                logger.warning("Failed to hash %s: %s", path, e)

        with self.db.transaction():
            for path in paths:
                if path not in hashes:
                    continue  # hashing failed above; already logged
                try:
                    file_hash = hashes[path]
                    node = parse_node(path.read_text(encoding="utf-8"))
                    disk_ids.add(node.id)

                    if node.id not in indexed:
                        self._index_file(path, file_hash)
                        added += 1
                    elif indexed[node.id] != file_hash:
                        prior = self._prior_row(node.id)  # read BEFORE the delete (#126)
                        self._clear_derived(node.id)
                        self._index_file(path, file_hash, prior)
                        updated += 1
                except Exception as e:
                    # Any failure here also leaves this node out of disk_ids.
                    scan_complete = False
                    logger.warning("Failed to process %s: %s", path, e)

            # Only a COMPLETE scan proves absence. _remove_node here deletes the node row and its
            # vector, so a node dropped on a transient read error loses its vector permanently —
            # nothing re-embeds it — and _remove_node does not clear the checked-pair tables, so
            # the node would come back as new (prior=None) carrying stale verdicts, defeating #126.
            pending_removal = indexed_ids - disk_ids
            if scan_complete:
                for node_id in pending_removal:
                    self._remove_node(node_id)
            elif pending_removal:
                logger.warning(
                    "incremental_update: scan incomplete, deferring removal of %d node(s)",
                    len(pending_removal),
                )

        return added, updated

    def index_single(self, path: Path) -> None:
        """Index or re-index a single file."""
        node = parse_node(path.read_text(encoding="utf-8"))
        file_hash = self.file_store.file_hash(path)  # takes L_mem: must precede the write txn
        with self.db.transaction():
            prior = self._prior_row(node.id)  # read BEFORE the delete (#126)
            # The vector is still valid exactly when the content fingerprint is: title and
            # content are what feed the embedding. Dropping it on an unchanged-content
            # reindex is permanent loss — nothing re-embeds it — and the node would sit
            # behind the watermark with no vector, invisible to the linker and unable to be
            # anyone else's semantic candidate. mark_outdated() (valid_until only) walks
            # exactly this path.
            unchanged = prior is not None and prior["content_fingerprint"] == content_fingerprint(
                node.title, node.content, node.type.value, node.space
            )
            self._clear_derived(node.id, drop_vector=not unchanged)
            self._index_file(path, file_hash, prior)

    def _prior_row(self, node_id: str) -> sqlite3.Row | None:
        """The stored fingerprint + seq, read BEFORE the upsert overwrites the row.

        Only the persisted fingerprint may serve as the baseline — see the comparison in
        _index_file_nodes_only for why the row's live columns must not.
        """
        return self.db.conn.execute(
            "SELECT seq, content_fingerprint FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()

    def _index_file(
        self, path: Path, file_hash: str, prior: sqlite3.Row | None = None
    ) -> None:
        """Index a single markdown file into the database (nodes + edges)."""
        self._index_file_nodes_only(path, file_hash, prior)
        self._index_file_edges(path)

    def _index_file_nodes_only(
        self,
        path: Path,
        file_hash: str,
        prior: sqlite3.Row | None = None,
        prior_fingerprints: dict[str, str | None] | None = None,
    ) -> None:
        """Index node, tags, and FTS from a markdown file (no edges).

        ``prior_fingerprints`` is full_rebuild's own invalidation path (#126): prior=None there
        so every node gets a fresh seq, but a node whose content actually changed (a restore
        from a stale/edited backup) must still drop its cached pair verdicts.
        """
        text = path.read_text(encoding="utf-8")
        node = parse_node(text)
        conn = self.db.conn
        new_fp = content_fingerprint(node.title, node.content, node.type.value, node.space)

        conn.execute(
            """
            INSERT INTO nodes
            (id, type, tier, source, space, space_locked, title, content, created, updated,
             last_accessed, access_count, confidence, importance,
             valid_until, stability, last_review, archived_at, file_path, file_hash,
             content_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                tier = excluded.tier,
                source = excluded.source,
                space = excluded.space,
                space_locked = excluded.space_locked,
                title = excluded.title,
                content = excluded.content,
                created = excluded.created,
                updated = excluded.updated,
                last_accessed = excluded.last_accessed,
                access_count = excluded.access_count,
                confidence = excluded.confidence,
                importance = excluded.importance,
                valid_until = excluded.valid_until,
                stability = excluded.stability,
                last_review = excluded.last_review,
                archived_at = excluded.archived_at,
                file_path = excluded.file_path,
                file_hash = excluded.file_hash,
                content_fingerprint = excluded.content_fingerprint
            """,
            (
                node.id,
                node.type.value,
                node.tier.value,
                node.source,
                node.space,
                int(node.space_locked),
                node.title,
                node.content,
                node.created.isoformat(),
                node.updated.isoformat(),
                node.last_accessed.isoformat(),
                node.access_count,
                node.confidence,
                node.importance,
                node.valid_until.isoformat() if node.valid_until else None,
                node.stability,
                node.last_review.isoformat() if node.last_review else None,
                node.archived_at.isoformat() if node.archived_at else None,
                str(path),
                file_hash,
                new_fp,
            ),
        )

        # Durable monotonic change-sequence (council v2 crit#1): allocate from meta.node_seq_next
        # — never decreases, unlike MAX(seq)+1 which is non-monotonic across INSERT OR REPLACE.
        #
        # #126: only a CONTENT change requeues. A reindex whose only delta is the connection
        # block (an edge write by auto_linker/conflict_detector) is not a content change —
        # requeueing it sent the node back to the end of the queue with nothing to learn, which
        # pinned the backlog at ~the size of the store. Compare against the PERSISTED fingerprint,
        # never against the row's live columns: auto_cluster writes `space` directly into SQLite,
        # so the row can already hold the new value while the fingerprint still reflects the last
        # indexed content — comparing rows would freeze that node out of relinking for good.
        if prior is not None and prior["content_fingerprint"] == new_fp:
            conn.execute("UPDATE nodes SET seq = ? WHERE id = ?", (prior["seq"], node.id))
        else:
            row = conn.execute("SELECT value FROM meta WHERE key = 'node_seq_next'").fetchone()
            next_seq = int(row[0]) if row else 1
            conn.execute("UPDATE nodes SET seq = ? WHERE id = ?", (next_seq, node.id))
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('node_seq_next', ?)",
                (str(next_seq + 1),),
            )
            if prior is not None:
                # An INCREMENTAL reindex of an existing node always invalidates its cached
                # verdicts (the seq only bumped here because the fingerprint changed).
                self._invalidate_checked_pairs(conn, node.id)
            elif prior_fingerprints is not None and prior_fingerprints.get(node.id) is not None \
                    and prior_fingerprints[node.id] != new_fp:
                # full_rebuild path (#126): prior is None so every node lands a fresh seq, but
                # a node whose PERSISTED fingerprint actually changed (restore over an
                # edited/older backup) must still drop its cached pair verdicts, or the old
                # content's link decisions silently carry over. Unchanged nodes are left alone
                # — re-judging an untouched store with the LLM would be a huge pointless cost.
                self._invalidate_checked_pairs(conn, node.id)

        # Tags
        for tag in node.tags:
            conn.execute(
                "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, ?)",
                (node.id, tag),
            )

        # FTS
        tags_str = " ".join(node.tags)
        conn.execute(
            "INSERT INTO nodes_fts (id, title, content, tags) VALUES (?, ?, ?, ?)",
            (node.id, node.title or "", node.content, tags_str),
        )

    def _invalidate_checked_pairs(self, conn: sqlite3.Connection, node_id: str) -> None:
        """Drop cached pair verdicts for a node whose content fingerprint changed (#126).

        The maintenance jobs skip any pair already recorded BEFORE they look at the edge, so a
        fresh `seq` alone changes nothing: the node is re-scanned and every one of its pairs is
        skipped. Doing it here covers every path into the index, including disk edits and sync.

        The fingerprint bundles title/content/type/space, so when it changes we clear all three
        checked tables — auto_link, duplicate AND conflict — mirroring the most comprehensive
        branch of memory_engine.update_node (content/title edit). auto_link/duplicate depend on
        the embedded text; conflict also depends on type/space. This Beta keeps the three as
        SEPARATE tables (schema.sql), unlike upstream's single shared table.
        """
        for table in ("auto_link_checked", "duplicate_checked", "conflict_checked"):
            conn.execute(
                f"DELETE FROM {table} WHERE node_a = ? OR node_b = ?", (node_id, node_id)
            )

    def _index_file_edges(self, path: Path) -> None:
        """Index edges from a markdown file's connections."""
        text = path.read_text(encoding="utf-8")
        node = parse_node(text)
        conn = self.db.conn

        for c in node.connections:
            # Only insert if target node exists (avoids FK violation)
            target_exists = conn.execute(
                "SELECT 1 FROM nodes WHERE id = ?", (c.target,)
            ).fetchone()
            if not target_exists:
                continue

            # Skip if reverse edge already exists (avoid bidirectional duplicates)
            reverse_exists = conn.execute(
                "SELECT 1 FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = ?",
                (c.target, node.id, c.edge.value),
            ).fetchone()
            if reverse_exists:
                continue

            conn.execute(
                """
                INSERT OR REPLACE INTO edges (source_id, target_id, edge_type, weight, created, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (node.id, c.target, c.edge.value, c.weight, node.created.isoformat(), c.reason),
            )

    def _clear_derived(self, node_id: str, *, drop_vector: bool = False) -> None:
        """Clear what this node's own markdown produces, keeping the node row itself (#123).

        This is the REINDEX path. The `nodes` row must survive: `edges.target_id` is
        `REFERENCES nodes(id) ON DELETE CASCADE`, so deleting it — or writing it with
        `INSERT OR REPLACE`, which is a delete underneath — destroys every edge pointing AT
        this node. Those rows are declared in OTHER nodes' markdown files, which a reindex of
        this node never reads and cannot reconstruct.

        Only `source_id` edges are cleared. A row in `edges` belongs to the markdown file of
        its source, and `_index_file_edges` reinserts exactly that set.

        Args:
            drop_vector: delete the `node_vectors` row so the embedding is regenerated. True
                only when the content fingerprint changed — dropping it on an unchanged-content
                reindex is permanent loss, because nothing re-embeds it.
        """
        conn = self.db.conn
        conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
        conn.execute("DELETE FROM edges WHERE source_id = ?", (node_id,))
        conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        if drop_vector:
            try:
                conn.execute("DELETE FROM node_vectors WHERE id = ?", (node_id,))
            except Exception:
                pass

    def _remove_node(self, node_id: str) -> None:
        """Remove a node and everything derived from it — the file is gone from disk.

        The `ON DELETE CASCADE` on `edges` is correct here: an edge pointing at a node that no
        longer exists is a foreign-key violation. For the REINDEX path, where the node survives,
        use `_clear_derived` instead (#123).
        """
        conn = self.db.conn
        conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
        conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)
        )
        conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        # Vector cleanup if table exists
        try:
            conn.execute("DELETE FROM node_vectors WHERE id = ?", (node_id,))
        except Exception:
            pass

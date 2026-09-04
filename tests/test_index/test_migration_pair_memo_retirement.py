"""The dead Pair memo tables and every stored Merge proposal leave the store at startup (#12).

Seam: the store's schema initialisation. `Database.init_schema()` applies `schema.sql`
and then runs the guarded migration steps — the house pattern these assertions drive.

The retired machinery is ADR-0006: a Pair either clears the Auto-merge threshold or
nothing happens, so `duplicate_checked` and `conflict_checked` have no writer left (#11)
and no producer files a Merge proposal any more (#9).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ormah.index.db import _SCHEMA_PATH, Database

DEAD_MEMO_TABLES = ("duplicate_checked", "conflict_checked")

_LEGACY_MEMO_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    node_a TEXT NOT NULL,
    node_b TEXT NOT NULL,
    result TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (node_a, node_b)
)
"""


def _table_exists(db: Database, table: str) -> bool:
    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _legacy_store(db_path) -> None:
    """A store in the pre-#12 shape: both dead memo tables, with rows in them.

    Built by initialising a current store and then re-adding what this change removes,
    which is the only way to get the old shape out of a schema that no longer carries it.
    """
    db = Database(db_path)
    db.init_schema()
    with db.transaction() as conn:
        for table in DEAD_MEMO_TABLES:
            conn.execute(_LEGACY_MEMO_DDL.format(table=table))
            conn.execute(
                f"INSERT INTO {table} (node_a, node_b, result, checked_at) VALUES (?, ?, ?, ?)",
                ("node-a", "node-b", "not_duplicate", datetime.now(timezone.utc).isoformat()),
            )
    db.close()


def _file_proposal(db: Database, proposal_id: str, proposal_type: str, status: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO proposals (id, type, status, source_nodes, proposed_action, "
            "reason, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                proposal_id,
                proposal_type,
                status,
                json.dumps(["node-a", "node-b"]),
                f"a {proposal_type} proposal",
                "test fixture",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def _proposal_ids(db: Database) -> set[str]:
    return {row[0] for row in db.conn.execute("SELECT id FROM proposals").fetchall()}


def test_initialisation_drops_both_dead_memo_tables(tmp_path):
    db_path = tmp_path / "legacy.db"
    _legacy_store(db_path)

    migrated = Database(db_path)
    migrated.init_schema()
    survivors = [t for t in DEAD_MEMO_TABLES if _table_exists(migrated, t)]
    linker_memo_survives = _table_exists(migrated, "auto_link_checked")
    migrated.close()

    assert survivors == []
    # auto_link_checked is upstream code with live readers — it is not part of this change.
    assert linker_memo_survives


def test_initialisation_deletes_every_merge_proposal_and_keeps_the_other_types(tmp_path):
    db_path = tmp_path / "proposals.db"
    _legacy_store(db_path)

    seeded = Database(db_path)
    _file_proposal(seeded, "merge-pending", "merge", "pending")
    _file_proposal(seeded, "merge-approved", "merge", "approved")
    _file_proposal(seeded, "merge-rejected", "merge", "rejected")
    _file_proposal(seeded, "decay-pending", "decay", "pending")
    _file_proposal(seeded, "conflict-resolved", "conflict", "resolved")
    seeded.close()

    migrated = Database(db_path)
    migrated.init_schema()
    remaining = _proposal_ids(migrated)
    migrated.close()

    # Every merge row goes, whatever its status; retiring merge retires nothing else.
    assert remaining == {"decay-pending", "conflict-resolved"}


def test_initialisation_is_a_no_op_the_second_time(tmp_path):
    db_path = tmp_path / "twice.db"
    _legacy_store(db_path)

    first = Database(db_path)
    first.init_schema()
    _file_proposal(first, "decay-pending", "decay", "pending")
    first.close()

    # A restart loop runs this again against an already-migrated store: it must not raise.
    second = Database(db_path)
    second.init_schema()
    second.init_schema()
    survivors = [t for t in DEAD_MEMO_TABLES if _table_exists(second, t)]
    remaining = _proposal_ids(second)
    second.close()

    assert survivors == []
    assert remaining == {"decay-pending"}


def test_the_schema_definition_no_longer_declares_the_dead_memo_tables(tmp_path):
    """The schema applied on its own, without the migration that runs right after it.

    Going through `init_schema()` cannot pin this half: `executescript` would create the
    two tables and the migration would drop them in the same call, so the assertion would
    stay green with the `schema.sql` change reverted.
    """
    conn = sqlite3.connect(tmp_path / "schema_only.db")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    declared = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()

    assert [t for t in DEAD_MEMO_TABLES if t in declared] == []
    # The two memo tables that stay are declared by the same file, so their absence would
    # mean the edit cut too deep rather than that the assertion above found nothing.
    assert {"auto_link_checked", "consolidation_checked"} <= declared


def test_a_fresh_store_initialises_without_the_dead_memo_tables(tmp_path):
    fresh = Database(tmp_path / "fresh.db")
    fresh.init_schema()
    created = [t for t in DEAD_MEMO_TABLES if _table_exists(fresh, t)]
    fresh.close()

    assert created == []

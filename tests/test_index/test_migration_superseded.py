"""Tests for the nodes.superseded_by column migration (#223)."""

from __future__ import annotations


def test_migration_adds_superseded_by_and_leaves_existing_rows_null(tmp_path):
    from ormah.index.db import Database

    db = Database(tmp_path / "legacy.db")
    try:
        with db.transaction() as conn:
            conn.execute(
                "CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, tier TEXT, space TEXT, "
                "title TEXT, content TEXT, created TEXT NOT NULL)"
            )
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "INSERT INTO nodes (id, type, tier, space, title, content, created) "
                "VALUES ('old', 'fact', 'working', NULL, 't', 'c', '2020-01-01')"
            )

        db.init_schema()  # must not raise

        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        assert "superseded_by" in cols
        row = db.conn.execute(
            "SELECT superseded_by FROM nodes WHERE id = 'old'"
        ).fetchone()
        assert row[0] is None
    finally:
        db.close()


def test_migration_is_idempotent(tmp_path):
    """PRAGMA-guarded: running init_schema twice must not raise 'duplicate column'."""
    from ormah.index.db import Database

    db = Database(tmp_path / "twice.db")
    try:
        db.init_schema()
        db.init_schema()
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        assert cols.count("superseded_by") == 1
    finally:
        db.close()

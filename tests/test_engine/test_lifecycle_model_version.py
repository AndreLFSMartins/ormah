"""Integer lifecycle-model version replaces the boolean fsrs_migrated flag (#221)."""

from __future__ import annotations

from datetime import datetime, timezone

from ormah.engine.memory_engine import LIFECYCLE_MODEL_VERSION
from ormah.models.node import CreateNodeRequest, NodeType, Tier


def _version(engine) -> str | None:
    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
    ).fetchone()
    return row["value"] if row else None


def _make_node(engine) -> str:
    """A real node, so the seed has something to act on — an empty table would
    make every assertion below pass vacuously."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="A node the migration will or will not reseed",
        type=NodeType.fact,
        tier=Tier.working,
        title="Migration subject",
    ))
    return node_id


def _stability(engine, node_id: str) -> float:
    return engine.db.conn.execute(
        "SELECT stability FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["stability"]


def test_the_version_constant_is_two():
    """1 = the legacy FSRS seed; 2 = bounded reinforcement."""
    assert LIFECYCLE_MODEL_VERSION == 2


def test_a_fresh_store_ends_at_the_current_version(engine):
    assert _version(engine) == "2"


def test_a_legacy_store_is_backfilled_without_reseeding(engine):
    """AC6: fsrs_migrated='1' means the seed already ran — record it as version 1."""
    node_id = _make_node(engine)
    # Simulate a store migrated by the old boolean flag: drop the new key, restore
    # the legacy one, and set a stability the seed would overwrite if it re-ran.
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('fsrs_migrated', '1')"
    )
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 42.0, access_count = 5 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    engine._migrate_fsrs()

    assert _version(engine) == "2"
    assert _stability(engine, node_id) == 42.0, "the seed re-ran on an already-migrated store"


def test_an_unmigrated_store_still_gets_seeded(engine):
    node_id = _make_node(engine)
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'fsrs_migrated'")
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, access_count = 5 WHERE id = ?", (node_id,)
    )
    # A genuinely pre-FSRS store: no node has ever been seeded or reinforced.
    # Stated explicitly rather than assumed — this is what separates it from the
    # rebuilt-index case below, and the whole seed decision now rests on it.
    engine.db.conn.execute("UPDATE nodes SET last_review = NULL")
    engine.db.conn.commit()

    engine._migrate_fsrs()

    assert _version(engine) == "2"
    assert _stability(engine, node_id) == 10.0, "min(30, access_count * 2) was not applied"


def test_a_corrupt_version_fails_closed_as_migrated(engine):
    """Skipping a seed is inert; running one overwrites stability. Fail closed."""
    engine.db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_model_version', 'banana')"
    )
    engine.db.conn.commit()

    assert engine._lifecycle_model_version() == 1


def test_a_rebuilt_index_does_not_reseed_earned_stability(engine):
    """C3: SQLite is excluded from backups, so a restore arrives with no meta.

    The Markdown still carries stability and last_review, so the store is not a
    pre-FSRS one and must not be reseeded.

    SCOPE, stated so nobody reads more into a green than it carries: this covers
    the EMPTY-meta restore only. It deletes the keys by hand and calls
    _migrate_fsrs directly — it goes through neither full_rebuild nor
    reload_restored_graph. The same-device restore, where meta survives the
    rebuild and _migrate_fsrs is never called, is a pre-existing defect tracked
    outside this issue (see the scope boundary above). This test passing does
    NOT mean restore is safe in general.
    """
    node_id = _make_node(engine)
    now = datetime.now(timezone.utc)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, access_count = 7, last_review = ? WHERE id = ?",
        (now.isoformat(), node_id),
    )
    # Exactly what a fresh-device restore or a deleted index looks like.
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'fsrs_migrated'")
    engine.db.conn.commit()

    engine._migrate_fsrs()

    # Without the last_review guard the seed would write min(30, 7*2) = 14.0.
    assert _stability(engine, node_id) == 1.0
    assert _version(engine) == "2"


def test_the_legacy_flag_is_written_alongside_the_version(engine):
    """I1: a rollback to a binary that only knows fsrs_migrated must not reseed.

    SCOPE, stated so a green is not over-read (council round 3, C2): this proves
    the old binary will not RESEED. It does not prove rollback is safe. The old
    binary still writes stability with the unbounded formula while leaving
    lifecycle_model_version at '2', and on the next upgrade the early return
    trusts that stale marker. Downgrade is unsupported; see the scope note above.
    """
    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'fsrs_migrated'"
    ).fetchone()
    assert row is not None and row["value"] == "1"

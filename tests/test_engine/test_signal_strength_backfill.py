"""The #218 backfill recomputes historical strength exactly, and only once."""

import json

import pytest

from ormah import signal_strength as ss


def _seed(engine, *, source, polarity, evidence, strength=0.85):
    """Insert a signals row with a stale strength.

    whisper_log_id stays NULL: the unique index on
    (whisper_log_id, signal_type, source) is partial on whisper_log_id IS NOT NULL,
    so NULL rows never collide however many are seeded.
    """
    cursor = engine.db.conn.execute(
        "INSERT INTO signals "
        "(whisper_log_id, node_id, signal_type, polarity, strength, source, evidence, created) "
        "VALUES (NULL, 'seed-node', 'seeded', ?, ?, ?, ?, datetime('now'))",
        (polarity, strength, source, json.dumps(evidence) if evidence is not None else None),
    )
    engine.db.conn.commit()
    return cursor.lastrowid


def _rerun(engine):
    """Clear the version stamp so the guarded migration runs again."""
    engine.db.conn.execute(
        "DELETE FROM meta WHERE key = 'signal_strength_ladder_version'"
    )
    engine.db.conn.commit()
    engine._migrate_signal_strength()


def _row(engine, signal_id):
    return engine.db.conn.execute(
        "SELECT strength, polarity, evidence FROM signals WHERE id = ?", (signal_id,)
    ).fetchone()


def test_backfill_recomputes_each_channel_exactly(engine):
    verbatim = _seed(
        engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence={"match": "node_id"}
    )
    overlap = _seed(
        engine,
        source=ss.HEURISTIC_SOURCE,
        polarity=1,
        evidence={"match": "token_overlap", "overlap_ratio": 1.167},
    )
    judged = _seed(
        engine,
        source=ss.LLM_JUDGE_SOURCE,
        polarity=1,
        evidence={"confidence": 0.88, "min_confidence": 0.75},
    )
    implicit = _seed(engine, source="implicit", polarity=1, evidence={"source": "implicit"},
                     strength=1.0)

    _rerun(engine)

    assert _row(engine, verbatim)["strength"] == ss.VERBATIM_NODE_ID
    assert _row(engine, overlap)["strength"] == pytest.approx(ss.token_overlap_strength(1.167))
    assert _row(engine, judged)["strength"] == pytest.approx(ss.judge_strength(0.88, 0.75, 1))
    assert _row(engine, implicit)["strength"] == ss.IMPLICIT


def test_backfill_uses_the_rows_own_min_confidence(engine):
    """Not today's setting — the judge stamped it on the row when it wrote it."""
    lenient = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=1,
        evidence={"confidence": 0.80, "min_confidence": 0.75},
    )
    strict = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=1,
        evidence={"confidence": 0.80, "min_confidence": 0.80},
    )

    _rerun(engine)

    assert _row(engine, lenient)["strength"] > _row(engine, strict)["strength"]


def test_backfill_zeroes_rows_that_assert_nothing(engine):
    uncertain = _seed(
        engine, source=ss.LLM_JUDGE_SOURCE, polarity=0,
        evidence={"confidence": 0.35, "min_confidence": 0.75},
    )

    _rerun(engine)

    assert _row(engine, uncertain)["strength"] == 0.0


def test_backfill_survives_missing_evidence(engine):
    orphan = _seed(engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence=None)

    _rerun(engine)

    assert _row(engine, orphan)["strength"] == ss.UNKNOWN


def test_backfill_leaves_evidence_and_polarity_untouched(engine):
    evidence = {"match": "token_overlap", "overlap_ratio": 1.167}
    signal_id = _seed(engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence=evidence)
    before = _row(engine, signal_id)

    _rerun(engine)

    after = _row(engine, signal_id)
    assert after["evidence"] == before["evidence"]
    assert after["polarity"] == before["polarity"]
    assert after["strength"] != before["strength"]


def test_backfill_is_idempotent(engine):
    signal_id = _seed(
        engine,
        source=ss.HEURISTIC_SOURCE,
        polarity=1,
        evidence={"match": "token_overlap", "overlap_ratio": 1.167},
    )

    _rerun(engine)
    once = _row(engine, signal_id)["strength"]
    _rerun(engine)
    twice = _row(engine, signal_id)["strength"]

    assert once == twice


def test_backfill_does_not_rerun_once_stamped(engine):
    """The version guard, not the recompute, is what makes the second boot free."""
    signal_id = _seed(
        engine, source=ss.HEURISTIC_SOURCE, polarity=1, evidence={"match": "node_id"}
    )
    _rerun(engine)

    engine.db.conn.execute("UPDATE signals SET strength = 0.123 WHERE id = ?", (signal_id,))
    engine.db.conn.commit()
    engine._migrate_signal_strength()

    assert _row(engine, signal_id)["strength"] == 0.123

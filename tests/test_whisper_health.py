import sqlite3
from datetime import datetime, timedelta, timezone

from ormah.engine.whisper_health import compute_whisper_health

NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)
ISO = NOW.isoformat()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE whisper_log "
        "(id INTEGER PRIMARY KEY, was_injected INTEGER, logged_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE affinity "
        "(whisper_log_id INTEGER, signal INTEGER, confirmed_at TEXT)"
    )
    return conn


def _inject(conn, wid, when=ISO, injected=1):
    conn.execute(
        "INSERT INTO whisper_log (id, was_injected, logged_at) VALUES (?, ?, ?)",
        (wid, injected, when),
    )


def _feedback(conn, wid, signal, when=ISO):
    conn.execute(
        "INSERT INTO affinity (whisper_log_id, signal, confirmed_at) VALUES (?, ?, ?)",
        (wid, signal, when),
    )


def test_empty_store_ratios_none():
    out = compute_whisper_health(_db(), NOW)
    for window in ("all_time", "last_7d"):
        assert out[window]["coverage"] is None
        assert out[window]["precision"] is None
        assert out[window]["injected"] == 0
    assert out["all_time"]["unlinked_feedback_rows"] == 0


def test_injection_without_feedback():
    conn = _db()
    _inject(conn, 1)
    _inject(conn, 2)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["injected"] == 2
    assert out["coverage"] == 0.0
    assert out["precision"] is None


def test_mixed_signals_precision():
    conn = _db()
    for wid in (1, 2, 3, 4):
        _inject(conn, wid)
    _feedback(conn, 1, 1)
    _feedback(conn, 2, 1)
    _feedback(conn, 3, 1)
    _feedback(conn, 4, -1)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["precision"] == 0.75
    assert out["coverage"] == 1.0


def test_distinct_guards_against_double_count():
    # In production idx_affinity_node_whisper_log_unique (db.py:234) forbids two
    # affinity rows on one whisper_log_id, so this two-row shape can't occur for
    # real. The minimal schema here omits that index on purpose, to assert the
    # DISTINCT clause is a defensive guard that keeps coverage <= 1.0 regardless.
    conn = _db()
    _inject(conn, 1)
    _feedback(conn, 1, 1)
    _feedback(conn, 1, -1)
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0  # not 2.0


def test_held_back_candidate_feedback_excluded():
    # C1: feedback on a was_injected=0 candidate must NOT inflate coverage.
    conn = _db()
    _inject(conn, 1, injected=1)
    _feedback(conn, 1, 1)
    _inject(conn, 2, injected=0)  # held-back candidate
    _feedback(conn, 2, 1)         # later converted to affinity
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["injected"] == 1
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0  # not 2.0
    assert out["positive"] == 1   # held-back signal excluded from precision too


def test_legacy_null_whisper_log_id_surfaced_not_counted():
    # I1 (council r2): pre-#21 affinity rows carry whisper_log_id = NULL. They are
    # excluded from linked-only coverage/precision but surfaced via
    # unlinked_feedback_rows so the loss is visible, not silent.
    conn = _db()
    _inject(conn, 1)
    _feedback(conn, 1, 1)
    conn.execute(
        "INSERT INTO affinity (whisper_log_id, signal, confirmed_at) "
        "VALUES (NULL, 1, ?)",
        (ISO,),
    )
    out = compute_whisper_health(conn, NOW)["all_time"]
    assert out["coverage"] == 1.0            # linked-only, NULL row ignored
    assert out["positive"] == 1              # NULL row excluded from precision
    assert out["unlinked_feedback_rows"] == 1  # but counted and exposed


def test_last_7d_old_injection_recent_feedback():
    # I1 (r1): recent feedback for an old injection must not push last_7d above 1.0.
    conn = _db()
    old = (NOW - timedelta(days=10)).isoformat()
    _inject(conn, 1, when=old)
    _feedback(conn, 1, 1, when=ISO)  # feedback today
    out = compute_whisper_health(conn, NOW)
    assert out["all_time"]["coverage"] == 1.0
    assert out["last_7d"]["injected"] == 0
    assert out["last_7d"]["feedback_rows"] == 0
    assert out["last_7d"]["coverage"] is None


def test_mixed_confirmed_at_format_still_counted():
    # I2 (r1): confirmed_at in datetime('now') space-format must not be dropped,
    # because the window filters wl.logged_at, never confirmed_at.
    conn = _db()
    _inject(conn, 1, when=ISO)
    _feedback(conn, 1, 1, when="2026-06-24 00:00:00")  # space-format, no TZ
    out = compute_whisper_health(conn, NOW)["last_7d"]
    assert out["feedback_rows"] == 1
    assert out["coverage"] == 1.0


def test_seven_day_cutoff():
    conn = _db()
    old = (NOW - timedelta(days=10)).isoformat()
    _inject(conn, 1, when=old)
    _feedback(conn, 1, 1, when=old)
    out = compute_whisper_health(conn, NOW)
    assert out["all_time"]["injected"] == 1
    assert out["all_time"]["coverage"] == 1.0
    assert out["last_7d"]["injected"] == 0
    assert out["last_7d"]["coverage"] is None
    assert out["last_7d"]["precision"] is None

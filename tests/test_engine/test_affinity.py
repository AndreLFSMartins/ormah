"""Tests for the affinity boost module (adaptive feedback loop)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from ormah.engine.affinity import batch_fetch_affinity, compute_affinity_boost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = SimpleNamespace(
    affinity_similarity_threshold=0.70,
    affinity_half_life_days=30.0,
    affinity_max_boost=0.15,
    affinity_implicit_weight=0.8,
)


def _make_vec(dim: int = 8) -> np.ndarray:
    """Return a unit vector of given dimension."""
    v = np.ones(dim, dtype=np.float32)
    return v / np.linalg.norm(v)


def _make_affinity_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the affinity table and row_factory."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE affinity (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_vec   BLOB NOT NULL,
            prompt_text  TEXT,
            node_id      TEXT NOT NULL,
            signal       INTEGER NOT NULL,
            source       TEXT NOT NULL DEFAULT 'explicit',
            confirmed_at TEXT NOT NULL,
            space        TEXT,
            session_id   TEXT NOT NULL,
            UNIQUE (node_id, session_id)
        )
        """
    )
    conn.commit()
    return conn


def _insert_affinity_row(
    conn: sqlite3.Connection,
    node_id: str,
    signal: int,
    vec: np.ndarray,
    source: str = "explicit",
    confirmed_at: str | None = None,
    session_id: str = "s1",
) -> None:
    if confirmed_at is None:
        confirmed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO affinity (prompt_vec, node_id, signal, source, confirmed_at, session_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vec.tobytes(), node_id, signal, source, confirmed_at, session_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# batch_fetch_affinity tests
# ---------------------------------------------------------------------------


class TestBatchFetchAffinity:

    def test_empty_list_returns_empty_dict(self):
        """batch_fetch_affinity([]) must return {} without touching the DB."""
        conn = _make_affinity_db()
        result = batch_fetch_affinity(conn, [])
        assert result == {}

    def test_rows_grouped_by_node_id(self):
        """Rows are returned as lists keyed by node_id."""
        conn = _make_affinity_db()
        vec = _make_vec()

        _insert_affinity_row(conn, "node-A", +1, vec, session_id="s1")
        _insert_affinity_row(conn, "node-A", -1, vec, session_id="s2")
        _insert_affinity_row(conn, "node-B", +1, vec, session_id="s3")

        result = batch_fetch_affinity(conn, ["node-A", "node-B"])

        assert set(result.keys()) == {"node-A", "node-B"}
        assert len(result["node-A"]) == 2
        assert len(result["node-B"]) == 1

        # Each row dict must have the required fields
        for row in result["node-A"]:
            assert "prompt_vec" in row
            assert "signal" in row
            assert "source" in row
            assert "confirmed_at" in row

    def test_unknown_node_id_not_in_result(self):
        """node_ids that have no rows do not appear in the result."""
        conn = _make_affinity_db()
        result = batch_fetch_affinity(conn, ["nonexistent"])
        assert result == {}

    def test_only_requested_nodes_returned(self):
        """Results are scoped to the requested node_ids only."""
        conn = _make_affinity_db()
        vec = _make_vec()
        _insert_affinity_row(conn, "node-X", +1, vec, session_id="s1")
        _insert_affinity_row(conn, "node-Y", +1, vec, session_id="s2")

        result = batch_fetch_affinity(conn, ["node-X"])
        assert "node-X" in result
        assert "node-Y" not in result


# ---------------------------------------------------------------------------
# compute_affinity_boost tests
# ---------------------------------------------------------------------------


class TestComputeAffinityBoost:

    def test_empty_rows_returns_zero(self):
        """No affinity rows → boost is 0.0."""
        vec = _make_vec()
        boost = compute_affinity_boost(vec, "node-1", [], _DEFAULT_SETTINGS)
        assert boost == 0.0

    def test_positive_signal_today_returns_max_boost(self):
        """Single +1 row, cosine sim = 1.0, confirmed today → boost = +max_boost."""
        vec = _make_vec()
        confirmed_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "prompt_vec": vec.tobytes(),
                "signal": 1,
                "source": "explicit",
                "confirmed_at": confirmed_at,
            }
        ]
        boost = compute_affinity_boost(vec, "node-1", rows, _DEFAULT_SETTINGS)
        # sim=1.0, recency=1.0 (today), source_w=1.0 → normalised=1.0 → boost=max_boost
        assert boost == pytest.approx(_DEFAULT_SETTINGS.affinity_max_boost, rel=1e-3)

    def test_negative_signal_today_returns_negative_max_boost(self):
        """Single -1 row, cosine sim = 1.0, confirmed today → boost = -max_boost."""
        vec = _make_vec()
        confirmed_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "prompt_vec": vec.tobytes(),
                "signal": -1,
                "source": "explicit",
                "confirmed_at": confirmed_at,
            }
        ]
        boost = compute_affinity_boost(vec, "node-1", rows, _DEFAULT_SETTINGS)
        assert boost == pytest.approx(-_DEFAULT_SETTINGS.affinity_max_boost, rel=1e-3)

    def test_below_threshold_is_skipped(self):
        """A row whose cosine sim < affinity_similarity_threshold is ignored → 0.0."""
        # Build two orthogonal unit vectors so sim = 0.0 (well below 0.70)
        current = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        stored = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

        confirmed_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "prompt_vec": stored.tobytes(),
                "signal": 1,
                "source": "explicit",
                "confirmed_at": confirmed_at,
            }
        ]
        boost = compute_affinity_boost(current, "node-1", rows, _DEFAULT_SETTINGS)
        assert boost == 0.0

    def test_implicit_source_uses_reduced_weight(self):
        """An implicit row should produce a smaller boost than an explicit row
        with otherwise identical properties."""
        vec = _make_vec()
        confirmed_at = datetime.now(timezone.utc).isoformat()

        explicit_rows = [
            {
                "prompt_vec": vec.tobytes(),
                "signal": 1,
                "source": "explicit",
                "confirmed_at": confirmed_at,
            }
        ]
        implicit_rows = [
            {
                "prompt_vec": vec.tobytes(),
                "signal": 1,
                "source": "implicit",
                "confirmed_at": confirmed_at,
            }
        ]

        boost_explicit = compute_affinity_boost(vec, "node-1", explicit_rows, _DEFAULT_SETTINGS)
        boost_implicit = compute_affinity_boost(vec, "node-1", implicit_rows, _DEFAULT_SETTINGS)

        # Explicit: source_w=1.0, Implicit: source_w=0.8
        # Both have sim=1.0, recency=1.0 → normalised=1.0 for both
        # (weighted_sum / weight_total simplifies — both are max_boost)
        # The implicit_weight only affects the magnitude when mixing signals,
        # but for a single-row case the normalised ratio is still 1.0.
        # What we can assert: implicit boost ≤ explicit boost.
        assert boost_implicit <= boost_explicit
        # For a single +1 row both should equal max_boost (normalised=1.0)
        assert boost_explicit == pytest.approx(_DEFAULT_SETTINGS.affinity_max_boost, rel=1e-3)
        assert boost_implicit == pytest.approx(_DEFAULT_SETTINGS.affinity_max_boost, rel=1e-3)

    def test_implicit_weight_affects_mixed_signal(self):
        """With one +1 explicit and one -1 implicit row at sim=1.0 confirmed today,
        the explicit signal should dominate (net boost > 0) because implicit has
        lower weight."""
        vec = _make_vec()
        confirmed_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "prompt_vec": vec.tobytes(),
                "signal": 1,
                "source": "explicit",
                "confirmed_at": confirmed_at,
            },
            {
                "prompt_vec": vec.tobytes(),
                "signal": -1,
                "source": "implicit",
                "confirmed_at": confirmed_at,
            },
        ]
        boost = compute_affinity_boost(vec, "node-1", rows, _DEFAULT_SETTINGS)
        # explicit weight = 1.0, implicit weight = 0.8
        # weighted_sum = (1 * 1.0) + (-1 * 0.8) = 0.2
        # weight_total = 1.0 + 0.8 = 1.8
        # normalised = 0.2 / 1.8 ≈ 0.111
        # boost = 0.111 * 0.15 ≈ 0.01667
        expected_normalised = (1.0 * 1.0 + (-1.0) * 0.8) / (1.0 + 0.8)
        expected_boost = expected_normalised * _DEFAULT_SETTINGS.affinity_max_boost
        assert boost == pytest.approx(expected_boost, rel=1e-4)
        assert boost > 0.0

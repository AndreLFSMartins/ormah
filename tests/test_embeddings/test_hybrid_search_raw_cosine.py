"""Unit tests for the raw_cosine absolute-signal contract in HybridSearch.

The whisper injection gate reads `raw_cosine` as an absolute relevance signal
and, when it is absent, falls back to the blended score. An FTS-only hit has
no vector measurement, so it must omit the key entirely rather than emit a 0.0
sentinel the gate would misread as "measured, irrelevant" — which would
silence exact keyword matches whenever the cross-encoder is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from ormah.config import Settings
from ormah.embeddings.hybrid_search import HybridSearch


def _make_node(node_id: str, title: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": node_id,
        "title": title,
        "content": f"Content about {title}",
        "type": "fact",
        "tier": "working",
        "space": "test",
        "confidence": 1.0,
        "created": now,
        "last_accessed": now,
        "access_count": 0,
        "valid_until": None,
    }


def _make_hybrid(vec_hits: list[dict], fts_hits: list[dict], nodes: dict):
    mock_db = MagicMock()
    mock_db.conn = MagicMock()

    settings = Settings()
    settings.similarity_threshold = 0.3
    settings.length_penalty_threshold = 0
    settings.recency_boost = 0.0
    settings.access_boost = 0.0
    settings.min_result_score = 0.0

    hs = HybridSearch(mock_db, settings)
    mock_encoder = MagicMock()
    mock_encoder.encode_query.return_value = [0.1] * 768
    hs.encoder = mock_encoder
    mock_vec_store = MagicMock()
    mock_vec_store.search.return_value = vec_hits
    hs.vec_store = mock_vec_store
    hs.graph.fts_search = MagicMock(return_value=fts_hits)
    hs.graph.get_nodes_batch = MagicMock(return_value=nodes)
    hs.graph.get_tags_batch = MagicMock(return_value={})
    mock_db.conn.execute.return_value.fetchall.return_value = [
        {"id": nid, "len": 200} for nid in nodes
    ]
    return hs


class TestRawCosineContract:
    def test_fts_only_hit_omits_raw_cosine(self):
        """A node found only via FTS (no vector hit) must carry no raw_cosine."""
        hs = _make_hybrid(
            vec_hits=[],
            fts_hits=[{"id": "fts1", "score": 9.0}],
            nodes={"fts1": _make_node("fts1", "Exact keyword match")},
        )

        results = hs.search("exact keyword", limit=10)

        assert len(results) == 1
        assert results[0]["node"]["id"] == "fts1"
        assert "raw_cosine" not in results[0], (
            "FTS-only hit must omit raw_cosine, not emit a 0.0 sentinel the "
            "gate would misread as a real measurement"
        )

    def test_vector_hit_carries_raw_cosine(self):
        """A node with a genuine vector measurement keeps its raw_cosine."""
        hs = _make_hybrid(
            vec_hits=[{"id": "vec1", "similarity": 0.66}],
            fts_hits=[{"id": "vec1", "score": 5.0}],
            nodes={"vec1": _make_node("vec1", "Semantic match")},
        )

        results = hs.search("semantic match topic", limit=10)

        assert len(results) == 1
        assert results[0]["raw_cosine"] == 0.66

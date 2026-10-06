"""Unit tests for HybridSearch title boost score capping.

Verifies that title_match_boost doesn't push scores above 1.0, which would
break downstream CE blend assumptions and cause noise leaks through the
injection gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


from ormah.config import Settings
from ormah.embeddings.hybrid_search import HybridSearch


def _make_node(node_id: str, title: str, tier: str = "working", confidence: float = 1.0) -> dict:
    """Build a minimal node dict matching GraphIndex.get_nodes_batch output."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": node_id,
        "title": title,
        "content": f"Content about {title}",
        "type": "fact",
        "tier": tier,
        "space": "test",
        "confidence": confidence,
        "created": now,
        "last_accessed": now,
        "access_count": 0,
        "valid_until": None,
    }


class TestTitleBoostScoreCap:
    """Verify that base_score and final_score are capped at 1.0."""

    def test_high_fts_and_vector_scores_with_title_match_capped_at_one(self):
        """When FTS + vector + title boost push base_score > 1.0, cap it."""
        # Setup: mock DB, settings, and HybridSearch internals
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        settings = Settings()
        settings.title_match_boost = 2.0  # default boost
        settings.fts_weight = 1.0
        settings.vector_weight = 1.0
        settings.rrf_k = 60
        settings.similarity_blend_weight = 0.4
        settings.similarity_threshold = 0.3
        settings.fts_only_dampening = 1.0
        settings.rrf_min_spread_ratio = 0.1
        settings.length_penalty_threshold = 0
        settings.tier_boost_core = 0.0
        settings.tier_boost_working = 0.0
        settings.tier_boost_archival = 0.0
        settings.recency_boost = 0.0
        settings.access_boost = 0.0
        settings.min_result_score = 0.0

        hs = HybridSearch(mock_db, settings)

        # Mock the encoder
        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = [0.1] * 768
        hs.encoder = mock_encoder

        # Mock vector store to return high similarity
        mock_vec_store = MagicMock()
        mock_vec_store.search.return_value = [
            {"id": "node1", "similarity": 0.85},
        ]
        hs.vec_store = mock_vec_store

        # Mock FTS search to return high FTS score
        hs.graph.fts_search = MagicMock(return_value=[
            {"id": "node1", "score": 10.5},  # High FTS score
        ])

        # Node with title that matches query keyword "memory"
        node1 = _make_node("node1", "Three-tier memory system", tier="working", confidence=1.0)
        hs.graph.get_nodes_batch = MagicMock(return_value={"node1": node1})
        hs.graph.get_tags_batch = MagicMock(return_value={})

        # Mock the length query
        mock_db.conn.execute.return_value.fetchall.return_value = [
            {"id": "node1", "len": 200},
        ]

        # Execute search with query containing "memory" (matches title)
        results = hs.search("memory management in C", limit=10)

        # Verify results
        assert len(results) == 1
        assert results[0]["node"]["id"] == "node1"

        # The key assertion: score must be <= 1.0
        # Without the cap, title boost would push this above 1.0
        assert results[0]["score"] <= 1.0, (
            f"Score {results[0]['score']} exceeds 1.0 — title boost not capped properly"
        )

    def test_multiple_keyword_overlap_high_boost_still_capped(self):
        """Multiple query tokens matching title → high title_bonus, but still capped."""
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        settings = Settings()
        settings.title_match_boost = 2.0
        settings.fts_weight = 1.0
        settings.vector_weight = 1.0
        settings.rrf_k = 60
        settings.similarity_blend_weight = 0.4
        settings.similarity_threshold = 0.3
        settings.fts_only_dampening = 1.0
        settings.rrf_min_spread_ratio = 0.1
        settings.length_penalty_threshold = 0
        settings.tier_boost_core = 0.0
        settings.tier_boost_working = 0.0
        settings.tier_boost_archival = 0.0
        settings.recency_boost = 0.0
        settings.access_boost = 0.0
        settings.min_result_score = 0.0

        hs = HybridSearch(mock_db, settings)

        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = [0.1] * 768
        hs.encoder = mock_encoder

        mock_vec_store = MagicMock()
        mock_vec_store.search.return_value = [
            {"id": "node2", "similarity": 0.9},
        ]
        hs.vec_store = mock_vec_store

        hs.graph.fts_search = MagicMock(return_value=[
            {"id": "node2", "score": 12.0},
        ])

        # Query: "graph edge node" — all three words match title
        node2 = _make_node("node2", "Graph edge node relationships", tier="core", confidence=1.0)
        hs.graph.get_nodes_batch = MagicMock(return_value={"node2": node2})
        hs.graph.get_tags_batch = MagicMock(return_value={})

        mock_db.conn.execute.return_value.fetchall.return_value = [
            {"id": "node2", "len": 150},
        ]

        results = hs.search("graph edge node", limit=10)

        assert len(results) == 1
        assert results[0]["score"] <= 1.0, (
            f"Multi-keyword overlap score {results[0]['score']} exceeds 1.0"
        )

    def test_final_score_cap_after_tier_and_boosts(self):
        """Even with tier boost + recency + access, final_score capped at 1.0."""
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        settings = Settings()
        settings.title_match_boost = 2.0
        settings.fts_weight = 1.0
        settings.vector_weight = 1.0
        settings.rrf_k = 60
        settings.similarity_blend_weight = 0.4
        settings.similarity_threshold = 0.3
        settings.fts_only_dampening = 1.0
        settings.rrf_min_spread_ratio = 0.1
        settings.length_penalty_threshold = 0
        settings.tier_boost_core = 0.3  # 30% boost
        settings.tier_boost_working = 0.0
        settings.tier_boost_archival = 0.0
        settings.recency_boost = 0.2  # 20% boost
        settings.recency_half_life_days = 7
        settings.access_boost = 0.15  # 15% boost
        settings.min_result_score = 0.0

        hs = HybridSearch(mock_db, settings)

        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = [0.1] * 768
        hs.encoder = mock_encoder

        mock_vec_store = MagicMock()
        mock_vec_store.search.return_value = [
            {"id": "node3", "similarity": 0.88},
        ]
        hs.vec_store = mock_vec_store

        hs.graph.fts_search = MagicMock(return_value=[
            {"id": "node3", "score": 11.0},
        ])

        # Core tier node with title match
        node3 = _make_node("node3", "Memory system architecture", tier="core", confidence=1.0)
        node3["access_count"] = 10  # Will add access boost
        hs.graph.get_nodes_batch = MagicMock(return_value={"node3": node3})
        hs.graph.get_tags_batch = MagicMock(return_value={})

        mock_db.conn.execute.return_value.fetchall.return_value = [
            {"id": "node3", "len": 180},
        ]

        results = hs.search("memory system", limit=10)

        assert len(results) == 1
        # With all boosts + core tier + title match, this would easily exceed 1.0
        # The second cap (after final_score computation) should clamp it
        assert results[0]["score"] <= 1.0, (
            f"Final score {results[0]['score']} exceeds 1.0 despite tier/recency/access boosts"
        )

    def test_question_query_bypasses_title_boost(self):
        """Question queries disable title boost, so no cap needed (but shouldn't break)."""
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        settings = Settings()
        settings.title_match_boost = 2.0
        settings.question_fts_weight_scale = 0.5
        settings.question_vector_weight_scale = 1.5
        settings.question_similarity_blend_weight = 0.7
        settings.fts_weight = 1.0
        settings.vector_weight = 1.0
        settings.rrf_k = 60
        settings.similarity_blend_weight = 0.4
        settings.similarity_threshold = 0.3
        settings.fts_only_dampening = 1.0
        settings.rrf_min_spread_ratio = 0.1
        settings.length_penalty_threshold = 0
        settings.tier_boost_core = 0.0
        settings.tier_boost_working = 0.0
        settings.tier_boost_archival = 0.0
        settings.recency_boost = 0.0
        settings.access_boost = 0.0
        settings.min_result_score = 0.0

        hs = HybridSearch(mock_db, settings)

        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = [0.1] * 768
        hs.encoder = mock_encoder

        mock_vec_store = MagicMock()
        mock_vec_store.search.return_value = [
            {"id": "node4", "similarity": 0.82},
        ]
        hs.vec_store = mock_vec_store

        hs.graph.fts_search = MagicMock(return_value=[
            {"id": "node4", "score": 8.5},
        ])

        node4 = _make_node("node4", "What is memory decay", tier="working", confidence=1.0)
        hs.graph.get_nodes_batch = MagicMock(return_value={"node4": node4})
        hs.graph.get_tags_batch = MagicMock(return_value={})

        mock_db.conn.execute.return_value.fetchall.return_value = [
            {"id": "node4", "len": 220},
        ]

        # Question query — title boost disabled
        results = hs.search("what is memory decay?", limit=10)

        assert len(results) == 1
        # No title boost applied, but cap should still be in place (harmless)
        assert results[0]["score"] <= 1.0

    def test_no_title_match_no_boost_score_remains_normal(self):
        """When title doesn't match, no boost applied, score stays in range."""
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        settings = Settings()
        settings.title_match_boost = 2.0
        settings.fts_weight = 1.0
        settings.vector_weight = 1.0
        settings.rrf_k = 60
        settings.similarity_blend_weight = 0.4
        settings.similarity_threshold = 0.3
        settings.fts_only_dampening = 1.0
        settings.rrf_min_spread_ratio = 0.1
        settings.length_penalty_threshold = 0
        settings.tier_boost_core = 0.0
        settings.tier_boost_working = 0.0
        settings.tier_boost_archival = 0.0
        settings.recency_boost = 0.0
        settings.access_boost = 0.0
        settings.min_result_score = 0.0

        hs = HybridSearch(mock_db, settings)

        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = [0.1] * 768
        hs.encoder = mock_encoder

        mock_vec_store = MagicMock()
        mock_vec_store.search.return_value = [
            {"id": "node5", "similarity": 0.75},
        ]
        hs.vec_store = mock_vec_store

        hs.graph.fts_search = MagicMock(return_value=[
            {"id": "node5", "score": 7.0},
        ])

        # Title has no overlap with query
        node5 = _make_node("node5", "Database optimization techniques", tier="working", confidence=1.0)
        hs.graph.get_nodes_batch = MagicMock(return_value={"node5": node5})
        hs.graph.get_tags_batch = MagicMock(return_value={})

        mock_db.conn.execute.return_value.fetchall.return_value = [
            {"id": "node5", "len": 300},
        ]

        # Query has no overlap with title
        results = hs.search("authentication flow with JWT", limit=10)

        assert len(results) == 1
        # No title boost, so score stays in normal range
        assert 0.0 <= results[0]["score"] <= 1.0

"""Environment-independent Settings overrides shared by the eval harnesses.

A bare ``Settings()`` absorbs the developer's ``ORMAH_*`` environment and
``~/.config/ormah/.env`` values, so retrieval knobs would silently vary from
machine to machine and baselines would not be comparable. These dicts pin
every retrieval-relevant knob to its production default (the values in
``src/ormah/config.py``), so the eval measures the *shipped* configuration
rather than whatever the local box happens to be tuned to.
"""
from __future__ import annotations

# Retrieval-relevant knobs pinned to their production defaults (config.py).
# Shared by both the recall and whisper eval harnesses so each one measures the
# shipped configuration regardless of local env/.env overrides.
RETRIEVAL_EVAL_SETTINGS_OVERRIDES: dict = {
    # LLM extraction is never exercised by retrieval evals.
    "llm_provider": "none",
    # Embeddings
    "embedding_provider": "local",
    "embedding_model": "BAAI/bge-base-en-v1.5",
    "embedding_dim": 768,
    # Hybrid search fusion
    "fts_weight": 0.4,
    "vector_weight": 0.6,
    "similarity_threshold": 0.4,
    "rrf_k": 60,
    "fts_only_dampening": 0.5,
    "min_result_score": 0.1,
    "rrf_min_spread_ratio": 0.05,
    # Question-query adjustments
    "question_fts_weight_scale": 0.3,
    "question_vector_weight_scale": 1.5,
    "question_similarity_blend_weight": 0.85,
    "similarity_blend_weight": 0.5,
    # Title / length scoring
    "title_match_boost": 2.0,
    "length_penalty_threshold": 300,
    # Scoring signals
    "recency_boost": 0.05,
    "recency_half_life_days": 7.0,
    "access_boost": 0.05,
    "tier_boost_core": 0.1,
    "tier_boost_working": 0.0,
    "tier_boost_archival": -0.1,
    # Space prioritization
    "space_boost_global": 1.0,
    "space_boost_other": 0.6,
    # Absolute gates
    "recall_min_relevance_score": 0.35,
    "whisper_injection_gate": 0.45,
    # Recall eval never whispers: no reranker, no involuntary storage, no
    # Claude-in-the-loop maintenance. The whisper eval re-enables the reranker.
    "whisper_reranker_enabled": False,
    "whisper_out_enabled": False,
    "claude_maintenance_enabled": False,
}

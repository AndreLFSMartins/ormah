# Whisper Precision Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve whisper noise rejection from 71% to ~80%+ by fixing the three root causes identified in WHISPER_PRECISION_FINDINGS.md: sigmoid blend masking CE suppression, unchecked exploration slot, and FTS title boost inflation.

**Architecture:** Three surgical changes to the whisper scoring pipeline. (1) Replace sigmoid blend with linear rescale so CE negative scores actually suppress noise instead of collapsing to ~0. (2) Gate the exploration slot on CE score — only explore candidates the CE didn't strongly reject. (3) Cap embedding scores at 1.0 before CE blending so FTS title boost can't push noise past the injection gate.

**Tech Stack:** Python, pytest, fastembed (TextCrossEncoder), numpy

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/ormah/embeddings/reranker.py` | Modify | Replace sigmoid with linear rescale blend |
| `src/ormah/config.py` | Modify | Update default blend_alpha (0.4→0.6), injection_gate (0.55→0.50) |
| `src/ormah/engine/context_builder.py` | Modify | CE-gate the exploration slot |
| `src/ormah/embeddings/hybrid_search.py` | Modify | Cap base_score at 1.0 after title boost |
| `tests/test_embeddings/test_reranker.py` | Modify | Update tests for linear rescale math |
| `tests/test_engine/test_whisper_context.py` | Modify | Add exploration CE-gate test + update integration tests for linear rescale |
| `tests/test_embeddings/test_hybrid_search_title_cap.py` | Create | Test title boost score cap |

**Important cross-cutting concern:** The `cross_encoder_score` field is only added by `rerank()` in reranker.py. Pipeline stages downstream (affinity boost, exploration slot) see this field on candidates that went through CE reranking. Tests must ensure candidates include this field when testing CE-dependent behavior.

---

## Chunk 1: Linear Rescale Blend

### Task 1: Update reranker blend formula

**Files:**
- Modify: `src/ormah/embeddings/reranker.py:63-76`
- Modify: `tests/test_embeddings/test_reranker.py`

**Context:** The current sigmoid blend maps all negative CE scores to ~0, making CE one-directional (can boost, can't suppress). Linear rescale preserves the full CE signal range: `rescaled = clamp((ce - ce_min) / (ce_max - ce_min), 0, 1)` with ce_min=-12, ce_max=+6. Then `blended = alpha * rescaled + (1-alpha) * emb`.

- [ ] **Step 1: Write failing tests for linear rescale math**

Replace the `_sigmoid` helper and update `TestBlendingMath` in `tests/test_embeddings/test_reranker.py`:

```python
# Replace the _sigmoid helper at line 31-32:
def _linear_rescale(ce: float, ce_min: float = -12.0, ce_max: float = 6.0) -> float:
    return max(0.0, min(1.0, (ce - ce_min) / (ce_max - ce_min)))


# In TestBlendingMath:

class TestBlendingMath:
    """Verify the linear-rescale blend formula: alpha * rescale(ce) + (1-alpha) * emb."""

    def test_positive_ce_boosts_score(self):
        """High CE score should push blended above embedding score."""
        candidates = [_candidate("a", "Relevant", 0.6)]
        mock = MagicMock()
        mock.rerank.return_value = [6.0]  # rescale = 1.0

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank("query", candidates, "model", min_score=0.0)

        expected = 0.6 * _linear_rescale(6.0) + 0.4 * 0.6  # 0.6*1.0 + 0.4*0.6 = 0.84
        assert len(results) == 1
        assert results[0]["score"] == pytest.approx(expected, abs=1e-6)
        assert results[0]["score"] > 0.6  # boosted above embedding

    def test_negative_ce_suppresses_score(self):
        """Very negative CE should suppress blended well below embedding score."""
        candidates = [_candidate("a", "Noise match", 0.75)]
        mock = MagicMock()
        mock.rerank.return_value = [-10.0]  # rescale = (-10 - -12) / (6 - -12) = 2/18 = 0.111

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank("query", candidates, "model", min_score=0.0)

        # 0.6 * 0.111 + 0.4 * 0.75 = 0.067 + 0.30 = 0.367
        expected = 0.6 * _linear_rescale(-10.0) + 0.4 * 0.75
        assert len(results) == 1
        assert results[0]["score"] == pytest.approx(expected, abs=1e-4)
        assert results[0]["score"] < 0.45  # suppressed below gate

    def test_zero_ce_is_midrange(self):
        """CE=0 → rescale = 12/18 = 0.667."""
        candidates = [_candidate("a", "Neutral", 0.7)]
        mock = MagicMock()
        mock.rerank.return_value = [0.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank("query", candidates, "model", min_score=0.0)

        expected = 0.6 * _linear_rescale(0.0) + 0.4 * 0.7
        assert results[0]["score"] == pytest.approx(expected, abs=1e-6)

    def test_custom_alpha(self):
        """Custom blend_alpha should change the weighting."""
        candidates = [_candidate("a", "Test", 0.5)]
        mock = MagicMock()
        mock.rerank.return_value = [2.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank(
                "query", candidates, "model", min_score=0.0, blend_alpha=0.8
            )

        expected = 0.8 * _linear_rescale(2.0) + 0.2 * 0.5
        assert results[0]["score"] == pytest.approx(expected, abs=1e-6)

    def test_alpha_zero_ignores_ce(self):
        """blend_alpha=0 means CE has no effect, score = embedding score."""
        candidates = [_candidate("a", "Test", 0.65)]
        mock = MagicMock()
        mock.rerank.return_value = [100.0]  # huge CE, but alpha=0

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank(
                "query", candidates, "model", min_score=0.0, blend_alpha=0.0
            )

        assert results[0]["score"] == pytest.approx(0.65, abs=1e-6)

    def test_alpha_one_ignores_embedding(self):
        """blend_alpha=1 means only CE matters."""
        candidates = [_candidate("a", "Test", 0.9)]
        mock = MagicMock()
        mock.rerank.return_value = [0.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank(
                "query", candidates, "model", min_score=0.0, blend_alpha=1.0
            )

        # rescale(0) = 12/18 = 0.667, ignore embedding
        assert results[0]["score"] == pytest.approx(_linear_rescale(0.0), abs=1e-6)

    def test_ce_below_floor_clamps_to_zero(self):
        """CE below -12 should clamp rescaled to 0."""
        candidates = [_candidate("a", "A", 0.5)]
        mock = MagicMock()
        mock.rerank.return_value = [-15.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank("q", candidates, "model", min_score=0.0)

        expected = 0.6 * 0.0 + 0.4 * 0.5  # 0.20
        assert results[0]["score"] == pytest.approx(expected, abs=1e-6)

    def test_ce_above_ceiling_clamps_to_one(self):
        """CE above +6 should clamp rescaled to 1."""
        candidates = [_candidate("a", "A", 0.5)]
        mock = MagicMock()
        mock.rerank.return_value = [10.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock):
            results = rerank("q", candidates, "model", min_score=0.0)

        expected = 0.6 * 1.0 + 0.4 * 0.5  # 0.80
        assert results[0]["score"] == pytest.approx(expected, abs=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embeddings/test_reranker.py::TestBlendingMath -v`
Expected: FAIL — current code uses sigmoid, not linear rescale

- [ ] **Step 3: Implement linear rescale in reranker.py**

Replace the blend logic in `src/ormah/embeddings/reranker.py`:

```python
"""Cross-encoder reranker for whisper context precision.

Uses linear-rescale blended scoring to combine cross-encoder relevance with
the original embedding score. Unlike sigmoid blending, linear rescale preserves
the CE model's ability to suppress noise (negative CE scores pull blended score
down proportionally).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}

# CE score range for linear rescale normalization.
# Derived from empirical distribution: MS MARCO MiniLM scores range
# from ~-12 (completely irrelevant) to ~+6 (perfect keyword match).
_CE_MIN = -12.0
_CE_MAX = 6.0


def _linear_rescale(ce_score: float) -> float:
    """Rescale raw CE score to [0, 1] using clamped linear interpolation."""
    return max(0.0, min(1.0, (ce_score - _CE_MIN) / (_CE_MAX - _CE_MIN)))


def rerank(
    query: str,
    candidates: list[dict],
    model_name: str,
    min_score: float,
    blend_alpha: float = 0.6,
    max_doc_chars: int = 512,
) -> list[dict]:
    """Rerank search results using a cross-encoder with linear-rescale blended scoring.

    Final score = alpha * linear_rescale(ce_score) + (1-alpha) * embedding_score

    Linear rescale maps the CE score range [-12, +6] to [0, 1], preserving the
    model's ability to both boost relevant results and suppress irrelevant ones.

    Args:
        query: The user's prompt.
        candidates: List of search result dicts ({"node": {...}, "score": float}).
        model_name: CrossEncoder model name.
        min_score: Drop results below this blended score.
        blend_alpha: Weight for cross-encoder component (0-1). Default 0.6.
        max_doc_chars: Max characters of content to feed to cross-encoder.

    Returns:
        Filtered and reordered candidates with updated scores.
    """
    if not candidates:
        return []

    model = _get_model(model_name)

    # Build doc strings for each candidate
    docs = []
    for r in candidates:
        node = r["node"]
        doc = node.get("title") or ""
        content = node.get("content", "").strip()
        if content and content != doc:
            doc = f"{doc}: {content[:max_doc_chars]}" if doc else content[:max_doc_chars]
        docs.append(doc)

    # Score all docs in one batch
    ce_scores = list(model.rerank(query, docs))

    # Linear-rescale blend with original embedding scores, filter, sort
    reranked = []
    for r, ce_score in zip(candidates, ce_scores):
        ce_rescaled = _linear_rescale(float(ce_score))
        emb_score = r.get("score", 0.0)
        blended = blend_alpha * ce_rescaled + (1 - blend_alpha) * emb_score

        if blended >= min_score:
            reranked.append({
                **r,
                "score": blended,
                "cross_encoder_score": float(ce_score),
                "embedding_score": emb_score,
            })

    reranked.sort(key=lambda r: r["score"], reverse=True)
    return reranked


def _get_model(model_name: str):
    if model_name in _model_cache:
        return _model_cache[model_name]
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    model = TextCrossEncoder(model_name)
    _model_cache[model_name] = model
    return model
```

- [ ] **Step 4: Update remaining test classes for new math**

Update `TestFiltering`, `TestSorting`, `TestBlendedScoreBoundary`, `TestRealWorldScenarios`, and `TestEdgeCases` to use `_linear_rescale` instead of `_sigmoid` in expected-value calculations. Key changes:

In `TestFiltering.test_min_score_filters_low_blended`:
```python
# a: blended = 0.6*rescale(3)+0.4*0.8 = 0.6*0.833+0.32 = 0.820
# b: blended = 0.6*rescale(-8)+0.4*0.15 = 0.6*0.222+0.06 = 0.193
```

In `TestSorting.test_ce_reorders_results`:
```python
# b: 0.6*rescale(8)+0.4*0.4 = 0.6*1.0+0.16 = 0.76
# a: 0.6*rescale(-2)+0.4*0.9 = 0.6*0.556+0.36 = 0.693
```

In `TestEdgeCases.test_extreme_positive_ce`:
```python
expected = 0.6 * 1.0 + 0.4 * 0.5  # rescale(50) clamps to 1.0
```

In `TestEdgeCases.test_extreme_negative_ce`:
```python
expected = 0.6 * 0.0 + 0.4 * 0.5  # rescale(-50) clamps to 0.0
```

In `TestRealWorldScenarios.test_semantic_match_survives_negative_ce`:
```python
# emb=0.714, CE=-10.7 → rescale=(-10.7+12)/18 = 0.072
# blended = 0.6*0.072 + 0.4*0.714 = 0.043 + 0.286 = 0.329
# This now correctly scores LOW — CE suppresses noise.
# Update min_score to 0.0 and assert score < 0.40 (below gate)
```

**Important:** Some "real world" tests assumed sigmoid would preserve semantic matches with negative CE. With linear rescale, CE=-10.7 correctly suppresses. Update these tests to reflect the new behavior — CE suppression is the fix, not a regression.

In `TestRealWorldScenarios.test_keyword_match_still_boosted`:
```python
# keyword: 0.6*rescale(6)+0.4*0.65 = 0.6*1.0+0.26 = 0.86
# semantic: 0.6*rescale(-8)+0.4*0.72 = 0.6*0.222+0.288 = 0.421
# Both still present at min_score=0.3, keyword ranks first
```

In `TestRealWorldScenarios.test_mixed_relevant_irrelevant_batch`:
```python
# a: 0.6*rescale(5)+0.4*0.78 = 0.6*0.944+0.312 = 0.879  (relevant)
# d: 0.6*rescale(1.5)+0.4*0.68 = 0.6*0.75+0.272 = 0.722  (related)
# b: 0.6*rescale(-9)+0.4*0.71 = 0.6*0.167+0.284 = 0.384  (borderline)
# c: 0.6*rescale(-12)+0.4*0.25 = 0.6*0.0+0.10 = 0.100    (filtered)
```

In `TestBlendedScoreBoundary.test_exactly_at_threshold_passes`:
```python
# Need blended = exactly 0.5 with alpha=0.6
# 0.6 * rescale(ce) + 0.4 * emb = 0.5
# If emb=0.5: 0.6 * rescale(ce) + 0.2 = 0.5 → rescale(ce) = 0.5 → ce = -3.0
candidates = [_candidate("a", "A", 0.5)]
mock.rerank.return_value = [-3.0]
```

In `TestOutputFields.test_missing_embedding_score_defaults_zero`:
```python
# Update expected value: alpha=0.6 now
expected = 0.6 * _linear_rescale(1.0) + 0.4 * 0.0
```

Note: The default `blend_alpha` in `rerank()` changes from 0.4 to 0.6. Tests that use explicit `blend_alpha=` are unaffected; tests relying on the default need their expected values recalculated with alpha=0.6.

- [ ] **Step 5: Run all reranker tests to verify they pass**

Run: `uv run pytest tests/test_embeddings/test_reranker.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/ormah/embeddings/reranker.py tests/test_embeddings/test_reranker.py
git commit -m "feat(whisper): replace sigmoid blend with linear rescale in reranker

Linear rescale maps CE scores [-12, +6] to [0, 1], preserving the
cross-encoder's ability to suppress noise. Sigmoid collapsed all
negative CE to ~0, making the blend one-directional (could boost
but not suppress). Alpha changed from 0.4 to 0.6 to give CE more
weight now that its full range is utilized."
```

---

### Task 2: Update config defaults

**Files:**
- Modify: `src/ormah/config.py:150-154,168-169`

- [ ] **Step 1: Update config defaults**

In `src/ormah/config.py`, change:

```python
# Line 150: update comment
# Whisper reranking (cross-encoder with linear-rescale blended scoring)

# Line 154: blend_alpha 0.4 → 0.6
whisper_reranker_blend_alpha: float = 0.6

# Line 169: injection gate 0.55 → 0.50
whisper_injection_gate: float = 0.50
```

- [ ] **Step 2: Update whisper context integration tests for linear rescale**

The following tests in `tests/test_engine/test_whisper_context.py` use sigmoid math in their comments and assertions. Update them for linear rescale:

**`TestWhisperReranker` class (line 334):**
- Update class docstring: "sigmoid-blended" → "linear-rescale blended"
- `test_reranker_blends_and_preserves_relevant`: CE scores [0.3, 0.9, 0.95, -0.5] with emb [0.8, 0.7, 0.6, 0.5]. With linear rescale (alpha=0.4 as passed explicitly): rescale(0.3)=0.683, rescale(0.9)=0.717, rescale(0.95)=0.719, rescale(-0.5)=0.639. All still have decent blended scores → all 4 preserved. Test assertion unchanged.
- `test_reranker_filters_low_blended_scores`: CE [-10.0] → rescale=0.111. emb=0.2. blended=0.4*0.111+0.6*0.2=0.044+0.12=0.164. Still below 0.15 → still filtered. Test assertion unchanged.
- `test_reranker_min_score_on_blended`: CE [0.8, 0.1, 0.05] → rescale=[0.711, 0.672, 0.669]. With alpha=0.4: node-0=0.4*0.711+0.6*0.8=0.764, node-1=0.4*0.672+0.6*0.7=0.689, node-2=0.4*0.669+0.6*0.6=0.628. At min_score=0.7: only node-0 passes. Update assertion: node-1 is now also filtered.

**`TestWhisperRerankerBlendIntegration` class (line 693):**
- `test_unanimously_negative_ce_suppresses_results`: CE [-10.7, -11.4, -8.2] → rescale=[0.072, 0.033, 0.211]. With alpha=0.4 (default): blended=[0.457, 0.455, 0.449]. These are above 0.40 floor but **below 0.55 gate** → still suppressed. With new gate=0.50, they're still below → result="" unchanged.
- `test_blend_alpha_passed_through`: CE=-5.0 → rescale=0.389. With alpha=0.4: 0.4*0.389+0.6*0.3=0.336. With alpha=0.9: 0.9*0.389+0.1*0.3=0.380. Both above 0.15 min_score. **Test needs updating**: change min_score threshold or CE value so alpha difference still creates a pass/fail split. Use CE=-10.0 (rescale=0.111): alpha=0.4 → 0.4*0.111+0.6*0.3=0.224 (passes 0.15), alpha=0.9 → 0.9*0.111+0.1*0.3=0.130 (fails 0.15).

Update the comments in these tests to show linear rescale math instead of sigmoid math. Only change assertions where the math actually produces different pass/fail results.

- [ ] **Step 3: Run existing whisper context tests to check for breakage**

Run: `uv run pytest tests/test_engine/test_whisper_context.py -v`
Expected: PASS after the updates above

- [ ] **Step 4: Commit**

```bash
git add src/ormah/config.py tests/test_engine/test_whisper_context.py
git commit -m "feat(whisper): tune blend_alpha=0.6, injection_gate=0.50

Complements linear rescale: alpha=0.6 gives CE 60% weight (up from 40%)
now that negative scores carry signal. Gate lowered from 0.55 to 0.50
because linear rescale produces lower blended scores for useful results
with moderately negative CE."
```

---

## Chunk 2: CE-Gated Exploration Slot

### Task 3: Gate exploration on CE score

**Files:**
- Modify: `src/ormah/engine/context_builder.py:604-643`
- Modify: `tests/test_engine/test_whisper_context.py`

**Context:** The exploration slot is the #1 noise source (20/26 failures). It injects one gated-out candidate per query to collect affinity signal, but fires on nearly every query because 1100+ memories means something always scores above 0.40. The fix: only explore candidates where the CE didn't strongly reject them. If `cross_encoder_score < -8`, the CE is confident this is irrelevant — don't explore it.

- [ ] **Step 1: Write failing test for CE-gated exploration**

Add to `tests/test_engine/test_whisper_context.py`:

**Key insight:** The `cross_encoder_score` field is added by `rerank()` in reranker.py. In the whisper pipeline, the reranker runs before the affinity boost and exploration slot. So candidates in `pre_gate_candidates` already have `cross_encoder_score` set. To test the exploration CE gate, we mock the reranker to return candidates with CE scores already populated, which is what happens in the real pipeline.

```python
class TestExplorationCEGate:
    """Exploration slot should skip candidates the CE strongly rejected."""

    def test_exploration_skips_strongly_rejected_by_ce(self, mock_graph):
        """Candidate with CE < -8 should not be explored even with no affinity signal.

        Pipeline flow: search → reranker (adds cross_encoder_score) → affinity
        boost → gate → exploration. We mock the reranker to return pre-scored
        candidates, then let the pipeline proceed naturally.
        """
        mock_engine = MagicMock()
        mock_engine.settings = _make_settings_mock(
            whisper_exploration_enabled=True,
            affinity_similarity_threshold=0.70,
            whisper_reranker_min_score=0.0,
        )
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            _make_node_dict("pass-1", "Relevant fact"),
            _make_node_dict("noise-1", "Noise fact"),
        ]
        # search returns raw results (no CE scores yet)
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.75, "source": "hybrid"},
            {"node": nodes[1], "score": 0.60, "source": "hybrid"},
        ]

        # Mock the reranker to return blended scores WITH cross_encoder_score.
        # pass-1: CE=+2.0 → high blended (passes gate)
        # noise-1: CE=-10.0 → low blended (gated out, but above 0.40 floor)
        mock_ce = MagicMock()
        mock_ce.rerank.return_value = [2.0, -10.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock_ce), \
             patch("ormah.engine.context_builder.ContextBuilder._get_classifier", return_value=None):
            result = builder.build_whisper_context(
                prompt="what is kubernetes",
                injection_gate=0.50,
                reranker_enabled=True,
                reranker_min_score=0.40,
            )

        # noise-1 should NOT appear — CE rejected it (score < -8)
        assert "Noise fact" not in result
        assert "Relevant fact" in result

    def test_exploration_allows_borderline_ce(self, mock_graph):
        """Candidate with CE > -8 should still be eligible for exploration."""
        mock_engine = MagicMock()
        mock_engine.settings = _make_settings_mock(
            whisper_exploration_enabled=True,
            affinity_similarity_threshold=0.70,
            whisper_reranker_min_score=0.0,
        )
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            _make_node_dict("pass-1", "Relevant fact"),
            _make_node_dict("maybe-1", "Maybe useful"),
        ]
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.75, "source": "hybrid"},
            {"node": nodes[1], "score": 0.60, "source": "hybrid"},
        ]

        # pass-1: CE=+2.0 → passes gate
        # maybe-1: CE=-5.0 → gated out but above -8 threshold (explorable)
        mock_ce = MagicMock()
        mock_ce.rerank.return_value = [2.0, -5.0]

        with patch("ormah.embeddings.reranker._get_model", return_value=mock_ce), \
             patch("ormah.engine.context_builder.ContextBuilder._get_classifier", return_value=None), \
             patch("ormah.engine.affinity.batch_fetch_affinity", return_value={"maybe-1": []}):
            result = builder.build_whisper_context(
                prompt="how does fastapi routing work",
                injection_gate=0.50,
                reranker_enabled=True,
                reranker_min_score=0.40,
            )

        # maybe-1 SHOULD appear via exploration — CE didn't strongly reject
        assert "Maybe useful" in result

    def test_exploration_when_no_ce_score_proceeds_normally(self, mock_graph):
        """When reranker is disabled, candidates have no cross_encoder_score.
        Exploration should proceed as before (no CE gate applied)."""
        mock_engine = MagicMock()
        mock_engine.settings = _make_settings_mock(
            whisper_exploration_enabled=True,
            affinity_similarity_threshold=0.70,
            whisper_reranker_min_score=0.40,
        )
        builder = ContextBuilder(mock_graph, engine=mock_engine)

        nodes = [
            _make_node_dict("pass-1", "Relevant fact"),
            _make_node_dict("explore-1", "Explore me"),
        ]
        # No reranker → no cross_encoder_score on candidates
        mock_engine.recall_search_structured.return_value = [
            {"node": nodes[0], "score": 0.60, "source": "hybrid"},
            {"node": nodes[1], "score": 0.42, "source": "hybrid"},
        ]

        with patch("ormah.engine.context_builder.ContextBuilder._get_classifier", return_value=None), \
             patch("ormah.engine.affinity.batch_fetch_affinity", return_value={"explore-1": []}):
            result = builder.build_whisper_context(
                prompt="some query",
                injection_gate=0.50,
                reranker_enabled=False,  # no CE
                reranker_min_score=0.40,
            )

        # explore-1 should still appear — no CE score means no CE gate
        assert "Explore me" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine/test_whisper_context.py::TestExplorationCEGate -v`
Expected: FAIL — current exploration doesn't check CE score

- [ ] **Step 3: Add CE gate to exploration slot**

In `src/ormah/engine/context_builder.py`, modify the exploration slot (lines 604-643). Add a CE score check inside the candidate loop:

```python
        # Exploration slot: inject one unconfirmed gated-out candidate to
        # surface false negatives and collect affinity signal for them.
        # CE gate: skip candidates the cross-encoder strongly rejected
        # (ce < -8 means "definitely not relevant") to prevent noise injection.
        if (not has_temporal
                and getattr(self.engine.settings, "whisper_exploration_enabled", True)
                and prompt_vec is not None
                and pre_gate_candidates):
            try:
                from ormah.engine.affinity import batch_fetch_affinity

                injected_ids = {r["node"]["id"] for r in search_results}
                # Gated-out candidates that cleared the 0.40 floor but not the gate
                gated_out = [
                    r for r in pre_gate_candidates
                    if r["node"]["id"] not in injected_ids
                ]
                if gated_out:
                    explore_node_ids = [r["node"]["id"] for r in gated_out]
                    affinity_map = batch_fetch_affinity(self.graph.conn, explore_node_ids)
                    explore_threshold = getattr(
                        self.engine.settings, "affinity_similarity_threshold", 0.70
                    )
                    for candidate in sorted(gated_out, key=lambda r: r["score"], reverse=True):
                        # CE gate: don't explore candidates the CE strongly rejected
                        ce_score = candidate.get("cross_encoder_score")
                        if ce_score is not None and ce_score < -8.0:
                            continue
                        nid = candidate["node"]["id"]
                        rows = affinity_map.get(nid, [])
                        # Only explore nodes with no existing affinity signal for similar prompts
                        has_signal = False
                        for arow in rows:
                            row_vec = np.frombuffer(arow["prompt_vec"], dtype=np.float32)
                            row_norm = float(np.linalg.norm(row_vec))
                            prompt_norm = float(np.linalg.norm(prompt_vec))
                            if row_norm > 0 and prompt_norm > 0:
                                sim = float(np.dot(prompt_vec, row_vec) / (prompt_norm * row_norm))
                                if sim >= explore_threshold:
                                    has_signal = True
                                    break
                        if not has_signal:
                            search_results.append(candidate)
                            break  # one exploration slot only
            except Exception as e:
                logger.warning("Exploration slot failed: %s", e)
```

The only change is adding these two lines after `for candidate in sorted(...)`:
```python
                        ce_score = candidate.get("cross_encoder_score")
                        if ce_score is not None and ce_score < -8.0:
                            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine/test_whisper_context.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/context_builder.py tests/test_engine/test_whisper_context.py
git commit -m "feat(whisper): CE-gate exploration slot to prevent noise injection

Skip exploration candidates where cross_encoder_score < -8.
These are queries the CE confidently identified as irrelevant.
This was the #1 noise source (20/26 failures) — the exploration
slot was injecting CE-rejected candidates on nearly every query."
```

---

## Chunk 3: Cap FTS Title Boost Inflation

### Task 4: Cap base_score at 1.0 after title boost

**Files:**
- Modify: `src/ormah/embeddings/hybrid_search.py:241-250`
- Create: `tests/test_embeddings/test_hybrid_search_title_cap.py`

**Context:** FTS title_match_boost (2.0x) pushes embedding scores past 1.0 for ormah-adjacent keywords like "memory", "graph", "edge". These inflated scores survive the injection gate even after CE blending. The fix: cap base_score at 1.0 after the title boost is applied, before the score enters CE blending.

- [ ] **Step 1: Write failing test for title boost cap**

Create `tests/test_embeddings/test_hybrid_search_title_cap.py`:

**Context:** `HybridSearch` uses `self.vec_store` (not `_vec_store`), `self.graph.fts_search()` for FTS, `self.vec_store.search()` which returns `list[dict]` with `{"id", "similarity"}` keys, and `self.graph.get_nodes_batch()` + `self.graph.get_tags_batch()` for node loading. The scoring loop at lines 213-293 iterates `(node_id, base_score)` pairs from RRF-fused results.

```python
"""Test that title_match_boost cannot push base_score above 1.0."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def test_title_boost_capped_at_one():
    """base_score with title boost applied should never exceed 1.0.

    Regression test: 'memory management in C' was getting emb=1.185
    because title_match_boost inflated scores past 1.0, bypassing the
    injection gate after CE blending.
    """
    from ormah.config import Settings

    settings = Settings(
        title_match_boost=2.0,
        embedding_provider="local",
        embedding_model="BAAI/bge-base-en-v1.5",
        embedding_dim=768,
        memory_dir="/tmp/ormah-test-title-cap",
    )

    from ormah.embeddings.hybrid_search import HybridSearch

    mock_db = MagicMock()
    mock_db.conn = MagicMock()

    node = {
        "id": "mem-1",
        "title": "Three-tier memory system",
        "content": "Core, working, archival tiers",
        "type": "fact",
        "tier": "core",
        "space": "ormah",
        "importance": 0.8,
        "confidence": 1.0,
        "valid_until": None,
        "source": "agent",
        "access_count": 5,
        "last_accessed": "2026-01-01T00:00:00Z",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }

    with patch("ormah.embeddings.hybrid_search.get_encoder") as mock_enc, \
         patch("ormah.embeddings.hybrid_search.VectorStore") as mock_vs_cls:
        mock_encoder = MagicMock()
        mock_encoder.encode_query.return_value = np.zeros(768, dtype=np.float32)
        mock_enc.return_value = mock_encoder

        mock_vs = MagicMock()
        # vec_store.search returns list[dict] with {"id", "similarity"}
        mock_vs.search.return_value = [{"id": "mem-1", "similarity": 0.85}]
        mock_vs_cls.return_value = mock_vs

        hs = HybridSearch(mock_db, settings)

        # Mock graph methods used by search
        # fts_search returns list[dict] with {"id", "score"}
        hs.graph = MagicMock()
        hs.graph.fts_search.return_value = [{"id": "mem-1", "score": 10.0}]
        hs.graph.get_nodes_batch.return_value = {"mem-1": node}
        hs.graph.get_tags_batch.return_value = {}

        # Mock content length query (for length penalty check)
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: {"id": "mem-1", "len": 30}[k]
        mock_db.conn.execute.return_value.fetchall.return_value = [mock_row]

        results = hs.search("memory management in C", limit=5)

    assert len(results) >= 1, "Expected at least one result"
    for r in results:
        assert r["score"] <= 1.0, (
            f"Score {r['score']:.3f} exceeds 1.0 — title_match_boost cap missing"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embeddings/test_hybrid_search_title_cap.py -v`
Expected: FAIL — score exceeds 1.0 due to uncapped title boost

Note: This test mocks the actual `HybridSearch` internals (`graph.fts_search`, `vec_store.search`, `graph.get_nodes_batch`). If mock setup needs minor adjustments during implementation (e.g., the content length query), adapt accordingly — the key assertion remains: no result score should exceed 1.0.

- [ ] **Step 3: Add score cap in hybrid_search.py**

In `src/ormah/embeddings/hybrid_search.py`, add two caps:

**Cap 1:** After title boost (line 250), cap `base_score` before it enters multiplicative factors:

```python
                if overlap > 0:
                    title_bonus = title_match_boost * (overlap / max(len(query_tokens), 1))
                    base_score *= (1.0 + title_bonus)

            # Cap base_score at 1.0 — title boost and RRF fusion can push
            # scores above 1.0, which breaks the CE blend assumption that
            # embedding scores are in [0, 1].
            base_score = min(base_score, 1.0)
```

**Cap 2:** After `final_score` computation (line 291), cap the output score. Even with `base_score` capped, tier boost (1.1x for core), recency boost, and access boost can still push past 1.0:

```python
            final_score = adjusted_score * tier_factor + r_boost + a_boost
            final_score = min(final_score, 1.0)  # CE blend assumes scores in [0, 1]
```

Add `base_score = min(base_score, 1.0)` after line 250, and `final_score = min(final_score, 1.0)` after line 291.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_embeddings/test_hybrid_search_title_cap.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/ormah/embeddings/hybrid_search.py tests/test_embeddings/test_hybrid_search_title_cap.py
git commit -m "fix(search): cap base_score at 1.0 after title boost

FTS title_match_boost (2.0x) was pushing embedding scores past 1.0
for ormah-adjacent keywords (memory, graph, edge). These inflated
scores survived the injection gate even after CE blending, causing
3/26 noise failures. Capping at 1.0 ensures scores stay in the
expected [0, 1] range for downstream blend math."
```

---

## Chunk 4: Validation

### Task 5: Run eval suite and verify improvement

**Files:**
- Read: `scripts/eval_whisper.py`

- [ ] **Step 1: Restart server with new config**

```bash
ormah server stop && ormah server start -d
```

Wait 5 seconds for startup.

- [ ] **Step 2: Run the whisper eval suite**

```bash
uv run python scripts/eval_whisper.py
```

Expected: Noise rejection improves from 71% (64/90) toward 80%+ (72+/90). Key improvements:
- 20 exploration-slot noise cases should mostly resolve (CE gate blocks them)
- 3 FTS title boost cases ("memory management", "graph theory", "edge computing") should resolve (score cap)
- Useful recall (identity, technical, conversational) should remain stable

- [ ] **Step 3: Review any regressions**

If any previously-passing useful cases regressed:
- Check if the lower gate (0.50 vs 0.55) compensates for the linear rescale producing lower blended scores
- If a useful case now scores between 0.45-0.50, consider adjusting the gate or alpha

- [ ] **Step 4: Update WHISPER_PRECISION_FINDINGS.md with results**

Add a new section documenting the fix results, before/after comparison.

- [ ] **Step 5: Final commit**

```bash
git add WHISPER_PRECISION_FINDINGS.md
git commit -m "docs: update whisper precision findings with fix results"
```

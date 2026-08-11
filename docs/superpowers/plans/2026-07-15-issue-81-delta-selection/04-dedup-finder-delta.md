# Task 4: Delta-selection in `_find_merge_candidates`

Read `00-overview.md` first. Work in `/Users/andre/Documents/GitHub/Tools/ormah-81` on branch `fix/81-delta-selection`. Depends on Task 1. Settings were added in Task 2 (`duplicate_check_max_nodes_per_run` already exists in config.py).

**Files:**
- Modify: `src/ormah/background/duplicate_merger.py:135-237` (`_find_merge_candidates`)
- Test: `tests/test_background/test_duplicate_merger.py` (extend)

Same contract as Task 2 — keyword-only `delta: bool = False`: default keeps TODAY's `ORDER BY RANDOM()` selection byte-for-byte and the plain-list return (agent path untouched); `delta=True` (background run only) selects seeds `seq > duplicate_check_watermark ORDER BY seq ASC LIMIT max_seeds` and returns `(candidates, drained_seeds)`. Dedup has no scope stamp (no space gate here). Dedup-specific prefilters kept intact in BOTH modes: user-node exclusion, `auto_link_checked` skip, embedding sim ≥ 0.25, same-type, composite score ≥ `_COMPOSITE_THRESHOLD`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_duplicate_merger.py` (it already imports `json`, `patch`, `CreateNodeRequest`, `NodeType`, and defines `_LLM_PATCH`):

```python
# --- #81 delta-selection ---

def _make_fact(engine, title, content):
    """Create a node without auto-linking; return (id, seq)."""
    original = engine.settings.auto_link_similarity_threshold
    engine.settings.auto_link_similarity_threshold = 999.0
    try:
        node_id, _ = engine.remember(
            CreateNodeRequest(content=content, type=NodeType.fact, title=title, tags=["test"]),
            agent_id="test",
        )
    finally:
        engine.settings.auto_link_similarity_threshold = original
    seq = engine.db.conn.execute("SELECT seq FROM nodes WHERE id = ?", (node_id,)).fetchone()["seq"]
    return node_id, seq


def test_dedup_finder_skips_seeds_at_or_below_watermark(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, set_watermark

    _make_fact(engine, "Python is dynamic", "Python is a dynamically typed language.")
    _make_fact(engine, "Python typing", "Python is a dynamically typed programming language.")

    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, DUPLICATE_WATERMARK_KEY, max_seq)
    candidates, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    assert candidates == [] and seeds == []
    # legacy mode (agent path) ignores the watermark entirely
    legacy = _find_merge_candidates(engine, limit=100)
    assert isinstance(legacy, list) and len(legacy) >= 1


def test_dedup_new_seed_pairs_with_old_neighbor(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, set_watermark

    old_id, old_seq = _make_fact(engine, "Server port", "The ormah server listens on port 8787.")
    set_watermark(engine, DUPLICATE_WATERMARK_KEY, old_seq)

    new_id, _ = _make_fact(engine, "Ormah port", "The ormah server runs on port 8787.")

    candidates, _ = _find_merge_candidates(engine, limit=100, delta=True)
    pair_ids = {(c["node_a"]["id"], c["node_b"]["id"]) for c in candidates}
    assert any(old_id in p and new_id in p for p in pair_ids)


def test_empty_vector_index_does_not_drain_dedup_seeds(engine):
    """Fail-closed (overview invariant): seed with text but no persisted
    vector must not drain (empty/backfilling node_vectors window)."""
    from ormah.background.duplicate_merger import _find_merge_candidates

    node_id, seq = _make_fact(engine, "Vectorless note", "A note whose vector is missing.")
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")

    _, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    assert (node_id, seq) not in seeds


def test_dedup_finder_delta_reports_drained_in_seq_order(engine):
    from ormah.background.duplicate_merger import _find_merge_candidates

    made = [_make_fact(engine, f"Note {i}", f"Unrelated singleton note number {i}.")
            for i in range(3)]
    _, seeds = _find_merge_candidates(engine, limit=100, delta=True)
    seed_ids = [s[0] for s in seeds]
    for node_id, _seq in made:
        assert node_id in seed_ids  # zero-candidate seeds still drained
    assert [s[1] for s in seeds] == sorted(s[1] for s in seeds)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v -k "watermark or old_neighbor or drained"`
Expected: FAIL — `TypeError: _find_merge_candidates() got an unexpected keyword argument 'delta'` (and the watermark test finds candidates because selection is still `ORDER BY RANDOM()` over everything)

- [ ] **Step 3: Rewrite the finder's selection**

In `src/ormah/background/duplicate_merger.py`, mirror Task 2 exactly, with the dedup key and no scope stamp. Signature and fetch:

```python
def _find_merge_candidates(
    engine,
    limit: int = 8,
    *,
    max_seeds: int | None = None,
    delta: bool = False,
):
    """Find node pairs that might be duplicates.

    ``delta=False`` (default — agent path): today's ``ORDER BY RANDOM()``
    selection, unchanged; returns a candidate list.

    ``delta=True`` (background run only, #81): seeds are nodes with ``seq``
    above the ``duplicate_check_watermark``, oldest-first, bounded by
    *max_seeds* (default: ``duplicate_check_max_nodes_per_run``). Vector
    neighbors are NOT age-filtered. Returns ``(candidates, drained_seeds)``;
    candidates carry ``seed_seq``. Only ``run_duplicate_detection`` advances
    the watermark. ``limit`` stays pair-denominated in both modes.
    """
    drained_seeds: list[tuple[str, int]] = []
    try:
        from ormah.embeddings.encoder import get_encoder
        from ormah.embeddings.vector_store import VectorStore, stored_or_encoded

        settings = engine.settings
        encoder = get_encoder(settings)
        vec_store = VectorStore(engine.db)
        user_node_id = getattr(engine, "user_node_id", None)

        if delta:
            from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

            if max_seeds is None:
                max_seeds = settings.duplicate_check_max_nodes_per_run
            watermark = get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY)
            nodes = engine.db.conn.execute(
                "SELECT id, content, title, type, seq FROM nodes "
                "WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                (watermark, max_seeds),
            ).fetchall()
        else:
            # Legacy selection — byte-for-byte today's query (agent path).
            nodes = engine.db.conn.execute(
                "SELECT id, content, title, type, seq FROM nodes ORDER BY RANDOM()"
            ).fetchall()
        ...
```

Bookkeeping identical to Task 2: user-node/empty-text `continue`s append to `drained_seeds` first; the candidate dict gains `"seed_seq": node["seq"]`; pair-limit breaks exclude the current seed; after the inner loop completes, append `(node["id"], node["seq"])`; `delta=True` return shape `(candidates, drained_seeds)`, exception path `([], []) if delta else []`. FAIL-CLOSED vectorless rule identical to Task 2 — placed IMMEDIATELY AFTER the empty-text check and BEFORE `stored_or_encoded`/`vec_store.search`, at the SEED level: `if delta and vec_store.get(node["id"]) is None: continue` WITHOUT draining the seed (mirrors upstream@4f66abc auto_linker.py:344-354). No prefilter removed or reordered.

- [ ] **Step 4: Run the whole file**

Run: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v`
Expected: all pass (pre-existing tests exercise `run_duplicate_detection`, untouched until Task 5)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/duplicate_merger.py tests/test_background/test_duplicate_merger.py
git commit -m "feat(background): delta-select duplicate seeds by seq watermark (#81)"
```

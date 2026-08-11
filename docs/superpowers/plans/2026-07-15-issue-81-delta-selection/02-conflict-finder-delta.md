# Task 2: Delta-selection in `_find_conflict_candidates`

Read `00-overview.md` first. Work in `/Users/andre/Documents/GitHub/Tools/ormah-81` on branch `fix/81-delta-selection`. Depends on Task 1 (`ormah.background.watermark`).

**Files:**
- Modify: `src/ormah/config.py` (~line 133, right after `auto_link_max_nodes_per_run`)
- Modify: `src/ormah/background/conflict_detector.py:104-131` (`_find_conflict_candidates` selection)
- Test: `tests/test_background/test_conflict_detector.py` (extend)

Contract (overview invariant "delta is opt-in"): new keyword-only `delta: bool = False`.

- `delta=False` (default): TODAY's selection byte-for-byte (`ORDER BY RANDOM()` full fetch, same filters), returns a plain candidate list. The agent path (`memory_engine.py:1678`, positional `limit`) hits this and its behavior does not change — with the upstream default `llm_provider="none"` the runs never advance a cursor, and random selection is what keeps agent-driven deployments progressing.
- `delta=True` (only the background run passes it): seeds = `seq > watermark ORDER BY seq ASC LIMIT max_seeds` (default from `conflict_check_max_nodes_per_run`); vector neighbors stay age-unfiltered; each candidate carries `seed_seq`; returns `(candidates, drained_seeds)` with `drained_seeds = [(id, seq), ...]` ascending, containing only seeds whose neighbor loop completed. A scope-stamp mismatch (see below) treats the watermark as 0.

`limit` stays pair-denominated in both modes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_conflict_detector.py` (reuse its existing imports and helpers — it already has `_LLM_PATCH`, node-creation helpers, and the `engine` fixture):

```python
# --- #81 delta-selection ---

def _make_belief(engine, title, content):
    """Create a belief-type node without auto-linking; return (id, seq)."""
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


def test_delta_finder_skips_seeds_at_or_below_watermark(engine):
    from ormah.background.conflict_detector import _find_conflict_candidates
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, set_watermark

    _, seq_a = _make_belief(engine, "Coffee is healthy", "Coffee improves focus and health.")
    _make_belief(engine, "Coffee is unhealthy", "Coffee harms sleep and health.")

    # Watermark past ALL nodes -> no seeds -> no candidates
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, CONFLICT_WATERMARK_KEY, max_seq)
    candidates, seeds = _find_conflict_candidates(engine, limit=100, delta=True)
    assert candidates == [] and seeds == []

    # Watermark below the pair -> pair found again
    set_watermark(engine, CONFLICT_WATERMARK_KEY, seq_a - 1)
    candidates, _ = _find_conflict_candidates(engine, limit=100, delta=True)
    assert len(candidates) >= 1


def test_legacy_mode_ignores_watermark(engine):
    """Default call (agent path) keeps today's selection: nodes below the
    watermark are still reachable and the return shape is a plain list."""
    from ormah.background.conflict_detector import _find_conflict_candidates
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, set_watermark

    _make_belief(engine, "Milk is good", "Milk strengthens bones at any age.")
    _make_belief(engine, "Milk is bad", "Milk weakens bones at any age.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, CONFLICT_WATERMARK_KEY, max_seq)

    candidates = _find_conflict_candidates(engine, limit=100)  # no delta kwarg
    assert isinstance(candidates, list)
    assert len(candidates) >= 1


def test_new_seed_pairs_with_old_neighbor(engine):
    """Neighbors are age-unfiltered: an OLD node below the watermark is still
    reachable as the neighbor of a NEW seed."""
    from ormah.background.conflict_detector import _find_conflict_candidates
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, set_watermark

    old_id, old_seq = _make_belief(engine, "Tabs are best", "The project uses tabs for indentation.")
    set_watermark(engine, CONFLICT_WATERMARK_KEY, old_seq)  # old node is below the cursor

    new_id, _ = _make_belief(engine, "Spaces are best", "The project uses spaces for indentation.")

    candidates, _ = _find_conflict_candidates(engine, limit=100, delta=True)
    pair_ids = {(c["node_a"]["id"], c["node_b"]["id"]) for c in candidates}
    assert any(old_id in p and new_id in p for p in pair_ids)


def test_finder_respects_max_seeds_and_seq_order(engine):
    from ormah.background.conflict_detector import _find_conflict_candidates

    ids = [_make_belief(engine, f"Fact {i}", f"The sky color observation number {i} is blue.")
           for i in range(3)]
    candidates, seeds = _find_conflict_candidates(engine, limit=100, max_seeds=2, delta=True)
    # Only the 2 lowest-seq nodes were seeds, in ascending order
    assert [s[0] for s in seeds] == [ids[0][0], ids[1][0]]
    assert [s[1] for s in seeds] == sorted(s[1] for s in seeds)
    for c in candidates:
        assert c["seed_seq"] in {ids[0][1], ids[1][1]}


def test_finder_never_advances_watermark(engine):
    """Agent path calls the finder directly; the cursor must not move."""
    from ormah.background.conflict_detector import _find_conflict_candidates
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

    _make_belief(engine, "Bikes are green", "Cycling is an eco-friendly transport choice.")
    _find_conflict_candidates(engine, limit=8)              # legacy mode
    _find_conflict_candidates(engine, limit=8, delta=True)  # delta mode
    assert get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY) == 0


def test_empty_vector_index_does_not_advance_conflict_selection(engine):
    """Fail-closed (overview invariant): a seed with text but NO persisted
    vector must not drain — mirrors test_empty_vector_index_does_not_advance_watermark
    in test_auto_linker.py."""
    from ormah.background.conflict_detector import _find_conflict_candidates

    node_id, seq = _make_belief(engine, "Vectorless claim", "A statement whose vector is missing.")
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors")  # simulate rebuild-before-backfill window

    _, seeds = _find_conflict_candidates(engine, limit=100, delta=True)
    assert (node_id, seq) not in seeds  # not drained -> cursor cannot pass it


def test_seedless_nodes_are_still_drained(engine):
    """A seed whose pairs are all prefiltered still appears in the drained list
    (it must not block the cursor)."""
    from ormah.background.conflict_detector import _find_conflict_candidates

    node_id, seq = _make_belief(engine, "Lone fact", "A completely unrelated singleton statement.")
    _, seeds = _find_conflict_candidates(engine, limit=100, delta=True)
    assert (node_id, seq) in seeds


def test_scope_toggle_resets_delta_selection(engine):
    """Nodes ingested while conflict_check_all_spaces was OFF must become
    reachable when it turns ON, even if the cursor already passed them."""
    from ormah.background.conflict_detector import _find_conflict_candidates
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, set_watermark

    engine.settings.conflict_check_all_spaces = False
    node_id, seq = _make_belief(engine, "Global claim", "A plain global-space statement.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, CONFLICT_WATERMARK_KEY, max_seq)
    with engine.db.transaction() as conn:  # stamp as if advanced under scope=global
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES "
            "('conflict_check_watermark_scope', 'global')"
        )

    engine.settings.conflict_check_all_spaces = True  # operator flips the flag
    _, seeds = _find_conflict_candidates(engine, limit=100, delta=True)
    assert (node_id, seq) in seeds  # stamp mismatch -> watermark treated as 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_conflict_detector.py -v -k "watermark or old_neighbor or max_seeds or drained"`
Expected: FAIL — `TypeError: _find_conflict_candidates() got an unexpected keyword argument 'delta'`

- [ ] **Step 3: Add the settings**

In `src/ormah/config.py`, immediately after `auto_link_max_nodes_per_run: int = 500` (~line 133):

```python
    duplicate_check_max_nodes_per_run: int = 500  # seed batch per dedup run (#81)
    conflict_check_max_nodes_per_run: int = 500   # seed batch per conflict run (#81)
```

- [ ] **Step 4: Rewrite the finder's selection**

In `src/ormah/background/conflict_detector.py`, change the signature and the node fetch (lines 104-131). Everything below the fetch (the seed/neighbor loops and prefilters) keeps its existing logic — only the bookkeeping shown here is added:

```python
CONFLICT_SCOPE_STAMP_KEY = "conflict_check_watermark_scope"


def _conflict_scope_value(settings) -> str:
    return "all" if settings.conflict_check_all_spaces else "global"


def _find_conflict_candidates(
    engine,
    limit: int = 8,
    *,
    max_seeds: int | None = None,
    delta: bool = False,
):
    """Find node pairs that might contradict each other.

    ``delta=False`` (default — the agent/two-call path): today's selection,
    unchanged: full ``ORDER BY RANDOM()`` fetch, returns a candidate list.

    ``delta=True`` (background run only, #81): seeds are nodes with ``seq``
    above the ``conflict_check_watermark``, oldest-first, bounded by
    *max_seeds* (default: ``conflict_check_max_nodes_per_run``). Vector
    neighbors are NOT filtered by age — a new seed pairs against neighbors of
    any age. Returns ``(candidates, drained_seeds)``; ``drained_seeds`` is
    ``[(node_id, seq), ...]`` ascending, containing only seeds whose neighbor
    loop completed (a seed cut short by the pair *limit* is excluded so the
    cursor never passes it). Candidates each carry ``seed_seq``. A scope-stamp
    mismatch (``conflict_check_all_spaces`` changed since the last advance)
    treats the watermark as 0. Only ``run_conflict_detection`` advances the
    watermark; this function never writes it. ``limit`` stays pair-denominated
    in both modes.
    """
    drained_seeds: list[tuple[str, int]] = []
    try:
        from ormah.embeddings.encoder import get_encoder
        from ormah.embeddings.vector_store import VectorStore, stored_or_encoded

        settings = engine.settings
        encoder = get_encoder(settings)
        vec_store = VectorStore(engine.db)

        space_filter = "" if settings.conflict_check_all_spaces else \
            "AND (space IS NULL OR space = 'null') "

        if delta:
            from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

            if max_seeds is None:
                max_seeds = settings.conflict_check_max_nodes_per_run
            watermark = get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY)
            stamp = engine.db.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (CONFLICT_SCOPE_STAMP_KEY,)
            ).fetchone()
            if stamp is not None and stamp["value"] != _conflict_scope_value(settings):
                watermark = 0  # scope changed: older nodes are newly in scope

            nodes = engine.db.conn.execute(
                "SELECT id, content, title, type, created, space, seq FROM nodes "
                f"WHERE type IN (?, ?, ?, ?) {space_filter}AND seq > ? "
                "ORDER BY seq ASC LIMIT ?",
                (*_BELIEF_TYPES, watermark, max_seeds),
            ).fetchall()
        else:
            # Legacy selection — byte-for-byte today's queries (agent path).
            nodes = engine.db.conn.execute(
                "SELECT id, content, title, type, created, space, seq FROM nodes "
                f"WHERE type IN (?, ?, ?, ?) {space_filter}ORDER BY RANDOM()",
                _BELIEF_TYPES,
            ).fetchall()

        checked: set[tuple[str, str]] = set()
        candidates: list[dict] = []

        for node in nodes:
            if len(candidates) >= limit:
                break  # pair budget hit before this seed: not drained
            # ... existing per-seed body unchanged (empty-text skip counts as
            #     drained: `continue` AFTER appending to drained_seeds) ...
            # FAIL-CLOSED (overview invariant, mirrors upstream@4f66abc
            # auto_linker.py:344-354): placed IMMEDIATELY AFTER the empty-text
            # check and BEFORE stored_or_encoded/vec_store.search — at the SEED
            # level, never inside the neighbor loop. A seed with text but no
            # persisted vector must NOT drain (empty/backfilling index would
            # return zero neighbors and the cursor would pass real pairs):
            #     if delta and vec_store.get(node["id"]) is None:
            #         continue  # NOT appended to drained_seeds
            # When appending a candidate inside the neighbor loop, add:
            #     "seed_seq": node["seq"],
            if len(candidates) >= limit:
                break  # pair budget hit mid-seed: possibly partial, not drained
            drained_seeds.append((node["id"], node["seq"]))

        if delta:
            return candidates, drained_seeds
        return candidates

    except Exception as e:
        logger.warning("_find_conflict_candidates failed: %s", e)
        return ([], []) if delta else []
```

Concretely: the existing empty-text `continue` (line ~141-142) must append to `drained_seeds` first; the candidate dict (line ~202-206) gains `"seed_seq": node["seq"]`. No prefilter (belief types, space gate, `auto_link_checked` skip, sim ≥ 0.4, contradicts/evolved_from edge skip) is removed or reordered. The two original `if/else` queries collapse into the single `space_filter` f-string shown — assert both legacy behaviors are covered by the pre-existing `test_project_scoped_nodes_*` tests. The exception swallow (`return []`) is today's upstream behavior — kept as-is (parity), noted for the #92-observability reconciliation.

- [ ] **Step 5: Run the new tests, then the whole file**

Run: `.venv/bin/python -m pytest tests/test_background/test_conflict_detector.py -v`
Expected: all pass — the pre-existing tests (LLM classification, space gating) must stay green; they create fresh nodes above the initial watermark 0, so selection still reaches them.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/config.py src/ormah/background/conflict_detector.py tests/test_background/test_conflict_detector.py
git commit -m "feat(background): delta-select conflict seeds by seq watermark (#81)"
```

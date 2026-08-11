# Task 3: Watermark advance in `run_conflict_detection`

Read `00-overview.md` first. Work in `/Users/andre/Documents/GitHub/Tools/ormah-81` on branch `fix/81-delta-selection`. Depends on Tasks 1-2.

**Files:**
- Modify: `src/ormah/background/conflict_detector.py` (`run_conflict_detection`, ~line 215)
- Test: `tests/test_background/test_conflict_detector.py` (extend)

Semantics (overview invariants): cursor advances to the last CONTIGUOUS drained seed (seq order) with zero LLM failures; a `_llm_check_conflict` returning `None` marks its seed failed; later seeds still processed this run but not passed. Agent path never advances (it calls the finder directly, not this function).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_conflict_detector.py` (uses `_make_belief` from Task 2):

```python
def _conflict_response():
    return json.dumps({
        "conflict": True, "same_subject": True, "relationship": "tension",
        "reason": "Opposing claims.",
    })


def test_clean_run_advances_watermark_past_all_seeds(engine):
    from ormah.background.conflict_detector import run_conflict_detection
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

    _make_belief(engine, "Tea is calming", "Tea makes the user calm in the evening.")
    _make_belief(engine, "Tea is agitating", "Tea makes the user agitated in the evening.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_conflict_response()):
        run_conflict_detection(engine)

    assert get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY) == max_seq


def test_llm_failure_parks_watermark_before_failed_seed(engine):
    """Seed A succeeds, seed B's LLM check returns None -> cursor stops at A;
    the next run re-selects B."""
    from ormah.background.conflict_detector import (
        _find_conflict_candidates, run_conflict_detection,
    )
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

    _make_belief(engine, "Cats are aloof", "The cat ignores everyone at home.")
    _make_belief(engine, "Cats are clingy", "The cat follows everyone at home.")
    b_id, b_seq = _make_belief(engine, "Dogs bark a lot", "The dog barks at everything.")
    _make_belief(engine, "Dogs are silent", "The dog never barks at anything.")

    def llm_fails_for_b(prompt, *args, **kwargs):
        if "barks" in prompt:
            return None          # seed involving the dog pair fails
        return _conflict_response()

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, side_effect=llm_fails_for_b):
        run_conflict_detection(engine)

    wm = get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY)
    assert wm < b_seq  # cursor did not pass the failed seed

    # next run re-selects the failed seed
    candidates = _find_conflict_candidates(engine, limit=100)
    assert any(b_id in (c["node_a"]["id"], c["node_b"]["id"]) for c in candidates)


def test_conflict_run_llm_disabled_does_not_advance_watermark(engine):
    """The llm_enabled guard must run BEFORE selection: a disabled-LLM run
    must not move the cursor (guard-reorder regression trap)."""
    from ormah.background.conflict_detector import run_conflict_detection
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark

    _make_belief(engine, "Any claim", "A statement that would otherwise be a seed.")
    engine.settings.llm_provider = "none"
    _reset_adapter()
    run_conflict_detection(engine)
    assert get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY) == 0


def test_run_with_no_new_nodes_is_a_noop(engine):
    from ormah.background.conflict_detector import run_conflict_detection
    from ormah.background.watermark import CONFLICT_WATERMARK_KEY, get_watermark, set_watermark

    _make_belief(engine, "Solo fact", "One isolated statement about nothing else.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, CONFLICT_WATERMARK_KEY, max_seq)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    llm = MagicMock(return_value=_conflict_response())
    with patch(_LLM_PATCH, llm):
        run_conflict_detection(engine)

    llm.assert_not_called()
    assert get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY) == max_seq
```

Note: `test_llm_failure_parks_watermark_before_failed_seed` needs the cat pair to sort below the dog pair in seq (creation order guarantees it). If the cat seed's LLM check also matches `"barks"` the test is invalid — the contents above were chosen so only dog-pair prompts contain the word.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_conflict_detector.py -v -k "advances or parks or noop"`
Expected: FAIL — watermark stays 0 (`run_conflict_detection` does not advance it yet)

- [ ] **Step 3: Implement the advance**

In `run_conflict_detection` (conflict_detector.py:215): switch the finder call to `delta=True`, track failed seeds, advance the contiguous clean prefix after the existing edge-flush:

```python
        from ormah.background.watermark import (
            CONFLICT_WATERMARK_KEY, get_watermark, set_watermark,
        )

        candidates, drained_seeds = _find_conflict_candidates(
            engine, limit=10_000, delta=True,
        )
        failed_seed_seqs: set[int] = set()
        edges_created = 0
        dirty_nodes: dict[str, list[Connection]] = {}

        for candidate in candidates:
            node_a = candidate["node_a"]
            node_b = candidate["node_b"]

            llm_result = _llm_check_conflict(settings, node_a, node_b)
            if llm_result is None:
                failed_seed_seqs.add(candidate["seed_seq"])
                continue
            # ... rest of the existing loop body unchanged ...

        # ... existing edge flush / dirty-node persistence unchanged ...

        # ponytail: contiguous-prefix advance; a deterministically failing seed
        # parks the cursor — dead-letter escape hatch is upstream #122.
        new_watermark = get_watermark(engine.db.conn, CONFLICT_WATERMARK_KEY)
        for _seed_id, seed_seq in drained_seeds:  # ascending seq
            if seed_seq in failed_seed_seqs:
                break
            new_watermark = seed_seq
        set_watermark(engine, CONFLICT_WATERMARK_KEY, new_watermark)
        # Stamp the scope this cursor was advanced under (finder resets on mismatch)
        with engine.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (CONFLICT_SCOPE_STAMP_KEY, _conflict_scope_value(settings)),
            )
```

(`CONFLICT_SCOPE_STAMP_KEY` and `_conflict_scope_value` are module-level in this same file, added in Task 2.)

The `limit=10_000` literal replaces the same literal already at line 224 — pair budget stays non-binding for the run path.

- [ ] **Step 4: Run the whole file**

Run: `.venv/bin/python -m pytest tests/test_background/test_conflict_detector.py -v`
Expected: all pass (pre-existing tests included — they run with watermark 0, so their fresh nodes are always selected)

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/conflict_detector.py tests/test_background/test_conflict_detector.py
git commit -m "feat(background): advance conflict watermark past drained seeds (#81)"
```

# Task 5: `run_duplicate_detection` onto the finder + watermark advance

Read `00-overview.md` first. Work in `/Users/andre/Documents/GitHub/Tools/ormah-81` on branch `fix/81-delta-selection`. Depends on Tasks 1, 2 (settings), 4.

**Files:**
- Modify: `src/ormah/background/duplicate_merger.py` (`run_duplicate_detection`, lines 240-386)
- Test: `tests/test_background/test_duplicate_merger.py` (extend)

The inline full-scan loop (plain `SELECT` over ALL nodes, its own vec search and prefilters, no skip check, no bound) is replaced by consuming `_find_merge_candidates(..., delta=True)`. Declared behavior change for the PR body: the run now honors the `auto_link_checked` skip and the per-run seed bound.

**CRITICAL data-loss guard (overview invariant):** finder `_nd` dicts truncate `content` to 400 chars. `_llm_check_duplicate` output feeds `execute_merge(merged_content=...)` — judging/merging from 400-char previews would be a regression. The run MUST re-fetch untruncated rows by id before calling the LLM. Note the pre-existing ceiling: `_llm_check_duplicate` itself truncates at 2000 chars (upstream, unchanged by this plan) — the re-fetch restores PARITY with today's run, it does not widen that ceiling (documented in the overview's known limitations).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_duplicate_merger.py` (uses `_make_fact` from Task 4):

```python
def _duplicate_response():
    return json.dumps({
        "is_duplicate": True,
        "merged_title": "Merged fact",
        "merged_content": "The merged content.",
        "reason": "Same statement.",
    })


def test_run_does_not_rejudge_pair_below_watermark(engine):
    """Reproduces #81: with the cursor past both nodes, a run must not spend
    LLM calls on them again."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark, set_watermark

    _make_fact(engine, "Editor choice", "The user edits everything in neovim.")
    _make_fact(engine, "Editor pick", "The user does all editing in neovim.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]
    set_watermark(engine, DUPLICATE_WATERMARK_KEY, max_seq)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    llm = MagicMock(return_value=_duplicate_response())
    with patch(_LLM_PATCH, llm):
        run_duplicate_detection(engine)

    llm.assert_not_called()
    assert get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY) == max_seq


def test_run_creates_proposal_for_delta_pair_and_advances(engine):
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    engine.settings.auto_merge_threshold = 999.0  # force proposal path, not auto-merge
    _make_fact(engine, "Backup time", "Backups run every night at 2am.")
    _make_fact(engine, "Backup schedule", "The backup runs nightly at 2am.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        run_duplicate_detection(engine)

    proposals = engine.db.conn.execute(
        "SELECT 1 FROM proposals WHERE type = 'merge' AND status = 'pending'"
    ).fetchall()
    assert len(proposals) >= 1
    assert get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY) == max_seq


def test_run_judges_full_content_not_400_char_preview(engine):
    """The LLM must receive the node's untruncated row (merge safety, parity
    with today's run), not the finder's 400-char preview. The marker sits
    beyond 400 chars but under _llm_check_duplicate's own pre-existing
    2000-char ceiling."""
    from ormah.background.duplicate_merger import run_duplicate_detection

    marker = "UNIQUE-TAIL-MARKER-9137"
    long_content = "The deploy procedure is documented step by step. " * 12 + marker
    _make_fact(engine, "Deploy procedure", long_content)
    _make_fact(engine, "Deployment steps", long_content.replace("documented", "written"))
    assert len(long_content) > 400

    seen_prompts: list[str] = []

    # NOTE: _llm_check_duplicate calls llm_generate(settings, prompt, json_mode=True),
    # so the mock MUST take `settings` FIRST — otherwise settings lands in `prompt`
    # and `marker in p` silently reads False (bug caught in Task 3's analogous mock).
    def capture(settings, prompt, *args, **kwargs):
        seen_prompts.append(prompt)
        return json.dumps({"is_duplicate": False, "reason": "distinct"})

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, side_effect=capture):
        run_duplicate_detection(engine)

    assert seen_prompts, "expected at least one LLM call for the near-duplicate pair"
    assert any(marker in p for p in seen_prompts)


def test_run_llm_failure_parks_dedup_watermark_exactly(engine):
    """A clean seed batch BEFORE the failing pair advances; the cursor stops
    exactly at the last clean seed before the failure (no `or wm == 0`
    escape hatch — the advance must be exact)."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    # unrelated singleton first: a clean, candidate-less seed with low seq
    _, clean_seq = _make_fact(engine, "Lone note", "A singleton note about nothing similar.")
    # then the near-duplicate pair whose LLM check will fail
    _, pair_seq_a = _make_fact(engine, "Coffee dose", "The user drinks two espressos daily.")
    _make_fact(engine, "Espresso habit", "The user has two espressos every day.")

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=None):  # LLM unavailable for every pair
        run_duplicate_detection(engine)

    wm = get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY)
    assert wm >= clean_seq      # clean prefix advanced
    assert wm < pair_seq_a      # cursor parked before the failed seed


def test_dedup_run_llm_disabled_does_not_advance_watermark(engine):
    """Guard order: `if not settings.llm_enabled: return` fires BEFORE any
    selection or advance."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    _make_fact(engine, "Any note", "A note that would otherwise be a seed.")
    engine.settings.llm_provider = "none"
    _reset_adapter()
    run_duplicate_detection(engine)
    assert get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY) == 0


def test_auto_merge_survivor_requeues_into_delta(engine):
    """When a pair auto-merges mid-run, the survivor's content rewrite
    allocates a fresh seq (see test_seq_bumped_on_rewrite), so it re-enters
    the delta on the next run — skipping its stale pairs loses no work."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    engine.settings.auto_merge_threshold = 0.0  # force the auto-merge path
    id_a, _ = _make_fact(engine, "Deploy cmd", "Deploy with make release every Friday.")
    id_b, _ = _make_fact(engine, "Release cmd", "Release with make release every Friday.")

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        run_duplicate_detection(engine)

    survivors = [r["id"] for r in engine.db.conn.execute(
        "SELECT id FROM nodes WHERE id IN (?, ?)", (id_a, id_b)).fetchall()]
    assert len(survivors) == 1  # one node merged away
    surv_seq = engine.db.conn.execute(
        "SELECT seq FROM nodes WHERE id = ?", (survivors[0],)).fetchone()["seq"]
    wm = get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY)
    assert surv_seq > wm  # survivor sits ABOVE the cursor: re-selected next run
```

Add `MagicMock` to the existing `unittest.mock` import line if not present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v -k "rejudge or delta_pair or full_content or parks"`
Expected: FAIL — `test_run_does_not_rejudge_pair_below_watermark` sees LLM calls (inline loop scans everything); the others fail on watermark == 0.

- [ ] **Step 3: Rewrite the run**

Replace the body of `run_duplicate_detection` between the `user_node_id = ...` line (260) and the final `if proposals_created:` log (382). The LLM-confirmation, auto-merge, existing-proposal check and proposal INSERT blocks are kept VERBATIM from today's loop (lines 316-381) — only selection and bookkeeping change:

```python
        from ormah.background.watermark import (
            DUPLICATE_WATERMARK_KEY, get_watermark, set_watermark,
        )

        candidates, drained_seeds = _find_merge_candidates(
            engine, limit=10_000, delta=True,
        )
        failed_seed_seqs: set[int] = set()
        proposals_created = 0

        for cand in candidates:
            # Re-fetch FULL rows: finder previews are truncated to 400 chars and
            # merged_content must never be generated from truncated text.
            node = engine.db.conn.execute(
                "SELECT id, content, title, type FROM nodes WHERE id = ?",
                (cand["node_a"]["id"],),
            ).fetchone()
            other = engine.db.conn.execute(
                "SELECT id, content, title, type FROM nodes WHERE id = ?",
                (cand["node_b"]["id"],),
            ).fetchone()
            if node is None or other is None:
                continue  # merged/deleted earlier in this same run: drained

            embedding_sim = cand["embedding_sim"]
            title_sim = cand["title_sim"]
            token_sim = cand["token_sim"]
            score = cand["score"]

            # --- LLM confirmation (mandatory) --- [unchanged block, using
            # `node`/`other` full rows; on llm_result None:]
            llm_result = _llm_check_duplicate(settings, node, other)
            if llm_result is None:
                failed_seed_seqs.add(cand["seed_seq"])
                continue
            # ... rest of today's loop body verbatim (reject log, merged_content,
            #     auto-merge, existing-proposal check, INSERT, counters), with
            #     `match["id"]` replaced by `other["id"]` ...

        # ponytail: contiguous-prefix advance; deterministic failure parks the
        # cursor — dead-letter escape hatch is upstream #122.
        new_watermark = get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY)
        for _seed_id, seed_seq in drained_seeds:  # ascending seq
            if seed_seq in failed_seed_seqs:
                break
            new_watermark = seed_seq
        set_watermark(engine, DUPLICATE_WATERMARK_KEY, new_watermark)
```

Delete: the run's own `nodes = ...` full-table SELECT, its vec-search loop, its local prefilters (the finder now owns them), and the now-unused locals `encoder`, `vec_store`, `user_node_id`, `checked` IF nothing else in the function uses them (check before removing the imports; ruff F841 will flag leftovers). The `if not settings.llm_enabled: return` guard stays first — before any selection, so a disabled-LLM run does not advance the watermark.

- [ ] **Step 4: Run the whole file, then lint**

Run: `.venv/bin/python -m pytest tests/test_background/test_duplicate_merger.py -v`
Expected: all pass. Pre-existing tests (`test_llm_confirms_duplicate_auto_merge` etc.) run with watermark 0 and must stay green — they now flow through the finder.

Run: `.venv/bin/ruff check src/ormah/background/duplicate_merger.py`
Expected: clean (unused imports removed).

- [ ] **Step 5: Full-suite verification (overview gate)**

```bash
.venv/bin/python -m pytest tests/test_background/ -v
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src/ tests/
```
Expected: all green, no regressions outside `test_background` either. Paste outputs in the completion report.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/duplicate_merger.py tests/test_background/test_duplicate_merger.py
git commit -m "refactor(background): route run_duplicate_detection through the delta finder (#81)"
```

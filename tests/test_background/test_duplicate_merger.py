"""Tests for LLM-based duplicate consolidation in duplicate_merger."""

from __future__ import annotations

import json
import logging
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from ormah.models.node import CreateNodeRequest, NodeType, UpdateNodeRequest

_LLM_PATCH = "ormah.background.llm_client.llm_generate"


def _create_pair(engine, title_a="Python language", content_a="Python is a programming language.",
                 title_b="Python lang", content_b="Python is a popular programming language.",
                 node_type=NodeType.fact):
    """Helper: create two similar nodes and return their IDs."""
    id_a, _ = engine.remember(
        CreateNodeRequest(content=content_a, type=node_type, title=title_a, tags=["test"]),
        agent_id="test",
    )
    id_b, _ = engine.remember(
        CreateNodeRequest(content=content_b, type=node_type, title=title_b, tags=["test"]),
        agent_id="test",
    )
    return id_a, id_b


def _reset_adapter():
    from ormah.background.llm_client import reset_adapter
    reset_adapter()


def _table_row_counts(engine) -> dict[str, int]:
    """Row count of every table in the store — the probe for "no row anywhere"."""
    names = [r["name"] for r in engine.db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
    counts = {}
    for name in names:
        try:
            counts[name] = engine.db.conn.execute(
                f'SELECT COUNT(*) AS c FROM "{name}"').fetchone()["c"]
        except sqlite3.OperationalError:   # fts5 shadow tables that refuse a bare count
            continue
    return counts


def _proposal_count(engine) -> int:
    """Rows in `proposals`. ADR-0006: this job files none, ever."""
    return engine.db.conn.execute("SELECT COUNT(*) AS c FROM proposals").fetchone()["c"]


def test_llm_confirms_duplicate_auto_merge(engine):
    """LLM confirms duplicate -> auto-merge with merged content."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": True,
        "merged_title": "Python Programming Language",
        "merged_content": "Python is a popular programming language used widely.",
        "reason": "Both describe Python as a programming language.",
    })

    # Force auto-merge threshold low so the pair qualifies
    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        stats = run_duplicate_detection(engine)

    # One of the two nodes should have been removed; the kept one should
    # have the LLM-generated content.
    kept = engine.file_store.load(id_a) or engine.file_store.load(id_b)
    assert kept is not None
    assert kept.content == "Python is a popular programming language used widely."
    assert kept.title == "Python Programming Language"

    # The merged Pair is reported apart from the barred ones (ADR-0006).
    assert stats["merged"] == 1
    assert stats["below_threshold"] == 0


def test_llm_rejects_duplicate_no_merge(engine):
    """LLM rejects duplicate -> no merge or proposal despite high composite score."""
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": False,
        "merged_title": "",
        "merged_content": "",
        "reason": "These describe different aspects of Python.",
    })

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        stats = run_duplicate_detection(engine)

    # Both nodes should still exist
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None

    # A "not a duplicate" verdict moves neither counter.
    assert stats["pairs_evaluated"] == 1
    assert stats["merged"] == 0
    assert stats["below_threshold"] == 0
    assert stats["below_threshold_mean_score"] is None


def test_llm_unavailable_skips_merge(engine):
    """LLM returns None -> pair is skipped, both nodes survive, no proposals."""
    id_a, id_b = _create_pair(engine)

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(_LLM_PATCH, return_value=None):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    # Both nodes should still exist
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None

    # No proposals
    assert _proposal_count(engine) == 0


def test_llm_disabled_skips_detection(engine):
    """With llm_provider='none', LLM is never called."""
    id_a, id_b = _create_pair(engine)

    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "none"
    _reset_adapter()

    mock_llm = MagicMock()
    with patch(_LLM_PATCH, mock_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    mock_llm.assert_not_called()


def test_confirmed_duplicate_below_threshold_writes_no_row_anywhere(engine):
    """ADR-0006: a confirmed duplicate under the Auto-merge threshold does not
    merge and does not get filed — nothing happens to it, and the run reports it.

    Was ``test_merged_content_stored_in_proposal``: same scenario (a confirmed
    pair the bar rejects), asserting the new outcome.
    """
    id_a, id_b = _create_pair(engine)

    llm_response = json.dumps({
        "is_duplicate": True,
        "merged_title": "Python Programming Language",
        "merged_content": "Python is a popular programming language used widely.",
        "reason": "Both describe Python as a programming language.",
    })

    # Set threshold high so the pair sits below the bar
    engine.settings.auto_merge_threshold = 0.99
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    before = _table_row_counts(engine)
    with patch(_LLM_PATCH, return_value=llm_response):
        from ormah.background.duplicate_merger import run_duplicate_detection
        stats = run_duplicate_detection(engine)

    # Both nodes should still exist (no auto-merge)
    assert engine.file_store.load(id_a) is not None
    assert engine.file_store.load(id_b) is not None

    assert _proposal_count(engine) == 0

    # ...and no row anywhere else either. `meta` is the watermark's home, which
    # this run legitimately advances.
    after = _table_row_counts(engine)
    grew = {t: (before.get(t), c) for t, c in after.items()
            if before.get(t) != c and t != "meta"}
    assert grew == {}, f"rows appeared outside `meta`: {grew}"

    assert stats["merged"] == 0
    assert stats["below_threshold"] == 1


def test_pairs_evaluated_counts_one_candidate_pair(engine):
    """Issue #90: pairs_evaluated must reflect exactly one LLM decision call."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(
        "ormah.background.duplicate_merger._llm_check_duplicate",
        return_value={"is_duplicate": False, "reason": "not a duplicate"},
    ):
        from ormah.background.duplicate_merger import run_duplicate_detection
        stats = run_duplicate_detection(engine)

    assert stats["pairs_attempted"] == 1
    assert stats["pairs_evaluated"] == 1
    # duration_s must have millisecond resolution — a fast mocked-LLM run
    # must not silently round down to 0.0 (issue #90 finding 2).
    assert stats["duration_s"] > 0


def test_pairs_attempted_counts_llm_unavailable_pair_but_not_evaluated(engine):
    """Issue #90 (council finding 2): an LLM-unavailable pair (None decision)
    must count as attempted but NOT as evaluated."""
    id_a, id_b = _create_pair(engine)

    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    with patch(
        "ormah.background.duplicate_merger._llm_check_duplicate",
        return_value=None,
    ):
        from ormah.background.duplicate_merger import run_duplicate_detection
        stats = run_duplicate_detection(engine)

    assert stats["pairs_attempted"] == 1
    assert stats["pairs_evaluated"] == 0


# --- #87 pair batching ---

def test_duplicate_prompt_is_composed_from_parts():
    from ormah.background import duplicate_merger as dm
    assert dm._LLM_DUPLICATE_PROMPT == (
        dm._LLM_DUP_INTRO + "\n\n" + dm._LLM_DUP_PAIR + "\n\n" + dm._LLM_DUP_RULES
    )
    assert dm._LLM_DUP_INSTRUCTIONS == dm._LLM_DUP_INTRO + "\n\n" + dm._LLM_DUP_RULES


def test_batched_dedup_reports_barred_pairs(engine):
    """Was ``test_batched_dedup_creates_proposals``: same batched run, asserting
    the new outcome — the confirmed Pairs the bar rejects are counted, not filed."""
    from ormah.background import duplicate_merger as dm
    for _ in range(3):
        engine.remember(CreateNodeRequest(
            content="ormah stores memories in sqlite with fts5", title="ormah storage"))
    engine.settings.llm_provider = "ollama"
    engine.settings.maintenance_pairs_per_call = 2
    engine.settings.auto_merge_threshold = 2.0     # every Pair sits below the bar
    _reset_adapter()

    def fake_batch(settings, prompt, json_mode=True, **kw):
        n = prompt.count("### Pair ")
        return json.dumps({"verdicts": [
            {"pair_id": i, "is_duplicate": True, "merged_title": "t",
             "merged_content": "c", "reason": "same fact"} for i in range(n)]})

    single = {"is_duplicate": True, "merged_title": "t", "merged_content": "c",
              "reason": "same fact"}
    with patch("ormah.background.llm.pair_batch.llm_generate", fake_batch), \
            patch("ormah.background.duplicate_merger._llm_check_duplicate", return_value=single):
        stats = dm.run_duplicate_detection(engine)

    assert _proposal_count(engine) == 0
    assert stats["pairs_evaluated"] >= 1
    assert stats["merged"] == 0
    assert stats["below_threshold"] >= 1


def test_batched_dedup_skips_pairs_whose_node_was_merged_away(engine):
    """Codex council finding (#87): overlapping pairs in one window (e.g. (A,B)
    and (B,C)) — once an auto-merge deletes a shared node, a later pair must be
    skipped, not re-merged on the stale (now-missing) node. execute_merge silently
    no-ops on a missing node ('Node X not found.'), which would otherwise miscount
    it as a successful merge."""
    from ormah.background import duplicate_merger as dm
    for _ in range(3):
        engine.remember(CreateNodeRequest(
            content="ormah stores memories in sqlite with fts5", title="ormah storage"))
    engine.settings.llm_provider = "ollama"
    engine.settings.maintenance_pairs_per_call = 3      # all candidate pairs in one window
    engine.settings.auto_merge_threshold = 0.0          # force the auto-merge path for every pair
    _reset_adapter()

    real_merge = engine.execute_merge
    bad_calls = []

    def spy_merge(node_id_a, node_id_b, **kw):
        for nid in (node_id_a, node_id_b):
            if engine.db.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (nid,)).fetchone() is None:
                bad_calls.append(nid)
        return real_merge(node_id_a, node_id_b, **kw)

    def fake_batch(settings, prompt, json_mode=True, **kw):
        n = prompt.count("### Pair ")
        return json.dumps({"verdicts": [
            {"pair_id": i, "is_duplicate": True, "merged_title": "t",
             "merged_content": "c", "reason": "same"} for i in range(n)]})

    single = {"is_duplicate": True, "merged_title": "t", "merged_content": "c", "reason": "same"}
    with patch("ormah.background.llm.pair_batch.llm_generate", fake_batch), \
            patch("ormah.background.duplicate_merger._llm_check_duplicate", return_value=single), \
            patch.object(engine, "execute_merge", spy_merge):
        dm.run_duplicate_detection(engine)

    assert bad_calls == [], f"execute_merge called on already-deleted node(s): {bad_calls}"


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


def test_dedup_barrier_logs_once_per_run(engine, caplog):
    """The vectorless drain barrier warns once per run, not once per seed."""
    from ormah.background.duplicate_merger import _find_merge_candidates

    id_a, _ = _make_fact(engine, "Vectorless note A", "First note whose vector is missing.")
    id_b, _ = _make_fact(engine, "Vectorless note B", "Second note whose vector is missing.")
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id IN (?, ?)", (id_a, id_b))

    with caplog.at_level(logging.WARNING):
        _find_merge_candidates(engine, limit=100, delta=True)

    matches = [r for r in caplog.records if "no persisted vector" in r.message]
    assert len(matches) == 1


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


def test_run_bars_delta_pair_and_still_advances(engine):
    """Was ``test_run_creates_proposal_for_delta_pair_and_advances``: same delta
    Pair, asserting the new outcome — barred, unfiled, and the Watermark still
    advances to the last drained seed."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    engine.settings.auto_merge_threshold = 999.0  # the Pair sits below the bar
    _make_fact(engine, "Backup time", "Backups run every night at 2am.")
    _make_fact(engine, "Backup schedule", "The backup runs nightly at 2am.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        stats = run_duplicate_detection(engine)

    assert _proposal_count(engine) == 0
    assert stats["below_threshold"] >= 1
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


def test_dedup_run_vectorless_seed_blocks_watermark(engine):
    """A vectorless seed must be a barrier: no later seed may drain past it,
    or the watermark jumps a hole and the vectorless seed's pairs are never
    re-checked once vectors are restored (#81 regression)."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    id_a, seq_a = _make_fact(engine, "Vectorless note", "A note whose vector went missing.")
    id_b, seq_b = _make_fact(engine, "Second note", "A second, unrelated note.")
    assert seq_a < seq_b

    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (id_a,))  # only the LOWER-seq seed loses its vector

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        run_duplicate_detection(engine)

    # With the `break` fix the finder stops at the vectorless barrier
    # (seq_a): the cursor may advance past legitimately-drained seeds before
    # it (e.g. the engine's own user_node), but must never reach seq_a or
    # jump the hole to seq_b.
    assert get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY) < seq_a


def test_dedup_run_judges_pair_already_in_auto_link_checked(engine):
    """Background dedup must not skip a pair merely because auto_linker
    already recorded a link decision for it (#81 regression: auto_link_checked
    is a LINK-decision log, not a dedup-skip list)."""
    from datetime import datetime, timezone

    from ormah.background.duplicate_merger import run_duplicate_detection

    engine.settings.auto_merge_threshold = 999.0  # the Pair sits below the bar
    id_a, _ = _make_fact(engine, "Editor choice", "The user edits everything in neovim.")
    id_b, _ = _make_fact(engine, "Editor pick", "The user does all editing in neovim.")

    pair = tuple(sorted([id_a, id_b]))
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT INTO auto_link_checked (node_a, node_b, result, checked_at) "
            "VALUES (?, ?, ?, ?)",
            (*pair, "none", datetime.now(timezone.utc).isoformat()),
        )

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        stats = run_duplicate_detection(engine)

    # It was judged: the bar barred it, which only a judged Pair can be.
    assert stats["below_threshold"] >= 1
    assert _proposal_count(engine) == 0


def test_dedup_run_processes_seeds_after_vectorless_barrier(engine):
    """A vectorless barrier parks the cursor but must not stop later seeds
    from being judged (liveness, mirrors upstream auto_linker)."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    engine.settings.auto_merge_threshold = 999.0  # the Pair sits below the bar
    barrier_id, barrier_seq = _make_fact(engine, "Vectorless note", "A note whose vector went missing.")
    with engine.db.transaction() as conn:
        conn.execute("DELETE FROM node_vectors WHERE id = ?", (barrier_id,))

    id_a, _ = _make_fact(engine, "Editor choice", "The user edits everything in neovim.")
    id_b, _ = _make_fact(engine, "Editor pick", "The user does all editing in neovim.")

    engine.settings.llm_provider = "ollama"
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=_duplicate_response()):
        stats = run_duplicate_detection(engine)

    assert stats["below_threshold"] >= 1, "later seeds past the barrier must still be judged"
    assert _proposal_count(engine) == 0

    wm = get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY)
    assert wm < barrier_seq  # cursor still parked before the barrier


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


def test_zero_usable_then_partial_probe_recovers_watermark(engine):
    """#189: recovery fills a partial probe's gap before advancing the cursor."""
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, get_watermark

    engine.settings.auto_merge_threshold = 999.0   # below the bar: no merge perturbs the probe
    _make_fact(engine, "Backup time", "Backups run every night at 2am.")
    _make_fact(engine, "Backup schedule", "The backup runs nightly at 2am.")
    _make_fact(engine, "Nightly backup", "Every night, backups run at 2am.")
    _make_fact(engine, "Backup window", "Backups are scheduled for 2am every night.")
    max_seq = engine.db.conn.execute("SELECT MAX(seq) m FROM nodes").fetchone()["m"]

    engine.settings.llm_provider = "ollama"
    engine.settings.maintenance_pairs_per_call = 4
    _reset_adapter()

    batch_sizes = []

    def staged_batch(settings, prompt, json_mode=True, **kw):
        n = prompt.count("### Pair ")
        batch_sizes.append(n)
        if len(batch_sizes) == 1:
            return json.dumps({"verdicts": [{"v": i} for i in range(n)]})
        if len(batch_sizes) == 2:
            return json.dumps({"verdicts": [{
                "pair_id": 0, "is_duplicate": True, "merged_title": "t",
                "merged_content": "c", "reason": "same fact",
            }]})
        return json.dumps({"verdicts": [
            {"pair_id": i, "is_duplicate": True, "merged_title": "t",
             "merged_content": "c", "reason": "same fact"} for i in range(n)
        ]})

    single = MagicMock(return_value={
        "is_duplicate": True, "merged_title": "t", "merged_content": "c",
        "reason": "same fact",
    })
    with patch("ormah.background.llm.pair_batch.llm_generate", staged_batch), \
            patch("ormah.background.duplicate_merger._llm_check_duplicate",
                  new=single):
        stats = run_duplicate_detection(engine)

    assert stats["pairs_evaluated"] >= 4
    assert batch_sizes[:3] == [4, 2, 2]
    assert single.call_count == 1
    assert get_watermark(engine.db.conn, DUPLICATE_WATERMARK_KEY) == max_seq
    # Same scenario, new outcome: every recovered verdict is confirmed and every
    # Pair sits below the bar, so all of them are barred and none is filed.
    assert stats["below_threshold"] >= 4
    assert _proposal_count(engine) == 0


def test_duplicate_detection_does_not_hold_the_lock_across_the_llm_call(engine):
    from tests.test_background.lock_probe import install_probe

    id_a, id_b = _create_pair(engine)
    # Force the auto-merge branch (the one wrapping engine.execute_merge, itself
    # lock-decorated) so the probe also exercises the nested-lock path.
    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    probe = install_probe(engine)
    lock_held_at_call: list[bool] = []

    def fake_llm(*args, **kwargs):
        lock_held_at_call.append(probe.held)
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    with patch(_LLM_PATCH, side_effect=fake_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    assert lock_held_at_call, "the fake LLM was never called — the fixture stopped exercising the job"
    assert not any(lock_held_at_call)


def test_duplicate_detection_aborts_when_a_restore_lands_mid_run(engine):
    id_a, id_b = _create_pair(engine)
    # The auto-merge branch is the only writing path left (ADR-0006), so the
    # node-count assertion below is what proves the abort.
    engine.settings.auto_merge_threshold = 0.0
    engine.settings.llm_provider = "ollama"
    _reset_adapter()

    nodes_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
    epoch_before = engine.restore_epoch

    # The bump must land AFTER the job read its entry epoch: restore_aware_job reads
    # engine.restore_epoch at call time, so bumping before the call would hand the job the
    # new value and leave no mismatch to detect. Inside the fake LLM is where a real restore
    # lands — between the unlocked LLM call and the apply step that follows it.
    def fake_llm(*args, **kwargs):
        engine._restore_epoch += 1
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    with patch(_LLM_PATCH, side_effect=fake_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)  # returns cleanly

    # Guard against silent vacuousness: the abort assertions below hold trivially if the
    # job never reached an apply step at all. Since the bump lives inside the fake LLM, a
    # moved epoch is proof the job actually got there.
    assert engine.restore_epoch > epoch_before, \
        "the fake LLM was never called — the fixture stopped exercising the job"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes").fetchone()["c"] == nodes_before


def test_a_node_edited_during_the_llm_call_is_not_merged_over(engine):
    """The merged text was written from pre-edit content; do not apply it to edited nodes."""
    import json
    from unittest.mock import patch

    id_a, id_b = _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_merge_threshold = 0.0

    edited = {"done": False}

    def edit_then_answer(*args, **kwargs):
        """The LLM call is the unlocked phase: a foreground edit lands here."""
        if not edited["done"]:
            edited["done"] = True
            engine.update_node(id_a, UpdateNodeRequest(
                content="the user rewrote this node while the merger was thinking"))
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    nodes_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]

    with patch("ormah.background.llm_client.llm_generate", side_effect=edit_then_answer):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    assert edited["done"], "the fake LLM was never called — the fixture stopped exercising the job"
    row = engine.db.conn.execute(
        "SELECT content FROM nodes WHERE id = ?", (id_a,)).fetchone()
    assert row is not None, "the edited node was merged away"
    assert "the user rewrote this node" in row["content"], "the stale merged text overwrote a fresh edit"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes").fetchone()["c"] == nodes_before


def test_below_threshold_mean_score_reflects_the_pairs_actually_barred(engine):
    """The reported mean is the mean of the barred Pairs — not of every judged
    Pair, and not a placeholder.

    Probed without touching the Composite score formula: the same corpus is run
    three times with only the *verdict* changed. Barring Pair 1 alone yields its
    score, barring Pair 2 alone yields its score, and barring both must yield
    exactly the average of the two.
    """
    from ormah.background.duplicate_merger import run_duplicate_detection
    from ormah.background.watermark import DUPLICATE_WATERMARK_KEY, set_watermark

    _make_fact(engine, "Backup time", "Backups run every night at 2am.")
    _make_fact(engine, "Backup schedule", "The backup runs nightly at 2am.")
    _make_fact(engine, "Editor choice", "The user edits everything in neovim.")
    _make_fact(engine, "Editor pick", "The user does all editing in neovim.")

    engine.settings.llm_provider = "ollama"
    engine.settings.maintenance_pairs_per_call = 1     # K=1: one verdict per Pair
    engine.settings.duplicate_check_pairs_per_call = 1
    engine.settings.auto_merge_threshold = 999.0       # every confirmed Pair is barred
    _reset_adapter()

    def _verdict_for(topics):
        def check(settings, node_row, other_row):
            titles = f"{node_row['title']} {other_row['title']}".lower()
            is_dup = any(t in titles for t in topics)
            return {"is_duplicate": is_dup, "merged_title": "t",
                    "merged_content": "c", "reason": "same fact"}
        return check

    def _run(topics):
        set_watermark(engine, DUPLICATE_WATERMARK_KEY, 0)
        with patch("ormah.background.duplicate_merger._llm_check_duplicate",
                   _verdict_for(topics)):
            return run_duplicate_detection(engine)

    backups = _run(["backup"])
    editors = _run(["editor"])
    both = _run(["backup", "editor"])

    assert backups["below_threshold"] == 1
    assert editors["below_threshold"] == 1
    assert both["below_threshold"] == 2

    m_backups = backups["below_threshold_mean_score"]
    m_editors = editors["below_threshold_mean_score"]
    assert m_backups != m_editors, "the two Pairs must score differently, or this proves nothing"
    # abs tolerance: each reported mean is rounded to 3 decimals at the source.
    assert both["below_threshold_mean_score"] == pytest.approx(
        (m_backups + m_editors) / 2, abs=1e-3)

    # Nothing was written for any of them.
    assert _proposal_count(engine) == 0

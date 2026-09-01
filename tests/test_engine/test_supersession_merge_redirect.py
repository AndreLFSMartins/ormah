"""Merging a consolidation node carries its sources' supersession markers (#223).

Consolidation writes A/B -> C.  If C is later merged into D, ``execute_merge``
soft-deletes C while A and B still point at it: the marker then reads as
*dangling*, and the next confirmed use promotes A or B even though D still
represents them.  Reported on PR #257 by the maintainer.
"""

from __future__ import annotations

from ormah.models.node import CreateNodeRequest, Tier


def _live(engine, content: str, title: str) -> str:
    node_id, _ = engine.remember(CreateNodeRequest(content=content, title=title))
    return node_id


def _superseded_source(engine, content: str, replacement: str) -> str:
    """An archival source carrying the marker the consolidator writes."""
    node_id, _ = engine.remember(CreateNodeRequest(content=content))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.superseded_by = replacement
    engine.builder.index_single(engine.file_store.save(node))
    return node_id


def _sql_marker(engine, node_id: str) -> str | None:
    row = engine.db.conn.execute(
        "SELECT superseded_by FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return None if row is None else row["superseded_by"]


def _consolidation_then_merge(engine):
    """A/B -> C, then C merged into D.  Returns (a, b, c, d).

    D wins ``_pick_keeper`` deterministically: same tier, strictly longer content.
    """
    c = _live(engine, "the consolidation node", "C")
    a = _superseded_source(engine, "source A folded into C", c)
    b = _superseded_source(engine, "source B folded into C", c)
    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )
    engine.execute_merge(c, d)
    return a, b, c, d


def test_merging_the_replacement_redirects_every_source(engine):
    a, b, c, d = _consolidation_then_merge(engine)

    assert engine.file_store.load(c) is None, "precondition: C was soft-deleted"
    assert engine.file_store.load(a).superseded_by == d
    assert engine.file_store.load(b).superseded_by == d


def test_the_redirect_reaches_sqlite_too(engine):
    """Markdown and index must not disagree: the promotion gate reads the file,
    but a reindex rebuilds the file's value into the row and sync reads the row."""
    a, b, _c, d = _consolidation_then_merge(engine)

    assert _sql_marker(engine, a) == d
    assert _sql_marker(engine, b) == d


def test_a_redirected_source_still_blocks_promotion(engine):
    """The point of the redirect.  With the stale pointer the marker reads as
    dangling (C is gone), the self-healing branch lifts the block, and A promotes
    into the whisper-eligible tier even though D represents it."""
    a, _b, _c, _d = _consolidation_then_merge(engine)

    engine._record_confirmed_use(a)

    assert engine.file_store.load(a).tier is Tier.archival


def test_a_marker_pointing_elsewhere_is_left_alone(engine):
    """The UPDATE is keyed on the removed node, not on 'has a marker'."""
    other = _live(engine, "an unrelated consolidation node", "other")
    bystander = _superseded_source(engine, "superseded by something else entirely", other)

    _consolidation_then_merge(engine)

    assert engine.file_store.load(bystander).superseded_by == other
    assert _sql_marker(engine, bystander) == other


def test_the_kept_node_never_supersedes_itself(engine):
    """If the kept node is the one carrying the marker, a blind redirect writes
    ``kept.superseded_by = kept.id`` — a marker that always resolves live and buries
    the node forever, the exact failure the dangling-marker branch exists to prevent.
    Absorbing the removed node means nothing supersedes the keeper any more."""
    replacement = _live(engine, "short", "R")
    keeper = engine.file_store.load(replacement)
    keeper.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(keeper))

    marked = _superseded_source(
        engine,
        "the source, longer than its own replacement so _pick_keeper keeps it",
        replacement,
    )

    engine.execute_merge(marked, replacement)

    assert engine.file_store.load(marked) is not None, "precondition: the marked node is the keeper"
    assert engine.file_store.load(marked).superseded_by is None
    assert _sql_marker(engine, marked) is None

    engine._record_confirmed_use(marked)

    assert engine.file_store.load(marked).tier is Tier.working


# --- Where the redirect gets its list of sources -----------------------------
#
# The redirect discovers sources with `SELECT id FROM nodes WHERE superseded_by = ?`
# — it reads the index, not the files.  The three tests below pin what that costs
# and what it does not, because the markdown file is the authority the promotion
# gate reads, and the two can diverge: `_mark_superseded` saves the file first and
# writes the row second, so a crash in between leaves a marker only in markdown.


def _marker_in_markdown_only(engine, content: str, replacement: str) -> str:
    """A source whose marker reached the file but not the row — the crash window
    inside _mark_superseded, reproduced by saving without re-indexing."""
    node_id, _ = engine.remember(CreateNodeRequest(content=content))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.superseded_by = replacement
    engine.file_store.save(node)  # deliberately NOT index_single
    assert _sql_marker(engine, node_id) is None, "precondition: the row never saw the marker"
    return node_id


def test_a_marker_that_never_reached_the_index_is_missed(engine):
    """Characterisation, not an endorsement: the redirect is exactly as
    index-trusting as the code around it — `execute_merge` already reads the
    edges it remaps out of SQLite in the same way, so a stale index mis-remaps
    edges long before it mis-redirects a marker.  Pinning the boundary here means
    a future change that widens it has to edit this test on purpose."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file, absent from the row", c)
    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )

    engine.execute_merge(c, d)

    assert engine.file_store.load(orphan).superseded_by == c, "still pointing at the dead node"
    assert _sql_marker(engine, orphan) is None


def test_the_missed_marker_lets_the_source_promote(engine):
    """The consequence, spelled out: C is gone, so the stale marker reads as
    dangling and the self-healing branch lifts the block."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file, absent from the row", c)
    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )
    engine.execute_merge(c, d)

    engine._record_confirmed_use(orphan)

    assert engine.file_store.load(orphan).tier is Tier.working


def test_a_reindex_closes_the_gap_before_the_merge(engine):
    """The divergence is not durable: the index is derived from the files, so
    re-indexing the source restores the row and the redirect finds it."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file, absent from the row", c)
    engine.builder.index_single(engine.file_store._find_file(orphan))
    assert _sql_marker(engine, orphan) == c, "precondition: the reindex restored the row"
    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )

    engine.execute_merge(c, d)

    assert engine.file_store.load(orphan).superseded_by == d
    assert _sql_marker(engine, orphan) == d


def test_the_opposite_divergence_heals_instead_of_breaking(engine):
    """Marker in the row, absent from the file — the mirror image.  SQL discovery
    finds it, and the markdown pass writes the keeper into the file, so the merge
    leaves the two agreeing.  This is why the SQL-first read is the safe half of
    the pair: it over-reaches into repair, never under-reaches into loss."""
    c = _live(engine, "the consolidation node", "C")
    node_id, _ = engine.remember(CreateNodeRequest(content="marked in the row, absent from the file"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))
    engine.db.conn.execute("UPDATE nodes SET superseded_by = ? WHERE id = ?", (c, node_id))
    engine.db.conn.commit()
    assert engine.file_store.load(node_id).superseded_by is None, "precondition: file has no marker"

    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )
    engine.execute_merge(c, d)

    assert _sql_marker(engine, node_id) == d
    assert engine.file_store.load(node_id).superseded_by == d, "the markdown pass healed the file"

"""Merging a consolidation node carries its sources' supersession markers (#223).

Consolidation writes A/B -> C.  If C is later merged into D, ``execute_merge``
soft-deletes C while A and B still point at it: the marker then reads as
*dangling*, and the next confirmed use promotes A or B even though D still
represents them.  Reported on PR #257 by the maintainer.
"""

from __future__ import annotations

from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, Tier


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
# Two routes, because they answer slightly different questions.  Route 1 reads
# `nodes.superseded_by` out of the index; route 2 opens the files named by the
# derived_from edges leaving the removed node.  The gate reads the *file*, and the
# two can diverge: `_mark_superseded` saves the markdown first and writes the row
# second, so a crash in between leaves a marker only in markdown.  The consolidator
# writes the derived_from edge before that call, so route 2 covers the window.


def _marker_in_markdown_only(engine, content: str, replacement: str, *, edge: bool) -> str:
    """A source whose marker reached the file but not the row — the crash window
    inside _mark_superseded.  *edge* replays the derived_from link the consolidator
    writes one line earlier; without it there is nothing pointing at this file."""
    node_id, _ = engine.remember(CreateNodeRequest(content=content))
    if edge:
        # Created BEFORE the unindexed save: connect() re-indexes, which would
        # otherwise hand the row the very marker this fixture must withhold.
        engine.connect(ConnectRequest(
            source_id=replacement,
            target_id=node_id,
            edge=EdgeType.derived_from,
            weight=1.0,
        ))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    node.superseded_by = replacement
    engine.file_store.save(node)  # deliberately NOT index_single
    assert _sql_marker(engine, node_id) is None, "precondition: the row never saw the marker"
    return node_id


def _merge_into_d(engine, c: str) -> str:
    d = _live(
        engine,
        "the node C is merged into, deliberately much longer so _pick_keeper keeps it",
        "D",
    )
    engine.execute_merge(c, d)
    return d


def test_a_marker_only_in_markdown_is_found_through_the_derived_from_edge(engine):
    """The crash window inside _mark_superseded, reproduced end to end: the row
    never got the marker, so route 1 cannot see this source at all."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file only", c, edge=True)

    d = _merge_into_d(engine, c)

    assert engine.file_store.load(orphan).superseded_by == d


def test_the_row_is_healed_while_it_is_redirected(engine):
    """Route 2 finds a source whose row is still NULL, so the per-id UPDATE has to
    write the marker rather than merely change it — a `WHERE superseded_by = ?`
    update would match nothing and leave the row behind the file forever."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file only", c, edge=True)

    d = _merge_into_d(engine, c)

    assert _sql_marker(engine, orphan) == d


def test_the_recovered_source_stays_blocked(engine):
    """The point of covering the window: without route 2 the stale marker reads as
    dangling once C is gone, and the source promotes back into the whisper tier."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "marked in the file only", c, edge=True)
    _merge_into_d(engine, c)

    engine._record_confirmed_use(orphan)

    assert engine.file_store.load(orphan).tier is Tier.archival


def test_a_derived_from_target_without_a_marker_is_not_redirected(engine):
    """derived_from is a general relationship — the same reason #223 refused to gate
    promotion on it.  Route 2 opens the file to read the marker; the edge only
    decides which files are worth opening.  Without this, every derived_from target
    of the removed node would be marked superseded by the keeper."""
    c = _live(engine, "the consolidation node", "C")
    plain, _ = engine.remember(CreateNodeRequest(content="derived from C, never superseded"))
    engine.connect(ConnectRequest(
        source_id=c, target_id=plain, edge=EdgeType.derived_from, weight=1.0,
    ))

    _merge_into_d(engine, c)

    assert engine.file_store.load(plain).superseded_by is None
    assert _sql_marker(engine, plain) is None


def test_a_derived_from_target_marked_by_someone_else_is_not_redirected(engine):
    """Reachable by the edge, but its marker names a different node.  The criterion
    is the marker's value, not merely that the file carries one."""
    c = _live(engine, "the consolidation node", "C")
    other = _live(engine, "an unrelated consolidation node", "other")
    node_id, _ = engine.remember(CreateNodeRequest(content="derived from C, superseded by other"))
    node = engine.file_store.load(node_id)
    node.superseded_by = other
    engine.builder.index_single(engine.file_store.save(node))
    # The edge is created LAST: index_single wipes every edge touching this node,
    # so building it first would leave the node unreachable by route 2 and this
    # test would pass with the marker check removed.
    engine.connect(ConnectRequest(
        source_id=c, target_id=node_id, edge=EdgeType.derived_from, weight=1.0,
    ))
    assert engine.db.conn.execute(
        "SELECT 1 FROM edges WHERE source_id = ? AND target_id = ? AND edge_type = 'derived_from'",
        (c, node_id),
    ).fetchone(), "precondition: route 2 can actually reach this node"

    _merge_into_d(engine, c)

    assert engine.file_store.load(node_id).superseded_by == other
    assert _sql_marker(engine, node_id) == other


def test_a_marker_with_neither_a_row_nor_an_edge_is_still_missed(engine):
    """The residual boundary, pinned on purpose.  Both routes need *some* trace of
    the source; a marker written outside the consolidator, into the file alone, has
    none.  Nothing in this repository writes one that way — the consolidator is the
    only producer, and it always writes the edge first — so closing this last case
    would cost a full store scan on every merge for a state no code can reach.  A
    change that widens the redirect has to edit this test on purpose."""
    c = _live(engine, "the consolidation node", "C")
    orphan = _marker_in_markdown_only(engine, "no row, no edge", c, edge=False)

    _merge_into_d(engine, c)

    assert engine.file_store.load(orphan).superseded_by == c, "still pointing at the dead node"


def test_the_opposite_divergence_heals_instead_of_breaking(engine):
    """Marker in the row, absent from the file — the mirror image.  Route 1 finds
    it, and the markdown pass writes the keeper into the file, so the merge leaves
    the two agreeing."""
    c = _live(engine, "the consolidation node", "C")
    node_id, _ = engine.remember(CreateNodeRequest(content="marked in the row, absent from the file"))
    node = engine.file_store.load(node_id)
    node.tier = Tier.archival
    engine.builder.index_single(engine.file_store.save(node))
    engine.db.conn.execute("UPDATE nodes SET superseded_by = ? WHERE id = ?", (c, node_id))
    engine.db.conn.commit()
    assert engine.file_store.load(node_id).superseded_by is None, "precondition: file has no marker"

    d = _merge_into_d(engine, c)

    assert _sql_marker(engine, node_id) == d
    assert engine.file_store.load(node_id).superseded_by == d, "the markdown pass healed the file"

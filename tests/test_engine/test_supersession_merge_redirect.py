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

from datetime import datetime, timezone

from ormah.models.node import CreateNodeRequest, NodeType, UpdateNodeRequest


def _create_node(engine, title, content):
    req = CreateNodeRequest(content=content, type=NodeType.fact, title=title, tags=["test"])
    node_id, _ = engine.remember(req, agent_id="test")
    return node_id


def _seed_pair_memo(engine, table, node_a, node_b, result):
    with engine.db.transaction() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {table} (node_a, node_b, result, checked_at) "
            "VALUES (?, ?, ?, ?)",
            (node_a, node_b, result, datetime.now(timezone.utc).isoformat()),
        )


def _count_pair_memo(engine, table):
    return engine.db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _seed_auto_link_checked(engine, node_a, node_b):
    _seed_pair_memo(engine, "auto_link_checked", node_a, node_b, "none")


def _count_auto_link_checked(engine):
    return _count_pair_memo(engine, "auto_link_checked")


# --- auto_link_checked invalidation: the one memo with live readers ---


def test_update_node_invalidates_auto_link_checked(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_auto_link_checked(engine, id_a, id_b)
    assert _count_auto_link_checked(engine) == 1

    engine.update_node(id_a, UpdateNodeRequest(content="Updated content about A"))

    assert _count_auto_link_checked(engine) == 0


def test_update_node_space_edit_still_invalidates_auto_link_checked(engine):
    """A space-only edit never entered update_node's own auto_link clause: the builder's
    fingerprint invalidation is what clears the memo, because the fingerprint bundles space.

    Pins that dropping the conflict-memo branch of update_node — the only branch a space edit
    ever reached — left that behaviour untouched.
    """
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_auto_link_checked(engine, id_a, id_b)
    assert _count_auto_link_checked(engine) == 1

    engine.update_node(id_a, UpdateNodeRequest(space="myproject"))

    assert _count_auto_link_checked(engine) == 0


def test_delete_node_invalidates_auto_link_checked(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_auto_link_checked(engine, id_a, id_b)
    assert _count_auto_link_checked(engine) == 1

    engine.delete_node(id_b)

    assert _count_auto_link_checked(engine) == 0


def test_delete_node_guarded_invalidates_auto_link_checked(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_auto_link_checked(engine, id_a, id_b)
    assert _count_auto_link_checked(engine) == 1

    assert engine.delete_node_guarded(id_b, lambda conn: True) is not None

    assert _count_auto_link_checked(engine) == 0


def test_execute_merge_invalidates_auto_link_checked_for_both_nodes(engine):
    id_a = _create_node(engine, "A", "Short.")
    id_b = _create_node(engine, "B", "This is a much longer description with detail.")
    id_c = _create_node(engine, "C", "Unrelated third node content")

    # A pair involving the removed node (id_a, the shorter one) and a pair involving the
    # kept node (id_b), to prove BOTH sides are invalidated.
    _seed_auto_link_checked(engine, id_a, id_c)
    _seed_auto_link_checked(engine, id_b, id_c)
    assert _count_auto_link_checked(engine) == 2

    engine.execute_merge(id_a, id_b, merged_content="Merged content for kept node.")

    assert _count_auto_link_checked(engine) == 0


# --- the dead Pair memos: no mutation path touches them any more (#11) ---
#
# duplicate_checked and conflict_checked have no reader anywhere (#4). The tables themselves
# are dropped at startup by #12; these assertions go with them. Until then a surviving row is
# the only observable proof that the invalidation deletes were actually removed.


def _seed_dead_memos(engine, node_a, node_b):
    _seed_pair_memo(engine, "duplicate_checked", node_a, node_b, "not_duplicate")
    _seed_pair_memo(engine, "conflict_checked", node_a, node_b, "none")


def _assert_dead_memos_intact(engine, expected):
    assert _count_pair_memo(engine, "duplicate_checked") == expected
    assert _count_pair_memo(engine, "conflict_checked") == expected


def test_update_node_content_edit_does_not_touch_the_dead_memos(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_dead_memos(engine, id_a, id_b)

    engine.update_node(id_a, UpdateNodeRequest(content="Updated content about A"))

    _assert_dead_memos_intact(engine, 1)


def test_update_node_space_or_type_edit_does_not_touch_the_dead_memos(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_dead_memos(engine, id_a, id_b)

    engine.update_node(id_a, UpdateNodeRequest(space="myproject"))
    engine.update_node(id_a, UpdateNodeRequest(type=NodeType.decision))

    _assert_dead_memos_intact(engine, 1)


def test_delete_node_does_not_touch_the_dead_memos(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_dead_memos(engine, id_a, id_b)

    engine.delete_node(id_b)

    _assert_dead_memos_intact(engine, 1)


def test_delete_node_guarded_does_not_touch_the_dead_memos(engine):
    id_a = _create_node(engine, "A", "Some content about A")
    id_b = _create_node(engine, "B", "Some content about B")
    _seed_dead_memos(engine, id_a, id_b)

    assert engine.delete_node_guarded(id_b, lambda conn: True) is not None

    _assert_dead_memos_intact(engine, 1)


def test_execute_merge_does_not_touch_the_dead_memos(engine):
    id_a = _create_node(engine, "A", "Short.")
    id_b = _create_node(engine, "B", "This is a much longer description with detail.")
    id_c = _create_node(engine, "C", "Unrelated third node content")

    _seed_dead_memos(engine, id_a, id_c)
    _seed_dead_memos(engine, id_b, id_c)
    _assert_dead_memos_intact(engine, 2)

    engine.execute_merge(id_a, id_b, merged_content="Merged content for kept node.")

    _assert_dead_memos_intact(engine, 2)

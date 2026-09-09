"""Tests for file store CRUD operations."""

from ormah.models.node import MemoryNode, NodeType, Tier


def test_save_and_load(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        tier=Tier.working,
        source="agent:test",
        content="Test fact content.",
        title="Test fact",
    )

    path = file_store.save(node)
    assert path.exists()
    assert path.suffix == ".md"

    loaded = file_store.load(node.id)
    assert loaded is not None
    assert loaded.id == node.id
    assert loaded.content == "Test fact content."


def test_delete(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="To be deleted.",
    )
    file_store.save(node)
    assert file_store.load(node.id) is not None

    result = file_store.delete(node.id)
    assert result is True
    assert file_store.load(node.id) is None


def test_list_all(file_store):
    for i in range(3):
        node = MemoryNode(
            type=NodeType.fact,
            source="agent:test",
            content=f"Fact number {i}",
        )
        file_store.save(node)

    nodes = file_store.list_all()
    assert len(nodes) == 3


def test_soft_delete_moves_file(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="To be soft deleted.",
        title="Soft delete me",
    )
    path = file_store.save(node)
    assert path.exists()

    result = file_store.soft_delete(node.id)
    assert result is True

    # Original file gone
    assert not path.exists()

    # File exists in deleted/ directory
    deleted_dir = file_store.nodes_dir.parent / "deleted"
    dest = deleted_dir / path.name
    assert dest.exists()


def test_soft_delete_nonexistent_returns_false(file_store):
    result = file_store.soft_delete("nonexistent-id")
    assert result is False


def test_soft_delete_clears_cache(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="Cache test.",
        title="Cache node",
    )
    file_store.save(node)
    assert file_store.load(node.id) is not None

    file_store.soft_delete(node.id)
    assert file_store.load(node.id) is None


def test_soft_deleted_not_in_list_all(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="Listed then gone.",
        title="Listed node",
    )
    file_store.save(node)
    assert len(file_store.list_all()) == 1

    file_store.soft_delete(node.id)
    assert len(file_store.list_all()) == 0


def test_soft_deleted_not_in_list_paths(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="Paths test.",
        title="Paths node",
    )
    file_store.save(node)
    assert len(file_store.list_paths()) == 1

    file_store.soft_delete(node.id)
    assert len(file_store.list_paths()) == 0


def test_touch_access(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        content="Access me.",
        access_count=0,
    )
    file_store.save(node)

    updated = file_store.touch_access(node.id)
    assert updated is not None
    assert updated.access_count == 1


def _colliding_pair() -> tuple[MemoryNode, MemoryNode]:
    """Two nodes with the same type, title and Short id — the residual collision."""
    short = "aaaaaaaa"

    def make(rest: str, content: str) -> MemoryNode:
        return MemoryNode(
            id=f"{short}-{rest}-4000-8000-000000000000",
            type=NodeType.fact,
            source="agent:test",
            title="Same title",
            content=content,
        )

    return make("1111", "First memory."), make("2222", "Second memory.")


def test_save_with_colliding_short_id_does_not_overwrite(file_store):
    first, second = _colliding_pair()

    first_path = file_store.save(first)
    second_path = file_store.save(second)

    assert second_path != first_path
    assert first_path.exists()

    loaded_first = file_store.load(first.id)
    loaded_second = file_store.load(second.id)
    assert loaded_first is not None and loaded_first.content == "First memory."
    assert loaded_second is not None and loaded_second.content == "Second memory."


def test_resaving_a_node_keeps_its_own_file(file_store):
    first, second = _colliding_pair()
    first_path = file_store.save(first)
    second_path = file_store.save(second)

    second.content = "Second memory, edited."
    assert file_store.save(second) == second_path
    assert file_store.save(first) == first_path
    assert len(file_store.list_paths()) == 2


def test_save_without_collision_keeps_todays_filename(file_store):
    node = MemoryNode(
        type=NodeType.fact,
        source="agent:test",
        title="Lonely fact",
        content="No collision.",
    )
    path = file_store.save(node)
    assert path.name == f"fact_lonely-fact_{node.short_id}.md"


def test_colliding_files_keep_the_short_id_suffix(file_store):
    """The lookup globs on the Short id: a widened name that dropped it would hide
    one of two colliding nodes from the ambiguity check."""
    first, second = _colliding_pair()
    file_store.save(first)
    file_store.save(second)

    assert {p.name.rsplit("_", 1)[1] for p in file_store.list_paths()} == {
        f"{first.short_id}.md"
    }
    cold = type(file_store)(file_store.nodes_dir)
    assert cold.load(first.short_id) is None  # ambiguous Short id resolves to nothing

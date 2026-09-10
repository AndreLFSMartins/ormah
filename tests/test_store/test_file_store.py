"""Tests for file store CRUD operations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from ormah.models.node import MemoryNode, NodeType, Tier
from ormah.store.file_store import FileStore


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


def test_save_never_overwrites_a_file_the_lookup_cannot_read(file_store):
    """Every Full id candidate taken by files the lookup cannot confirm: the save
    still gets a path of its own instead of replacing one of them."""
    first, second = _colliding_pair()
    file_store.save(first)
    slug = "same-title"
    parts = second.id.split("-")
    taken = []
    for width in range(len(parts)):
        extra = "-".join(parts[1 : width + 1])
        widened = f"{slug}-{extra}" if extra else slug
        occupied = file_store.nodes_dir / f"fact_{widened}_{second.short_id}.md"
        occupied.write_text("not frontmatter")
        taken.append(occupied)

    path = file_store.save(second)
    assert file_store.load(second.id).content == "Second memory."
    # `path.read_text() != "not frontmatter"` alone stays green when the save
    # overwrites one of the occupied candidates — including the canonical name, which
    # is what the old _path_for returned. Name the survivors instead.
    assert path not in taken
    assert all(p.read_text() == "not frontmatter" for p in taken)


def test_concurrent_saves_from_two_stores_keep_both_nodes(tmp_path):
    """Two FileStores over one directory do not share a lock, so `_path_for` picking a
    free name proves nothing by the time the save publishes. Both stores choose before
    either writes; the publish itself has to reserve the name.
    """
    nodes_dir = tmp_path / "nodes"
    first, second = _colliding_pair()
    stores = [FileStore(nodes_dir), FileStore(nodes_dir)]
    gate = Barrier(2, timeout=5)

    for store in stores:
        choose = store._path_for
        fired: list[bool] = []

        def gated(node, _choose=choose, _fired=fired):
            path = _choose(node)
            if not _fired:  # a retry after a lost race must not re-enter the barrier
                _fired.append(True)
                gate.wait()
            return path

        store._path_for = gated

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda pair: pair[0].save(pair[1]),
                              zip(stores, [first, second])))

    assert len(set(paths)) == 2
    cold = FileStore(nodes_dir)
    assert cold.load(first.id).content == "First memory."
    assert cold.load(second.id).content == "Second memory."
    assert len(cold.list_paths()) == 2

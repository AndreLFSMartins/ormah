"""Tests for eval/whisper/seeder.py."""
from __future__ import annotations
import pytest


@pytest.fixture
def tmp_engine(tmp_path):
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


_CASE = {
    "id": "t-001",
    "memories": [
        {
            "node_id": "aaa-portfact",
            "title": "Port fact",
            "content": "Server runs on port 8787.",
            "type": "fact",
            "tier": "working",
            "space": "ormah",
        },
        {
            "node_id": "bbb-userpref",
            "title": "User preference",
            "content": "User prefers dark themes.",
            "type": "preference",
            "tier": "core",
            "space": None,
        },
    ],
}


class TestSeedCase:
    def test_creates_node_files(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 2

    def test_preserves_node_ids(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        node = tmp_engine.file_store.load("aaa-portfact")
        assert node is not None
        assert node.title == "Port fact"

    def test_clear_removes_previous_nodes(self, tmp_engine):
        from eval.whisper.seeder import seed_case, clear_eval_db
        seed_case(tmp_engine, _CASE)
        clear_eval_db(tmp_engine)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 0

    def test_seed_replaces_prior_case(self, tmp_engine):
        from eval.whisper.seeder import seed_case
        seed_case(tmp_engine, _CASE)
        new_case = {
            "id": "t-002",
            "memories": [
                {"node_id": "ccc-newnode", "title": "New", "content": "New content.", "type": "fact", "tier": "working"},
            ],
        }
        seed_case(tmp_engine, new_case)
        nodes_dir = tmp_engine.file_store.nodes_dir
        files = list(nodes_dir.glob("*.md"))
        assert len(files) == 1
        assert tmp_engine.file_store.load("aaa-portfact") is None
        assert tmp_engine.file_store.load("ccc-newnode") is not None

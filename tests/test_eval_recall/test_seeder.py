import pytest
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from eval.recall.seeder import seed_case, clear_eval_db


@pytest.fixture
def eval_engine(tmp_path):
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


def _make_case(case_id="t-001"):
    return {
        "id": case_id,
        "memories": [
            {
                "node_id": f"{case_id}-mem-0",
                "title": "Test memory A",
                "content": "Content about hybrid search and FTS5",
                "type": "fact",
                "tier": "working",
                "tags": ["search"],
                "space": "testproject",
            },
            {
                "node_id": f"{case_id}-mem-1",
                "title": "Test memory B",
                "content": "Content about vector embeddings",
                "type": "fact",
                "tier": "working",
                "tags": [],
                "space": "testproject",
            },
        ],
        "prompts": [],
    }


def test_seed_inserts_nodes_with_correct_ids(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    node = eval_engine.graph.get_node("t-001-mem-0")
    assert node is not None
    assert node["title"] == "Test memory A"


def test_seed_forces_node_id(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    node = eval_engine.graph.get_node("t-001-mem-0")
    assert node["id"] == "t-001-mem-0"


def test_seed_only_case_nodes_in_db(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 2


def test_clear_removes_all_nodes(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    clear_eval_db(eval_engine)
    count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 0


def test_seed_after_clear_gives_fresh_state(eval_engine):
    case_a = _make_case("a-001")
    case_b = _make_case("b-001")
    seed_case(eval_engine, case_a)
    seed_case(eval_engine, case_b)
    assert eval_engine.graph.get_node("a-001-mem-0") is None
    assert eval_engine.graph.get_node("b-001-mem-0") is not None


def test_seed_indexes_embedding(eval_engine):
    case = _make_case()
    seed_case(eval_engine, case)
    vec_count = eval_engine.db.conn.execute("SELECT COUNT(*) FROM node_vectors").fetchone()[0]
    assert vec_count == 2

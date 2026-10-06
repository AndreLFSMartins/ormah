"""Tests for eval/recall/runner.py."""
from __future__ import annotations
import pytest
from eval.recall.runner import run_eval, EvalResult


def _make_case(case_id, mem_titles, prompt_text, should_inject):
    return {
        "id": case_id,
        "memories": [
            {
                "node_id": f"{case_id}-mem-{i}",
                "title": t,
                "content": f"Content about {t.lower()}",
                "type": "fact",
                "tier": "working",
                "space": "testproject",
            }
            for i, t in enumerate(mem_titles)
        ],
        "prompts": [
            {
                "text": prompt_text,
                "expected": {
                    "should_inject": should_inject,
                    "should_not_inject": [],
                },
            }
        ],
    }


@pytest.fixture
def eval_engine(tmp_path):
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine
    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    yield engine
    engine.shutdown()


def test_run_eval_returns_result(eval_engine):
    case = _make_case(
        "t-001",
        ["SQLite search", "Unrelated memory"],
        "how does search work?",
        ["t-001-mem-0"],
    )
    result = run_eval([case], eval_engine, k=8)
    assert isinstance(result, EvalResult)
    assert len(result.case_results) == 1


def test_run_eval_empty_corpus(eval_engine):
    result = run_eval([], eval_engine, k=8)
    assert result.aggregate["recall"] is None
    assert result.aggregate["precision"] is None
    assert result.case_results == []


def test_run_eval_all_unlabeled(eval_engine):
    case = {
        "id": "unlabeled-001",
        "memories": [
            {"node_id": "u-mem-0", "title": "A", "content": "stuff", "type": "fact", "tier": "working"}
        ],
        "prompts": [
            {"text": "what is X?", "expected": {"should_inject": [], "should_not_inject": []}}
        ],
    }
    result = run_eval([case], eval_engine, k=8)
    assert result.aggregate["recall"] is None


def test_run_eval_case_isolation(eval_engine):
    case_a = _make_case("a-001", ["Fact about apples"], "tell me about apples", ["a-001-mem-0"])
    case_b = _make_case("b-001", ["Fact about oranges"], "tell me about oranges", ["b-001-mem-0"])
    result = run_eval([case_a, case_b], eval_engine, k=8)
    assert len(result.case_results) == 2
    case_b_result = result.case_results[1]
    all_returned_ids = [
        nid
        for pr in case_b_result.get("prompt_results", [])
        for nid in pr.get("all_ranked_ids", [])
    ]
    assert "a-001-mem-0" not in all_returned_ids

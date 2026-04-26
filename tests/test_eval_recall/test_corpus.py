import json
import pytest
from pathlib import Path
from eval.recall.corpus import load_corpus, validate_case, CorpusError


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")


def test_load_golden_case(tmp_path):
    case = {
        "id": "test-001",
        "memories": [
            {"node_id": "test-001-mem-0", "title": "SQLite FTS5", "content": "Uses FTS5", "type": "fact", "tier": "working"}
        ],
        "prompts": [
            {"text": "how does search work?", "expected": {"should_inject": ["test-001-mem-0"], "should_not_inject": []}}
        ]
    }
    f = tmp_path / "golden.jsonl"
    _write_jsonl(f, [case])
    cases = load_corpus(f)
    assert len(cases) == 1
    assert cases[0]["id"] == "test-001"
    assert cases[0]["memories"][0]["node_id"] == "test-001-mem-0"


def test_load_skips_header(tmp_path):
    header = {"_header": True, "generated_at": "2026-01-01", "generator_version": "0.3.0"}
    case = {"id": "syn-001", "memories": [], "prompts": []}
    f = tmp_path / "synthetic.jsonl"
    _write_jsonl(f, [header, case])
    cases = load_corpus(f)
    assert len(cases) == 1
    assert cases[0]["id"] == "syn-001"


def test_load_empty_file(tmp_path):
    f = tmp_path / "golden.jsonl"
    f.write_text("")
    cases = load_corpus(f)
    assert cases == []


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(CorpusError, match="not found"):
        load_corpus(tmp_path / "nonexistent.jsonl")


def test_validate_case_missing_node_id():
    case = {
        "id": "bad-001",
        "memories": [{"title": "no id", "content": "x", "type": "fact", "tier": "working"}],
        "prompts": []
    }
    with pytest.raises(CorpusError, match="node_id"):
        validate_case(case)


def test_validate_case_duplicate_node_ids():
    case = {
        "id": "dup-001",
        "memories": [
            {"node_id": "dup-001-mem-0", "title": "A", "content": "a", "type": "fact", "tier": "working"},
            {"node_id": "dup-001-mem-0", "title": "B", "content": "b", "type": "fact", "tier": "working"},
        ],
        "prompts": []
    }
    with pytest.raises(CorpusError, match="duplicate"):
        validate_case(case)

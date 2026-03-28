"""Tests for eval/whisper/corpus.py."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from eval.whisper.corpus import load_corpus, validate_case, CorpusError, VALID_CATEGORIES


def _write_jsonl(tmp_path, cases):
    f = tmp_path / "test.jsonl"
    f.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    return f


_MEM = {"node_id": "m-1", "title": "T", "content": "C", "type": "fact", "tier": "working"}
_PROMPT = {"text": "q", "category": "factual", "expected": {"should_inject": ["m-1"], "should_suppress": False}}
_VALID = {"id": "w-001", "memories": [_MEM], "prompts": [_PROMPT]}


class TestLoadCorpus:
    def test_loads_cases(self, tmp_path):
        f = _write_jsonl(tmp_path, [_VALID])
        cases = load_corpus(f)
        assert len(cases) == 1
        assert cases[0]["id"] == "w-001"

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "t.jsonl"
        f.write_text(json.dumps(_VALID) + "\n\n" + json.dumps(_VALID) + "\n")
        assert len(load_corpus(f)) == 2

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(CorpusError, match="not found"):
            load_corpus(tmp_path / "missing.jsonl")


class TestValidateCase:
    def test_valid_case_passes(self):
        validate_case(_VALID)  # no exception

    def test_missing_node_id_raises(self):
        bad = {"id": "x", "memories": [{"title": "T"}], "prompts": []}
        with pytest.raises(CorpusError, match="missing 'node_id'"):
            validate_case(bad)

    def test_duplicate_node_id_raises(self):
        bad = {
            "id": "x",
            "memories": [
                {"node_id": "dup", "title": "A", "content": "C", "type": "fact", "tier": "working"},
                {"node_id": "dup", "title": "B", "content": "C", "type": "fact", "tier": "working"},
            ],
            "prompts": [],
        }
        with pytest.raises(CorpusError, match="duplicate node_id"):
            validate_case(bad)

    def test_invalid_category_raises(self):
        bad = {
            "id": "x",
            "memories": [_MEM],
            "prompts": [{"text": "q", "category": "bogus", "expected": {}}],
        }
        with pytest.raises(CorpusError, match="invalid category"):
            validate_case(bad)

    def test_unknown_node_ref_in_should_inject_raises(self):
        bad = {
            "id": "x",
            "memories": [_MEM],
            "prompts": [{"text": "q", "category": "factual", "expected": {"should_inject": ["unknown-id"]}}],
        }
        with pytest.raises(CorpusError, match="unknown node_id"):
            validate_case(bad)

    def test_all_valid_categories_accepted(self):
        for cat in VALID_CATEGORIES:
            case = {
                "id": "x", "memories": [_MEM],
                "prompts": [{"text": "q", "category": cat, "expected": {"should_inject": ["m-1"]}}],
            }
            validate_case(case)  # no exception

"""Tests for eval/relevance/runner.py (the in-context relevance-gate ship gate).

No live provider is exercised here: MemoryEngine._extract_memories_llm is
replaced with a fake so the runner's scoring/guard logic is verified
deterministically. The live-provider run is the ship gate itself
(env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m eval.relevance.runner),
not a unit test.
"""
from __future__ import annotations

import json
from pathlib import Path

from eval.relevance.runner import CORPUS_PATH, MIN_PER_CLASS, _labels_for, main


class _FakeEngine:
    """Stands in for MemoryEngine; only needs _extract_memories_llm."""

    def __init__(self, labels_by_id: dict[str, list[str] | str]):
        self._labels_by_id = labels_by_id

    def _extract_memories_llm(self, snippet: str):
        result = self._labels_by_id[snippet]
        if isinstance(result, str):  # simulate an extractor error string
            return result
        return [{"provenance": label} for label in result]


def _write_corpus(tmp_path: Path, product_count: int, material_count: int) -> Path:
    cases = []
    for i in range(product_count):
        cases.append({"id": f"prod-{i}", "label": "product", "snippet": f"prod-snippet-{i}"})
    for i in range(material_count):
        cases.append({"id": f"mat-{i}", "label": "material", "snippet": f"mat-snippet-{i}"})
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    return path


# --- _labels_for ---------------------------------------------------------

def test_labels_for_returns_provenance_list():
    engine = _FakeEngine({"snippet-a": ["product"]})
    assert _labels_for(engine, "snippet-a") == ["product"]


def test_labels_for_returns_multiple_labels():
    engine = _FakeEngine({"snippet-b": ["material", "product"]})
    assert _labels_for(engine, "snippet-b") == ["material", "product"]


def test_labels_for_returns_empty_on_extractor_error_string():
    engine = _FakeEngine({"snippet-c": "LLM extraction failed."})
    assert _labels_for(engine, "snippet-c") == []


# --- main(): corpus-size guard -------------------------------------------

def test_main_fails_corpus_too_small(tmp_path, capsys):
    corpus_path = _write_corpus(tmp_path, product_count=5, material_count=5)

    def _unused_engine_factory():
        raise AssertionError("engine must not be constructed when corpus guard fails")

    rc = main(engine_factory=_unused_engine_factory, corpus_path=corpus_path)

    assert rc == 2
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "corpus too small" in out
    assert "product=5" in out
    assert "material=5" in out


# --- main(): scoring -------------------------------------------------------

def test_main_passes_when_both_thresholds_met(tmp_path, capsys):
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    labels_by_id.update({f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)})
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "product_preserved=1.000" in out
    assert "material_dropped=1.000" in out
    assert "PASS" in out
    assert rc == 0


def test_main_fails_when_product_preserved_below_threshold(tmp_path, capsys):
    # 20 product cases; only 19/20 (0.95) come back labeled "product" -> below 0.98.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    labels_by_id["prod-snippet-0"] = ["material"]  # dropped/mislabeled
    labels_by_id.update({f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)})
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "FAIL" in out
    assert rc == 1


def test_main_fails_when_material_dropped_below_threshold(tmp_path, capsys):
    # 20 material cases; only 15/20 (0.75) labeled "material" -> below 0.80.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    mat_labels = {f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)}
    for i in range(5):
        mat_labels[f"mat-snippet-{i}"] = ["product"]  # over-preserved / not dropped
    labels_by_id.update(mat_labels)
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "FAIL" in out
    assert rc == 1


def test_main_treats_extractor_error_as_no_labels(tmp_path, capsys):
    # An extraction error for a product case means it is not preserved.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    labels_by_id["prod-snippet-0"] = "LLM extraction failed."
    labels_by_id.update({f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)})
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "product_preserved=0.950" in out
    assert "FAIL" in out
    assert rc == 1


# --- main(): mixed-label scoring (council fix) ------------------------------

def test_main_product_case_with_mixed_labels_is_not_preserved(tmp_path, capsys):
    # A product case that ALSO emits a "material" candidate must not count as preserved:
    # the extractor mislabeled at least one candidate for this snippet.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    labels_by_id["prod-snippet-0"] = ["material", "product"]
    labels_by_id.update({f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)})
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "product_preserved=0.950" in out
    assert "FAIL" in out
    assert rc == 1


def test_main_material_case_with_mixed_labels_is_not_dropped(tmp_path, capsys):
    # 20 material cases; 5/20 also emit a "product" candidate alongside "material" -> those
    # must NOT count as dropped (gate only drops when "material" is the only label present),
    # pushing material_dropped to 0.75, below the 0.80 threshold.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["product"] for i in range(MIN_PER_CLASS)}
    mat_labels = {f"mat-snippet-{i}": ["material"] for i in range(MIN_PER_CLASS)}
    for i in range(5):
        mat_labels[f"mat-snippet-{i}"] = ["material", "product"]
    labels_by_id.update(mat_labels)
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "material_dropped=0.750" in out
    assert "FAIL" in out
    assert rc == 1


def test_main_all_mixed_corpus_fails(tmp_path, capsys):
    # Every case (product and material) emits BOTH labels: the old scorer false-passed
    # both metrics on this corpus; the fixed scorer must fail both.
    corpus_path = _write_corpus(tmp_path, product_count=MIN_PER_CLASS, material_count=MIN_PER_CLASS)
    labels_by_id = {f"prod-snippet-{i}": ["material", "product"] for i in range(MIN_PER_CLASS)}
    labels_by_id.update(
        {f"mat-snippet-{i}": ["material", "product"] for i in range(MIN_PER_CLASS)}
    )
    engine = _FakeEngine(labels_by_id)

    rc = main(engine_factory=lambda: engine, corpus_path=corpus_path)

    out = capsys.readouterr().out
    assert "product_preserved=0.000" in out
    assert "material_dropped=0.000" in out
    assert "FAIL" in out
    assert rc == 1


# --- seed corpus sanity (no extraction — just structural checks) ---------

def test_seed_corpus_meets_minimum_size_and_has_ambiguous_pairs():
    cases = json.loads(CORPUS_PATH.read_text())
    product = [c for c in cases if c["label"] == "product"]
    material = [c for c in cases if c["label"] == "material"]

    assert len(product) >= MIN_PER_CLASS
    assert len(material) >= MIN_PER_CLASS

    ambiguous_ids = [c["id"] for c in cases if "amb" in c["id"]]
    # each ambiguous pair contributes one product + one material case
    assert len(ambiguous_ids) >= 6

    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for c in cases:
        assert c["snippet"].strip(), f"case {c['id']} has an empty snippet"

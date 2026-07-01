import json
from eval.recall.report import format_report, write_results, load_previous_run


def _make_aggregate(recall=0.81, precision=0.74):
    return {
        "recall": recall, "precision": precision, "f1": 0.77, "mrr": 0.83,
        "false_negative_rate": 0.19, "injection_rate": 0.91,
        "case_count": 42, "labeled_prompt_count": 42,
    }


def _make_case_results():
    return [
        {"case_id": "golden-007", "prompt_results": [
            {"prompt": "how do we handle auth tokens?", "should_inject": ["m0"], "all_ranked_ids": [], "metrics": {"recall": 0.0, "precision": 0.0, "f1": 0.0, "mrr": 0.0, "false_negative_rate": 1.0, "injection_fired": False}}
        ]},
    ]


def test_format_report_contains_metrics():
    agg = _make_aggregate()
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=None)
    assert "Recall@8" in report
    assert "0.81" in report
    assert "Precision@8" in report


def test_format_report_shows_regression():
    agg = _make_aggregate(recall=0.75)
    prev = _make_aggregate(recall=0.81)
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=prev)
    assert "▼" in report


def test_format_report_suppresses_noise():
    agg = _make_aggregate(recall=0.811)
    prev = _make_aggregate(recall=0.810)
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=prev)
    assert "→" in report


def test_format_report_shows_worst_cases():
    agg = _make_aggregate()
    report = format_report(agg, _make_case_results(), k=8, corpus_label="golden", previous=None)
    assert "golden-007" in report


def test_write_results_creates_files(tmp_path):
    agg = _make_aggregate()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_results(agg, _make_case_results(), results_dir=results_dir, corpus_label="golden", k=8)
    assert (results_dir / "latest.json").exists()
    assert (results_dir / "history.jsonl").exists()


def test_write_results_appends_history(tmp_path):
    agg = _make_aggregate()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_results(agg, [], results_dir=results_dir, corpus_label="golden", k=8)
    write_results(agg, [], results_dir=results_dir, corpus_label="golden", k=8)
    lines = (results_dir / "history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_load_previous_run_returns_none_when_no_history(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    assert load_previous_run(results_dir) is None


def test_load_previous_run_returns_last_entry(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    history = results_dir / "history.jsonl"
    history.write_text(
        json.dumps({"aggregate": {"recall": 0.75}, "corpus_label": "golden"}) + "\n" +
        json.dumps({"aggregate": {"recall": 0.80}, "corpus_label": "golden"}) + "\n"
    )
    prev = load_previous_run(results_dir, corpus_label="golden")
    assert prev["aggregate"]["recall"] == 0.80

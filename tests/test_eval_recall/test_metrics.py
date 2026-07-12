import pytest
from eval.recall.metrics import recall_at_k, precision_at_k, f1_at_k, mrr, false_negative_rate, compute_case_metrics


def test_recall_perfect():
    assert recall_at_k(["a", "b"], ["a", "b", "c", "d"], k=8) == 1.0


def test_recall_partial():
    assert recall_at_k(["a", "b"], ["a", "c", "d", "e"], k=8) == pytest.approx(0.5)


def test_recall_none_injected():
    assert recall_at_k(["a", "b"], ["c", "d"], k=8) == 0.0


def test_recall_empty_should_inject():
    assert recall_at_k([], ["a", "b"], k=8) is None


def test_precision_perfect():
    assert precision_at_k(["a", "b"], ["a", "b"], k=2) == 1.0


def test_precision_zero():
    assert precision_at_k(["a", "b"], ["c", "d"], k=2) == 0.0


def test_precision_empty_results():
    assert precision_at_k(["a"], [], k=8) == 0.0


def test_precision_empty_should_inject():
    assert precision_at_k([], ["a", "b"], k=8) is None


def test_f1_perfect():
    assert f1_at_k(["a"], ["a"], k=8) == pytest.approx(1.0)


def test_f1_zero():
    assert f1_at_k(["a"], ["b"], k=8) == pytest.approx(0.0)


def test_mrr_first_result_relevant():
    assert mrr(["a", "b"], ["a", "c", "d"]) == pytest.approx(1.0)


def test_mrr_second_result_relevant():
    assert mrr(["a", "b"], ["c", "a", "d"]) == pytest.approx(0.5)


def test_mrr_no_relevant():
    assert mrr(["a"], ["b", "c"]) == pytest.approx(0.0)


def test_mrr_empty_should_inject():
    assert mrr([], ["a", "b"]) is None


def test_false_negative_rate_all_missed():
    assert false_negative_rate(["a", "b"], ["c", "d"], k=8) == pytest.approx(1.0)


def test_false_negative_rate_none_missed():
    assert false_negative_rate(["a", "b"], ["a", "b"], k=8) == pytest.approx(0.0)


def test_compute_case_metrics_returns_all_keys():
    result = compute_case_metrics(
        should_inject=["a", "b"],
        ranked_ids=["a", "c", "d", "b"],
        injection_gate=0.55,
        ranked_scores=[0.9, 0.8, 0.7, 0.6],
        k=8,
    )
    for key in ["recall", "precision", "f1", "mrr", "false_negative_rate", "injection_fired"]:
        assert key in result


def test_injection_fired_false_when_gate_filters_all():
    result = compute_case_metrics(
        should_inject=["a"],
        ranked_ids=["a", "b"],
        injection_gate=0.99,
        ranked_scores=[0.5, 0.4],
        k=8,
    )
    assert result["injection_fired"] is False


def test_false_positive_present_none_without_negative_labels():
    result = compute_case_metrics(
        should_inject=["a"],
        ranked_ids=["a", "b"],
        injection_gate=0.45,
        ranked_scores=[0.9, 0.8],
        k=8,
    )
    assert result["false_positive_present"] is None


def test_false_positive_present_detects_forbidden_node_in_top_k():
    result = compute_case_metrics(
        should_inject=["a"],
        ranked_ids=["a", "bad"],
        injection_gate=0.45,
        ranked_scores=[0.9, 0.8],
        k=8,
        should_not_inject=["bad"],
    )
    assert result["false_positive_present"] is True


def test_negative_only_case_scores_false_positive_without_positive_metrics():
    result = compute_case_metrics(
        should_inject=[],
        ranked_ids=["x", "y"],
        injection_gate=0.45,
        ranked_scores=[0.9, 0.8],
        k=8,
        should_not_inject=["z"],
    )
    assert result["recall"] is None
    assert result["false_positive_present"] is False

"""The heuristic detector places matches on the #218 ordinal ladder."""

import pytest

from ormah import signal_strength as ss
from ormah.background.session_watcher import _node_usage_evidence


def _row(node_id="a1b2c3d4-dead-beef-0000-000000000000", title="", content="", prompt_text=""):
    """_node_usage_evidence reads its row purely by key, so a dict is a valid row."""
    return {"node_id": node_id, "title": title, "content": content, "prompt_text": prompt_text}


def test_node_id_match_takes_the_top_heuristic_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(content="anything"), "As memory a1b2c3d4 records, we chose X."
    )
    assert referenced
    assert evidence["match"] == "node_id"
    assert strength == ss.VERBATIM_NODE_ID


def test_title_match_takes_the_title_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(
            title="Transcript watcher mines feedback usage",
            content="Some unrelated body text goes here.",
        ),
        "The transcript watcher mines feedback usage, as noted.",
    )
    assert referenced
    assert evidence["match"] == "title"
    assert strength == ss.VERBATIM_TITLE


def test_sentence_match_takes_the_sentence_rung():
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="T", content="The consolidator summarizes from full source content."),
        "Recall that the consolidator summarizes from full source content today.",
    )
    assert referenced
    assert evidence["match"] == "sentence"
    assert strength == ss.VERBATIM_SENTENCE


def test_token_overlap_varies_with_its_ratio():
    """The defect #218 names: every token_overlap match used to report exactly 0.85."""
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="Q", content="quantum entanglement decoherence topology manifold"),
        "We should consider decoherence, then topology, then the manifold, "
        "and finally quantum entanglement in that order.",
    )
    assert referenced
    assert evidence["match"] == "token_overlap"
    assert evidence["overlap_ratio"] == pytest.approx(1.0)
    assert strength == pytest.approx(ss.token_overlap_strength(1.0))
    assert strength != 0.85


def test_no_match_carries_no_strength():
    referenced, strength, evidence = _node_usage_evidence(
        _row(title="Z", content="alpha beta gamma delta"), "Completely unrelated prose here."
    )
    assert not referenced
    assert evidence["match"] == "none"
    assert strength == 0.0


def test_every_heuristic_rung_sits_inside_its_band():
    """The verbatim rungs must stay above the judge band, the overlap rung below implicit."""
    assert ss.VERBATIM_SENTENCE > ss.JUDGE_HI
    assert ss.OVERLAP_FLOOR + ss.OVERLAP_SPAN < ss.IMPLICIT

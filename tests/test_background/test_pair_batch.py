"""Issue #87: pair batching — settings, timeout hint, batch module."""
import json

from ormah.background.llm import pair_batch
from ormah.config import Settings


def test_batching_settings_defaults(tmp_path):
    s = Settings(memory_dir=tmp_path)
    assert s.maintenance_pairs_per_call == 1          # K=1 -> legacy flow untouched
    assert s.maintenance_timeout_per_pair_seconds == 10
    # per-job K overrides (council C3): 0 = fall back to the global K
    assert s.auto_link_pairs_per_call == 0
    assert s.duplicate_check_pairs_per_call == 0
    assert s.conflict_check_pairs_per_call == 0
    # caps default to CURRENT-equivalent bounds (council I1): 0 = unbounded
    assert s.auto_link_max_pairs_per_run == 0
    assert s.duplicate_check_max_pairs_per_run == 0
    assert s.conflict_check_max_pairs_per_run == 10000   # today's exact bound


# --- pair_batch.judge_pairs (Task 05) ---

def _settings(tmp_path, k):
    return Settings(memory_dir=tmp_path, maintenance_pairs_per_call=k,
                    llm_timeout_seconds=60, maintenance_timeout_per_pair_seconds=10)


PAIRS = [{"id": i} for i in range(4)]
PAIRS5 = [{"id": i} for i in range(5)]
PAIRS8 = [{"id": i} for i in range(8)]
RENDER = lambda p: f"pair-{p['id']}"       # noqa: E731
INSTR = "JUDGE THE PAIR"


def test_k1_is_a_pure_map_over_judge_single(tmp_path, monkeypatch):
    monkeypatch.setattr(pair_batch, "llm_generate",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no batch call at K=1")))
    out = pair_batch.judge_pairs(_settings(tmp_path, 1), INSTR, PAIRS, RENDER,
                                 judge_single=lambda p: {"ok": p["id"]})
    assert out == [{"ok": 0}, {"ok": 1}, {"ok": 2}, {"ok": 3}]


def test_explicit_k_overrides_settings(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_generate(settings, prompt, json_mode=True, **kw):
        calls["n"] += 1
        n = prompt.count("### Pair ")
        return json.dumps({"verdicts": [{"pair_id": i, "v": i} for i in range(n)]})

    monkeypatch.setattr(pair_batch, "llm_generate", fake_generate)
    out = pair_batch.judge_pairs(_settings(tmp_path, 1), INSTR, PAIRS, RENDER,
                                 judge_single=lambda p: {"single": True}, k=4)
    assert calls["n"] == 1 and [v["v"] for v in out] == [0, 1, 2, 3]


def test_valid_batch_applies_all_verdicts(tmp_path, monkeypatch):
    prompts = []

    def fake_generate(settings, prompt, json_mode=True, **kw):
        prompts.append((prompt, kw.get("timeout_hint_seconds")))
        return json.dumps({"verdicts": [{"pair_id": i, "v": i} for i in range(4)]})

    monkeypatch.setattr(pair_batch, "llm_generate", fake_generate)
    out = pair_batch.judge_pairs(_settings(tmp_path, 4), INSTR, PAIRS, RENDER,
                                 judge_single=lambda p: {"single": True})
    assert [v["v"] for v in out] == [0, 1, 2, 3]
    assert prompts[0][1] == 60 + 10 * 4          # base + per_pair * K
    assert INSTR in prompts[0][0] and "pair-3" in prompts[0][0]


def test_batch_prompt_repeats_required_pair_id_next_to_each_pair():
    prompt = pair_batch.build_batch_prompt("INSTRUCTIONS", ["alpha", "beta"])

    assert (
        '### Pair 0\nRequired field in this pair\'s verdict object: {"pair_id": 0}\nalpha'
        in prompt
    )
    assert (
        '### Pair 1\nRequired field in this pair\'s verdict object: {"pair_id": 1}\nbeta'
        in prompt
    )


def test_zero_usable_pair_ids_are_unusable_and_log_received_ids(caplog):
    raw = json.dumps({"verdicts": [
        {"value": "missing"},
        {"pair_id": 99, "value": "outside"},
        {"pair_id": [], "value": "wrong-type"},
    ]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0, 1})

    # ZERO_USABLE, not None: the payload parsed fine, so bisecting it is bounded.
    assert out is pair_batch.ZERO_USABLE
    assert any(
        "no usable pair_id" in message
        and "expected=[0, 1]" in message
        and "received=[None, 99, '<list>']" in message
        for message in caplog.messages
    )


def test_partial_valid_verdicts_stay_partial_and_log_discarded_ids(caplog):
    raw = json.dumps({"verdicts": [
        {"pair_id": 1, "value": "kept"},
        {"pair_id": 99, "value": "outside"},
        {"pair_id": True, "value": "bool-alias"},
        {"pair_id": 1.0, "value": "float-alias"},
        {"pair_id": {}, "value": "wrong-type"},
    ]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0, 1})

    assert out == {1: {"pair_id": 1, "value": "kept"}}
    assert any(
        "discarded unusable pair_id" in message
        and "received=[1, 99, True, 1.0, '<dict>']" in message
        for message in caplog.messages
    )


def test_duplicate_pair_ids_are_ambiguous_and_log_diagnostics(caplog):
    raw = json.dumps({"verdicts": [
        {"pair_id": 0, "value": "first"},
        {"pair_id": 0, "value": "second"},
        {"pair_id": 0, "value": "third"},
        {"pair_id": 1, "value": "kept"},
    ]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0, 1})

    assert out == {1: {"pair_id": 1, "value": "kept"}}
    assert any(
        "discarded ambiguous duplicate pair_id" in message
        and "expected=[0, 1]" in message
        and "received=[0, 0, 0, 1]" in message
        for message in caplog.messages
    )


def test_diagnostics_do_not_log_textual_or_container_pair_id_contents(caplog):
    secret = "PAIR_ID_SECRET_1234567890"
    nested = ["CONTAINER_SECRET", {"still": "secret"}]
    mapping = {"MAP_SECRET": "sensitive"}
    raw = json.dumps({"verdicts": [
        {"pair_id": secret},
        {"pair_id": nested},
        {"pair_id": mapping},
        {"pair_id": None},
        {"pair_id": 99},
    ]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0, 1})

    assert out is pair_batch.ZERO_USABLE
    messages = "\n".join(caplog.messages)
    assert secret not in messages
    assert "CONTAINER_SECRET" not in messages
    assert "MAP_SECRET" not in messages
    assert "<str len=25>" in messages
    assert "<list>" in messages and "<dict>" in messages
    assert "None" in messages and "99" in messages


def test_diagnostics_do_not_log_abnormally_large_invalid_integer_pair_id(caplog):
    huge_digits = "9" * 4000
    raw = json.dumps({"verdicts": [{"pair_id": int(huge_digits)}]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0, 1})

    assert out is pair_batch.ZERO_USABLE
    messages = "\n".join(caplog.messages)
    assert huge_digits not in messages
    assert "<int digits=4000>" in messages


def test_numeric_pair_id_beyond_python_limit_is_unparseable():
    raw = '{"verdicts": [{"pair_id": ' + ("9" * 5000) + "}]}"

    assert pair_batch.parse_batch_verdicts(raw, {0, 1}) is None


def test_zero_usable_repr_is_readable():
    assert repr(pair_batch.ZERO_USABLE) == "ZERO_USABLE"


def test_parseable_payload_with_non_list_verdicts_is_unparseable():
    raw = json.dumps({"verdicts": {"pair_id": 0}})

    assert pair_batch.parse_batch_verdicts(raw, {0}) is None


def test_non_dict_verdict_item_logs_only_its_type(caplog):
    secret = "NON_DICT_VERDICT_SECRET"
    raw = json.dumps({"verdicts": [secret]})

    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.parse_batch_verdicts(raw, {0})

    assert out is pair_batch.ZERO_USABLE
    messages = "\n".join(caplog.messages)
    assert secret not in messages
    assert "received=['<str>']" in messages


def test_empty_verdict_list_respects_expected_ids():
    raw = json.dumps({"verdicts": []})
    assert pair_batch.parse_batch_verdicts(raw, {0}) is pair_batch.ZERO_USABLE
    assert pair_batch.parse_batch_verdicts(raw, set()) == {}


def test_partial_verdicts_leave_missing_as_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pair_batch, "llm_generate",
                        lambda *a, **k: json.dumps({"verdicts": [{"pair_id": 1, "v": 1}]}))
    out = pair_batch.judge_pairs(_settings(tmp_path, 4), INSTR, PAIRS, RENDER,
                                 judge_single=lambda p: {"single": True})
    assert out[1] == {"pair_id": 1, "v": 1}
    assert out[0] is None and out[2] is None and out[3] is None


def test_zero_usable_then_partial_probe_single_judges_only_missing(tmp_path, monkeypatch):
    batch_sizes = []
    singles = []

    def staged_batch(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        if len(batch_sizes) == 1:
            return json.dumps({"verdicts": [{"v": i} for i in range(n)]})
        if len(batch_sizes) == 2:
            return json.dumps({"verdicts": [{"pair_id": 0, "v": 0}]})
        return json.dumps({"verdicts": [{"pair_id": i, "v": i} for i in range(n)]})

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", staged_batch)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 4), INSTR, PAIRS, RENDER, judge_single,
    )

    assert batch_sizes == [4, 2, 2]
    assert singles == [1]
    assert out == [
        {"pair_id": 0, "v": 0}, {"single": 1},
        {"pair_id": 0, "v": 0}, {"pair_id": 1, "v": 1},
    ]


def test_zero_usable_then_duplicate_probe_judges_ambiguous_indices(tmp_path, monkeypatch):
    batch_sizes = []
    singles = []

    def staged_batch(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        if len(batch_sizes) == 1:
            return json.dumps({"verdicts": [{"v": i} for i in range(n)]})
        if len(batch_sizes) == 2:
            return json.dumps({"verdicts": [
                {"pair_id": 0, "v": "first"}, {"pair_id": 0, "v": "duplicate"},
            ]})
        return json.dumps({"verdicts": [{"pair_id": i, "v": i} for i in range(n)]})

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", staged_batch)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 4), INSTR, PAIRS, RENDER, judge_single,
    )

    assert batch_sizes == [4, 2, 2]
    assert singles == [0, 1]
    assert out == [
        {"single": 0}, {"single": 1},
        {"pair_id": 0, "v": 0}, {"pair_id": 1, "v": 1},
    ]


def test_zero_usable_pair_ids_probe_one_level_then_judge_singles(tmp_path, monkeypatch, caplog):
    """Council R2: zero-usable gets ONE half-size probe, never the full tree."""
    batch_sizes = []
    singles = []

    def no_ids(*args, **kwargs):
        prompt = args[1]
        n = prompt.count("### Pair ")
        batch_sizes.append(n)
        return json.dumps({"verdicts": [{"v": i} for i in range(n)]})

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", no_ids)
    with caplog.at_level("WARNING", logger=pair_batch.__name__):
        out = pair_batch.judge_pairs(
            _settings(tmp_path, 8), INSTR, PAIRS8, RENDER, judge_single,
        )

    # K + 3 = 11 LLM calls: 3 batch + 8 singles. The full ladder would be
    # [8, 4, 2, 2, 4, 2, 2] = 7 batch calls (2K-1 = 15 total).
    assert batch_sizes == [8, 4, 4]
    assert singles == [0, 1, 2, 3, 4, 5, 6, 7]
    assert out == [{"single": i} for i in range(8)]
    assert any("no usable pair_id" in message for message in caplog.messages)
    assert any("judging 4 pairs individually" in message for message in caplog.messages)


def test_zero_usable_then_unparseable_children_respect_probe_bound(tmp_path, monkeypatch):
    batch_sizes = []
    singles = []

    def staged_batch(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        if len(batch_sizes) == 1:
            return json.dumps({"verdicts": [{"v": i} for i in range(n)]})
        return "NOT JSON {{{"

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", staged_batch)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 8), INSTR, PAIRS8, RENDER, judge_single,
    )

    assert batch_sizes == [8, 4, 4]
    assert singles == list(range(8))
    assert out == [{"single": i} for i in range(8)]
    assert len(batch_sizes) + len(singles) == 11


def test_zero_usable_k5_probes_one_level_then_judges_all_singles(tmp_path, monkeypatch):
    batch_sizes = []
    singles = []

    def no_ids(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        return json.dumps({"verdicts": [{"value": i} for i in range(n)]})

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", no_ids)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 5), INSTR, PAIRS5, RENDER, judge_single,
    )

    assert batch_sizes == [5, 2, 3]
    assert singles == [0, 1, 2, 3, 4]
    assert out == [{"single": i} for i in range(5)]


def test_zero_usable_k2_uses_singles_without_batching_singletons(tmp_path, monkeypatch):
    batch_sizes = []
    singles = []

    def no_ids(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        return json.dumps({"verdicts": [{"value": i} for i in range(n)]})

    def judge_single(pair):
        singles.append(pair["id"])
        return {"single": pair["id"]}

    monkeypatch.setattr(pair_batch, "llm_generate", no_ids)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 2), INSTR, PAIRS[:2], RENDER, judge_single,
    )

    assert batch_sizes == [2]
    assert singles == [0, 1]
    assert out == [{"single": 0}, {"single": 1}]


def test_zero_usable_single_failure_aborts_remaining_bisect_halves_and_chunks(
    tmp_path, monkeypatch,
):
    batch_sizes = []
    singles = []

    def no_ids(*args, **kwargs):
        n = args[1].count("### Pair ")
        batch_sizes.append(n)
        return json.dumps({"verdicts": [{"value": i} for i in range(n)]})

    def unavailable_single(pair):
        singles.append(pair["id"])
        return None

    monkeypatch.setattr(pair_batch, "llm_generate", no_ids)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 4), INSTR, PAIRS8, RENDER, unavailable_single,
    )

    assert batch_sizes == [4, 2]
    assert singles == [0]
    assert out == [None] * 8


def test_unparseable_output_still_bisects_the_full_ladder(tmp_path, monkeypatch):
    """The bound applies to ZERO_USABLE only — unparseable keeps today's tree."""
    batch_sizes = []

    def not_json(*args, **kwargs):
        batch_sizes.append(args[1].count("### Pair "))
        return "NOT JSON {{{"

    monkeypatch.setattr(pair_batch, "llm_generate", not_json)
    out = pair_batch.judge_pairs(
        _settings(tmp_path, 8), INSTR, PAIRS8, RENDER,
        judge_single=lambda p: {"single": p["id"]},
    )

    assert batch_sizes == [8, 4, 2, 2, 4, 2, 2]      # K-1 = 7 internal nodes
    assert out == [{"single": i} for i in range(8)]


def test_parse_failure_bisects_to_single(tmp_path, monkeypatch):
    monkeypatch.setattr(pair_batch, "llm_generate", lambda *a, **k: "NOT JSON {{{")
    singles = []

    def judge_single(p):
        singles.append(p["id"])
        return {"single": p["id"]}

    out = pair_batch.judge_pairs(_settings(tmp_path, 4), INSTR, PAIRS, RENDER, judge_single)
    assert singles == [0, 1, 2, 3]               # ladder bottomed out per pair
    assert [v["single"] for v in out] == [0, 1, 2, 3]


def test_llm_unavailable_aborts_remaining_chunks(tmp_path, monkeypatch):
    """Council C1: an outage must not iterate the whole collected list."""
    calls = {"n": 0}

    def fake_generate(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(pair_batch, "llm_generate", fake_generate)
    out = pair_batch.judge_pairs(_settings(tmp_path, 2), INSTR, PAIRS, RENDER,
                                 judge_single=lambda p: {"single": True})
    assert out == [None, None, None, None]
    assert calls["n"] == 1                        # chunk 1 fails -> chunk 2 never attempted

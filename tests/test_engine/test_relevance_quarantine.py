from ormah.engine import relevance_quarantine as q


def test_record_and_iter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "quarantine.jsonl")
    q.record_dropped(None, content="the requests lib raises Timeout", title="requests Timeout",
                     node_type="fact", space="proj", provider="claude_cli", model="haiku",
                     dropped_at="2026-07-20T00:00:00+00:00")
    rows = list(q.iter_dropped(None))
    assert len(rows) == 1
    r = rows[0]
    assert r["content"] == "the requests lib raises Timeout"
    assert r["label"] == "material"
    assert r["provider"] == "claude_cli"
    assert len(r["prompt_version"]) == 12


def test_iter_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "missing.jsonl")
    assert list(q.iter_dropped(None)) == []

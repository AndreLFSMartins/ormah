import json
import subprocess
from pathlib import Path
from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude_cli_envelope.json"


def _fake_run(stdout="", returncode=0, raises=None):
    def run(argv, **kwargs):
        run.argv, run.kwargs = argv, kwargs
        if raises:
            raise raises
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="err")
    return run


def test_prompt_goes_on_stdin_not_argv(monkeypatch):
    run = _fake_run(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCliAdapter(model="haiku").generate("SECRET transcript text")
    assert "SECRET transcript text" not in run.argv
    assert run.kwargs["input"] == "SECRET transcript text"


def test_generate_parses_result_from_envelope(monkeypatch):
    envelope = json.dumps({"type": "result", "result": '{"memories": []}'})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=envelope))
    assert ClaudeCliAdapter(model="haiku").generate("hi") == '{"memories": []}'


def test_argv_pins_model_and_json_output(monkeypatch):
    run = _fake_run(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi")
    assert run.argv[0] == "/bin/claude" and "-p" in run.argv
    assert run.argv[run.argv.index("--model") + 1] == "haiku"
    assert run.argv[run.argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in run.argv
    assert run.argv[run.argv.index("--settings") + 1] == '{"hooks":{}}'


def test_returns_none_on_is_error_envelope(monkeypatch):
    envelope = json.dumps({
        "type": "result", "is_error": True,
        "subtype": "error_during_execution", "result": "boom",
    })
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=envelope))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_argv_denies_all_tools(monkeypatch):
    run = _fake_run(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCliAdapter(model="haiku").generate("hi")
    assert run.argv[run.argv.index("--allowed-tools") + 1] == ""


def test_child_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    run = _fake_run(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCliAdapter(model="haiku").generate("hi")
    assert "ANTHROPIC_API_KEY" not in run.kwargs["env"]


def test_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="", returncode=2))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        _fake_run(raises=subprocess.TimeoutExpired(cmd="claude", timeout=1)),
    )
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="not json"))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_concurrency_is_bounded(monkeypatch):
    import threading
    a = ClaudeCliAdapter(model="haiku", max_concurrency=1)
    inside = []

    def run(argv, **kwargs):
        inside.append(1)
        assert sum(inside) <= 1, "more than max_concurrency subprocesses ran at once"
        inside.pop()
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"result": "ok"}), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    threads = [threading.Thread(target=lambda: a.generate("hi")) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_contract_real_envelope_fixture():
    envelope = json.loads(FIXTURE.read_text())
    assert isinstance(envelope.get("result"), str)

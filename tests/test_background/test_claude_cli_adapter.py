import json
import subprocess
import tempfile
from pathlib import Path

import pytest

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
    settings = json.loads(run.argv[run.argv.index("--settings") + 1])
    assert settings["disableAllHooks"] is True


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
    # Tool denial is via --settings permissions (NOT --allowed-tools "", which is inert under an
    # inherited defaultMode:bypassPermissions). defaultMode "default" escapes the inherited
    # bypass; allow [] drops inherited allow rules; deny lists the built-in tools by bare name
    # (a "*" glob is rejected as invalid and would discard the whole block -> fail-open).
    perms = json.loads(run.argv[run.argv.index("--settings") + 1])["permissions"]
    assert perms["defaultMode"] == "default"
    assert perms["allow"] == []
    assert {"Read", "Bash", "Write", "Edit"} <= set(perms["deny"])
    # Do not inherit the user's bypassPermissions at the CLI level either.
    assert run.argv[run.argv.index("--permission-mode") + 1] == "default"
    # Disable ALL inherited hooks (user + plugin) — they otherwise fire in the child because a
    # hooks:{} override merges rather than replaces. disableAllHooks is a boolean that overrides.
    assert perms and json.loads(run.argv[run.argv.index("--settings") + 1])["disableAllHooks"] is True


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


def test_cleanup_persisted_stub_removes_only_matching_session(tmp_path, monkeypatch):
    from ormah.background.llm.claude_cli_adapter import _cleanup_persisted_stub
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-tmp-encoded"
    proj.mkdir(parents=True)
    mine = proj / "sess-abc.jsonl"
    mine.write_text("{}")
    other = proj / "sess-xyz.jsonl"
    other.write_text("{}")
    _cleanup_persisted_stub("sess-abc")
    assert not mine.exists()          # the child's own stub is removed
    assert other.exists()             # a different session is never touched
    _cleanup_persisted_stub("")       # empty session_id is a no-op
    assert other.exists()


def test_cleanup_persisted_stub_never_globs(tmp_path, monkeypatch):
    """session_id comes from the CLI envelope (untrusted). A pattern-like value must NEVER be
    expanded as a glob — otherwise '*' would wipe every transcript. Validated + exact-matched."""
    from ormah.background.llm.claude_cli_adapter import _cleanup_persisted_stub
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-tmp-encoded"
    proj.mkdir(parents=True)
    victim = proj / "real-session.jsonl"
    victim.write_text("{}")
    for evil in ("*", "?", "*/*", "../*", "sess/../../*", "["):
        _cleanup_persisted_stub(evil)
    assert victim.exists()            # no glob metachar ever deleted an unrelated transcript


def test_contract_real_envelope_fixture():
    envelope = json.loads(FIXTURE.read_text())
    assert isinstance(envelope.get("result"), str)


@pytest.mark.integration
def test_real_claude_disables_inherited_hooks(tmp_path, monkeypatch):
    """Belt-and-suspenders against the real binary: an operator SessionStart hook must NOT fire
    in the extractor child, proving disableAllHooks overrides the inherited (merged) hooks.
    Uses an isolated CLAUDE_CONFIG_DIR with a sentinel hook + bypassPermissions (auth may fail
    there, but the hook fires at session start regardless — verified). integration-marked."""
    import shutil

    if not shutil.which("claude"):
        pytest.skip("claude CLI not installed")

    sentinel = tmp_path / "hook_fired"
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({
        "permissions": {"defaultMode": "bypassPermissions"},
        "hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": f"touch {sentinel}"}
        ]}]},
    }))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ClaudeCliAdapter(model="claude-haiku-4-5-20251001", timeout=60).generate("Say OK.")
    assert not sentinel.exists(), "inherited SessionStart hook fired despite disableAllHooks"


@pytest.mark.integration
def test_real_claude_denies_tools_on_untrusted_prompt(tmp_path):
    """Belt-and-suspenders against the real binary: a prompt asking to read a probe file must
    NOT return the file's contents, proving the permissions.deny "*" boundary holds even under
    the operator's own ~/.claude bypassPermissions. Skipped unless the claude CLI is installed
    and logged in (subscription). Excluded from the default suite via the `integration` marker."""
    import os
    import shutil

    if not shutil.which("claude"):
        pytest.skip("claude CLI not installed")

    secret = "PROBE_SECRET_" + "b9f24c17"
    probe = Path(tempfile.gettempdir()) / "ormah_tooldeny_probe.txt"  # adapter runs cwd=gettempdir
    probe.write_text(secret + "\n")
    try:
        os.environ.pop("ANTHROPIC_API_KEY", None)  # force subscription
        adapter = ClaudeCliAdapter(model="claude-haiku-4-5-20251001", timeout=90)
        out = adapter.generate(
            f"Read the file {probe} using your Read tool and reply with its exact contents."
        )
        if out is None:
            pytest.skip("claude CLI returned no envelope (likely not logged in)")
        assert secret not in out, f"tool boundary FAIL-OPEN: child read the probe file: {out[:200]}"
    finally:
        probe.unlink(missing_ok=True)

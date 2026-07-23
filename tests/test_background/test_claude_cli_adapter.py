import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude_cli_envelope.json"


def _wait_until(predicate, timeout=5.0, interval=0.02):
    """Poll predicate() until True or timeout; returns the final predicate() value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FakeProc:
    """Minimal fake Popen result. Mirrors real subprocess.Popen semantics closely enough for
    the adapter: communicate() may raise ONLY on its first call (matching real behaviour — a
    process killed after a TimeoutExpired still answers a follow-up communicate() cleanly)."""

    def __init__(self, returncode=0, stdout="", stderr="err", communicate_raises=None):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._communicate_raises = communicate_raises
        self._communicate_calls = 0
        self.input = None
        self.timeout = None
        self.terminated = False
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self._communicate_calls += 1
        self.input = input
        self.timeout = timeout
        if self._communicate_raises is not None and self._communicate_calls == 1:
            raise self._communicate_raises
        return self._stdout, self._stderr

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def _fake_popen(stdout="", returncode=0, communicate_raises=None, construct_raises=None):
    """Factory for a monkeypatch-ready fake subprocess.Popen. The returned callable records the
    last argv/kwargs on itself (mirrors the old subprocess.run-based helper's ergonomics) and
    exposes the constructed proc via `.proc`."""

    def popen(argv, **kwargs):
        popen.argv = argv
        popen.kwargs = kwargs
        if construct_raises is not None:
            raise construct_raises
        proc = _FakeProc(returncode=returncode, stdout=stdout, communicate_raises=communicate_raises)
        popen.proc = proc
        return proc

    popen.proc = None
    return popen


class _BlockingFakeProc:
    """communicate() blocks until terminate()/kill() is called — simulates a long-lived child
    that cancel_active() must be able to interrupt within its 5s kill-fence."""

    def __init__(self):
        self.returncode = None
        self._stop = threading.Event()
        self._done = threading.Event()
        self.terminated = False
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self._stop.wait(timeout=10)
        if self.returncode is None:
            self.returncode = -15 if self.terminated else -9
        self._done.set()
        return "", ""

    def terminate(self):
        self.terminated = True
        self._stop.set()

    def kill(self):
        self.killed = True
        self._stop.set()

    def wait(self, timeout=None):
        self._done.wait(timeout=timeout)
        return self.returncode

    def poll(self):
        return self.returncode if self._done.is_set() else None


def test_prompt_goes_on_stdin_not_argv(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    ClaudeCliAdapter(model="haiku").generate("SECRET transcript text")
    assert "SECRET transcript text" not in popen.argv
    assert "input" not in popen.kwargs           # never passed via Popen kwargs
    assert popen.proc.input == "SECRET transcript text"  # only ever via communicate(input=...)


def test_generate_parses_result_from_envelope(monkeypatch):
    envelope = json.dumps({"type": "result", "result": '{"memories": []}'})
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    assert ClaudeCliAdapter(model="haiku").generate("hi") == '{"memories": []}'


def test_argv_pins_model_and_json_output(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi")
    assert popen.argv[0] == "/bin/claude" and "-p" in popen.argv
    assert popen.argv[popen.argv.index("--model") + 1] == "haiku"
    assert popen.argv[popen.argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in popen.argv
    settings = json.loads(popen.argv[popen.argv.index("--settings") + 1])
    assert settings["disableAllHooks"] is True


def test_returns_none_on_is_error_envelope(monkeypatch):
    envelope = json.dumps({
        "type": "result", "is_error": True,
        "subtype": "error_during_execution", "result": "boom",
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_argv_denies_all_tools(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    ClaudeCliAdapter(model="haiku").generate("hi")
    # Tool denial is via --settings permissions (NOT --allowed-tools "", which is inert under an
    # inherited defaultMode:bypassPermissions). defaultMode "default" escapes the inherited
    # bypass; allow [] drops inherited allow rules; deny lists the built-in tools by bare name
    # (a "*" glob is rejected as invalid and would discard the whole block -> fail-open).
    perms = json.loads(popen.argv[popen.argv.index("--settings") + 1])["permissions"]
    assert perms["defaultMode"] == "default"
    assert perms["allow"] == []
    assert {"Read", "Bash", "Write", "Edit"} <= set(perms["deny"])
    # Do not inherit the user's bypassPermissions at the CLI level either.
    assert popen.argv[popen.argv.index("--permission-mode") + 1] == "default"
    # Disable ALL inherited hooks (user + plugin) — they otherwise fire in the child because a
    # hooks:{} override merges rather than replaces. disableAllHooks is a boolean that overrides.
    assert perms and json.loads(popen.argv[popen.argv.index("--settings") + 1])["disableAllHooks"] is True


def test_child_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    ClaudeCliAdapter(model="haiku").generate("hi")
    assert "ANTHROPIC_API_KEY" not in popen.kwargs["env"]


def test_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout="", returncode=2))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_generate_returns_none_on_timeout(monkeypatch):
    """MEDIUM-E (council, Codex): a provider timeout still returns None in this slice — never
    LlmTimeoutError (that's slice 3's job) and never LlmCancelledError (no shutdown involved)."""
    monkeypatch.setattr(
        subprocess, "Popen",
        _fake_popen(communicate_raises=subprocess.TimeoutExpired(cmd="claude", timeout=1)),
    )
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_generate_respects_timeout_hint(monkeypatch):
    """timeout_hint_seconds overrides the constructor timeout for a single call; a call
    without the hint falls back to the constructor default."""
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    adapter = ClaudeCliAdapter(model="haiku", timeout=120)
    adapter.generate("hi", timeout_hint_seconds=180)
    assert popen.proc.timeout == 180
    adapter.generate("hi")
    assert popen.proc.timeout == 120


def test_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout="not json"))
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_concurrency_is_bounded(monkeypatch):
    a = ClaudeCliAdapter(model="haiku", max_concurrency=1)
    inside = []

    def popen(argv, **kwargs):
        inside.append(1)
        assert sum(inside) <= 1, "more than max_concurrency subprocesses ran at once"
        inside.pop()
        return _FakeProc(returncode=0, stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
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


def test_response_format_adds_json_schema_and_reads_structured_output(monkeypatch):
    from ormah.background.llm import claude_cli_adapter as mod
    captured = {}

    def _fake_popen_call(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc(
            returncode=0,
            stdout='{"result": "", "is_error": false, "structured_output": {"is_duplicate": true}}',
        )

    monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen_call)
    adapter = mod.ClaudeCliAdapter(model="claude-haiku-4-5-20251001")
    schema = {
        "type": "object",
        "properties": {"is_duplicate": {"type": "boolean"}},
        "required": ["is_duplicate"],
    }
    raw = adapter.generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert "--json-schema" in captured["argv"]
    i = captured["argv"].index("--json-schema")
    assert '"is_duplicate"' in captured["argv"][i + 1]
    assert json.loads(raw) == {"is_duplicate": True}


def test_generate_schema_returns_structured_output_when_present(monkeypatch):
    envelope = json.dumps({
        "result": "", "is_error": False,
        "structured_output": {"relationship": "related_to", "reason": "x"},
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    schema = {"type": "object", "properties": {"relationship": {"type": "string"}}}
    raw = ClaudeCliAdapter(model="haiku").generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert json.loads(raw) == {"relationship": "related_to", "reason": "x"}


def test_generate_schema_falls_back_to_result_when_structured_null(monkeypatch):
    from ormah.background.llm_client import extract_json
    fenced_result = '```json\n{"summary": "consolidated note"}\n```'
    envelope = json.dumps({
        "result": fenced_result, "is_error": False, "structured_output": None,
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    raw = ClaudeCliAdapter(model="haiku").generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert raw == fenced_result
    assert json.loads(extract_json(raw)) == {"summary": "consolidated note"}


def test_generate_schema_returns_none_when_structured_null_and_result_blank(monkeypatch):
    envelope = json.dumps({"result": "", "is_error": False, "structured_output": None})
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    raw = ClaudeCliAdapter(model="haiku").generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert raw is None


# --- ADR-0004 slice 2: cancellation ------------------------------------------------------


def test_cancel_active_terminates_running_generate(monkeypatch):
    """Start generate() on a long-lived fake child; from another thread call
    adapter.cancel_active(); generate() must raise LlmCancelledError (never LlmTimeoutError —
    council R4: a cancel must stay uncapped) well under 10s, and cancel_active() must return 1."""
    adapter = ClaudeCliAdapter(model="haiku")
    proc = _BlockingFakeProc()
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: proc)

    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e

    t = threading.Thread(target=_run)
    t.start()
    assert _wait_until(lambda: len(adapter._active_procs) == 1, timeout=5), \
        "the child must be registered in _active_procs before cancel_active() can see it"

    start = time.monotonic()
    cancelled = adapter.cancel_active()
    t.join(timeout=10)
    elapsed = time.monotonic() - start

    assert not t.is_alive()
    assert elapsed < 10.0
    assert cancelled == 1
    assert isinstance(outcome.get("exc"), LlmCancelledError)
    assert not isinstance(outcome.get("exc"), LlmTimeoutError)


def test_cancel_active_noop_when_idle():
    adapter = ClaudeCliAdapter(model="haiku")
    assert adapter.cancel_active() == 0


def test_cancel_aborts_semaphore_waiter_without_spawning(monkeypatch):
    """council R2: max_concurrency=1, one generate() live on a long child, a second blocked on
    the semaphore. cancel_active() while both pending -> BOTH raise LlmCancelledError promptly
    and no replacement process is spawned (count Popen calls)."""
    adapter = ClaudeCliAdapter(model="haiku", max_concurrency=1)
    proc1 = _BlockingFakeProc()
    popen_calls = []

    def popen(argv, **kwargs):
        popen_calls.append(1)
        return proc1

    monkeypatch.setattr(subprocess, "Popen", popen)

    outcome = {}

    def _call(key):
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome[key] = e

    t1 = threading.Thread(target=_call, args=("t1",))
    t1.start()
    assert _wait_until(lambda: len(adapter._active_procs) == 1, timeout=5)

    t2 = threading.Thread(target=_call, args=("t2",))
    t2.start()
    time.sleep(0.2)  # best-effort: give t2 time to block on the semaphore before we cancel

    cancelled = adapter.cancel_active()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive() and not t2.is_alive()
    assert isinstance(outcome.get("t1"), LlmCancelledError)
    assert isinstance(outcome.get("t2"), LlmCancelledError)
    assert cancelled == 1                # only t1's live proc was tracked
    assert len(popen_calls) == 1, "t2 must never spawn a replacement process"


def test_popen_creation_failure_is_fast_failure(monkeypatch):
    """council R2 (critical): Popen raising FileNotFoundError/OSError returns None (fast
    failure -> EXTRACT_ERR_CALL_FAILED -> TRANSIENT), never LlmTimeoutError and never a
    slice-specific error string."""
    monkeypatch.setattr(
        subprocess, "Popen",
        _fake_popen(construct_raises=FileNotFoundError("no claude binary")),
    )
    assert ClaudeCliAdapter(model="haiku").generate("hi") is None


def test_adapter_generates_again_after_a_rollback_cancellation(monkeypatch):
    """council R6: a recoverable cancellation (startup rollback) must not poison the surviving
    cached adapter. cancel_active() then resume() -> generate() works."""
    adapter = ClaudeCliAdapter(model="haiku")
    adapter.cancel_active()
    adapter.resume()
    monkeypatch.setattr(
        subprocess, "Popen", _fake_popen(stdout=json.dumps({"result": "ok"}))
    )
    assert adapter.generate("hi") == "ok"


def test_cancel_between_creation_and_registration(monkeypatch):
    """codex R3 race: generate() is paused between process creation and its registration in
    _active_procs while cancel_active() runs to completion (seeing an empty set). generate()
    must STILL raise LlmCancelledError promptly (post-registration event re-check) and the fake
    child must be killed."""
    entered = threading.Barrier(2)   # rendezvous: Popen() has been called (creation underway)
    release = threading.Event()      # cancel_active() has finished; let Popen() return the proc
    proc_holder = {}

    def popen(argv, **kwargs):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        proc = _FakeProc(returncode=0, stdout=json.dumps({"result": "ok"}))
        proc_holder["proc"] = proc
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)

    adapter = ClaudeCliAdapter(model="haiku")
    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e

    t = threading.Thread(target=_run)
    t.start()

    entered.wait(timeout=5)                    # Popen() has been entered
    assert adapter._active_procs == set(), "must not be registered before Popen() returns"
    cancelled = adapter.cancel_active()          # sees an EMPTY set -> returns 0
    assert cancelled == 0
    release.set()                                # let Popen() return; generate() re-checks

    t.join(timeout=5)
    assert not t.is_alive()
    assert isinstance(outcome.get("exc"), LlmCancelledError)
    assert proc_holder["proc"].killed, "the post-registration re-check must still kill it"


def test_llm_generate_swallows_cancel_and_timeout(monkeypatch):
    """The maintenance path keeps its None-on-failure contract, so consolidator,
    auto_linker & co. are untouched by the new exception types."""
    from ormah.background import llm_client

    for exc in (LlmCancelledError("stopped"), LlmTimeoutError("slow")):
        class _Raising:
            def generate(self, *a, **k):
                raise exc
        monkeypatch.setattr(llm_client, "_get_or_create_adapter", lambda s: _Raising())
        assert llm_client.llm_generate(object(), "prompt") is None


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


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_claude_json_schema_returns_structured_output():
    from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
    adapter = ClaudeCliAdapter(model="claude-haiku-4-5-20251001", timeout=60)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}},
              "required": ["n"], "additionalProperties": False}
    raw = adapter.generate("Return the integer 7 in a field n.",
        response_format={"type": "json_schema", "json_schema": {"schema": schema}})
    import json
    assert json.loads(raw) == {"n": 7}


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_claude_json_schema_recovers_prose_json_fallback():
    """Consolidator-style prompt: known to answer in a single text turn (structured_output
    null, valid JSON in `result`). Proves the fallback recovers it end-to-end via the real
    CLI, not a mocked envelope. Only a true no-output run (both fields empty) is a skip."""
    from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
    from ormah.background.llm_client import extract_json

    adapter = ClaudeCliAdapter(model="claude-haiku-4-5-20251001", timeout=60)
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    prompt = (
        "Summarize this note in one short sentence: "
        "'The user prefers dark mode and enabled it in settings.'\n\n"
        'Return a JSON object:\n{"summary": "one-sentence summary"}'
    )
    raw = adapter.generate(
        prompt, response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    if raw is None:
        pytest.skip("claude CLI returned no output on either structured_output or result")
    parsed = json.loads(extract_json(raw))
    assert isinstance(parsed, dict) and isinstance(parsed.get("summary"), str) and parsed["summary"]

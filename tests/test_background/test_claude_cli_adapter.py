import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from ormah.background import llm_cancel
from ormah.background.llm.claude_cli_adapter import _CANCEL_POLL_INTERVAL, ClaudeCliAdapter
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
    process killed after a TimeoutExpired still answers a follow-up communicate() cleanly), and
    it supports the context-manager protocol (real Popen.__exit__ closes the pipes and reaps via
    wait() — the adapter now runs the communicate()/timeout/exception handling inside `with
    proc:`, B-2)."""

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
        self.wait_calls = 0
        self.exited = False

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
        self.wait_calls += 1
        return self.returncode

    def poll(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        self.wait()
        return False


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


# The tests never spawn a real child -- Popen is always faked -- so this path is only ever
# handed to the fake as `cwd`. It is deliberately NOT created on disk.
WORKSPACE = Path("/tmp/ormah-judge-workspace-under-test")


def _adapter(**kwargs):
    """Build the adapter with a stand-in workspace. `workspace_dir` is required and has no safe
    default in production, so every test supplies one; overriding it stays possible per call."""
    kwargs.setdefault("workspace_dir", WORKSPACE)
    return ClaudeCliAdapter(**kwargs)


class _NeverEofProc:
    """A child whose pipes NEVER reach EOF — models the setsid grandchild that survives our group
    kill and keeps the write end of our inherited stdout open. communicate() honours its timeout
    slice (sleeps it) and then raises TimeoutExpired, exactly like the real one.

    Fails loudly on an UNBOUNDED communicate() (timeout=None): that is the B-1 regression, where
    the call blocks until an EOF a grandchild can withhold forever."""

    def __init__(self):
        self.returncode = None
        self.communicate_calls = 0
        self.wait_calls = 0
        self.killed = False
        self.terminated = False
        self.timeouts = []
        self.inputs = []

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        self.timeouts.append(timeout)
        self.inputs.append(input)
        if timeout is None:
            raise AssertionError("communicate() must never be called unbounded (B-1)")
        time.sleep(timeout)
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = -9
        return self.returncode

    def poll(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.wait()
        return False


def test_prompt_goes_on_stdin_not_argv(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("SECRET transcript text")
    assert "SECRET transcript text" not in popen.argv
    assert "input" not in popen.kwargs           # never passed via Popen kwargs
    assert popen.proc.input == "SECRET transcript text"  # only ever via communicate(input=...)


def test_generate_parses_result_from_envelope(monkeypatch):
    envelope = json.dumps({"type": "result", "result": '{"memories": []}'})
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    assert _adapter(model="haiku").generate("hi") == '{"memories": []}'


def test_argv_pins_model_and_json_output(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku", bin_path="/bin/claude").generate("hi")
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
    assert _adapter(model="haiku").generate("hi") is None


def test_argv_denies_all_tools(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("hi")
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
    _adapter(model="haiku").generate("hi")
    assert "ANTHROPIC_API_KEY" not in popen.kwargs["env"]


def test_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout="", returncode=2))
    assert _adapter(model="haiku").generate("hi") is None


def test_generate_returns_none_on_timeout(monkeypatch, caplog):
    """MEDIUM-E (council, Codex): a provider timeout still returns None in this slice — never
    LlmTimeoutError (that's slice 3's job) and never LlmCancelledError (no shutdown involved).

    HIGH-2 (council-pr R3): with the poll loop in place, the REAL deadline path must preserve
    exactly today's semantics — group kill + wait() reap, the "timed out after" warning, None."""
    proc = _NeverEofProc()
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: proc)
    with caplog.at_level(logging.WARNING):
        result = _adapter(model="haiku", timeout=1).generate("hi")
    assert result is None                      # returned, never raised
    assert proc.killed, "the deadline path must kill the child"
    assert proc.wait_calls >= 1, "the deadline path must reap via wait()"
    assert any("timed out after" in r.getMessage() for r in caplog.records)
    # The input is handed over exactly once — CPython rejects re-sending it on a retry.
    assert proc.inputs[0] == "hi" and all(i is None for i in proc.inputs[1:])


def test_timeout_reaps_via_wait_and_never_an_unbounded_communicate(monkeypatch):
    """B-1: base subprocess.run's timeout path does process.kill(); process.wait() -- it REAPS
    the child, it never waits for pipe EOF. An UNBOUNDED communicate() (timeout=None) blocks
    until EOF on BOTH pipes; if a grandchild inherited our stdout/stderr, that can never arrive
    and the ingest drain thread would hang forever on the live single-process Beta.

    HIGH-2 (council-pr R3) replaced the single communicate() with a bounded POLL LOOP, so a
    SECOND communicate() is now expected and correct -- what must never happen is an unbounded
    one. _NeverEofProc raises loudly on any communicate(timeout=None) instead of hanging the
    suite, and this proves the deadline path still reaps via kill()+wait()."""
    proc = _NeverEofProc()
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: proc)

    start = time.monotonic()
    result = _adapter(model="haiku", timeout=1).generate("hi")
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 3.0, "the deadline path must reap via wait(), never block on pipe EOF"
    assert proc.killed
    assert proc.wait_calls >= 1, "the timeout path must call wait() to reap the killed child"
    assert proc.communicate_calls >= 2, "the poll loop must re-poll within the budget"
    assert all(t is not None and t <= _CANCEL_POLL_INTERVAL for t in proc.timeouts), \
        "every communicate() must be bounded by at most one poll interval (B-1)"


def test_generate_respects_timeout_hint(monkeypatch):
    """timeout_hint_seconds overrides the constructor timeout for a single call; a call without
    the hint falls back to the constructor default.

    HIGH-2 (council-pr R3): under the poll loop the hint sets the overall DEADLINE while each
    communicate() is capped at one poll interval, so the budget is asserted by how long a
    never-EOF child is polled for — not by a single communicate() timeout argument."""
    procs = []

    def popen(argv, **kwargs):
        p = _NeverEofProc()
        procs.append(p)
        return p

    monkeypatch.setattr(subprocess, "Popen", popen)
    adapter = _adapter(model="haiku", timeout=3)

    start = time.monotonic()
    assert adapter.generate("hi", timeout_hint_seconds=1) is None
    hinted = time.monotonic() - start
    assert 0.9 <= hinted < 2.5, f"the hint must bound this call, took {hinted:.2f}s"

    start = time.monotonic()
    assert adapter.generate("hi") is None
    default = time.monotonic() - start
    assert default >= 2.8, f"without a hint the constructor budget applies, took {default:.2f}s"

    assert all(t <= _CANCEL_POLL_INTERVAL for p in procs for t in p.timeouts), \
        "every communicate() is capped at one poll interval regardless of the budget"


def test_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout="not json"))
    assert _adapter(model="haiku").generate("hi") is None


def test_concurrency_is_bounded(monkeypatch):
    a = _adapter(model="haiku", max_concurrency=1)
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
    adapter = _adapter(model="claude-haiku-4-5-20251001")
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
    raw = _adapter(model="haiku").generate(
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
    raw = _adapter(model="haiku").generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert raw == fenced_result
    assert json.loads(extract_json(raw)) == {"summary": "consolidated note"}


def test_generate_schema_returns_none_when_structured_null_and_result_blank(monkeypatch):
    envelope = json.dumps({"result": "", "is_error": False, "structured_output": None})
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    raw = _adapter(model="haiku").generate(
        "hi", response_format={"type": "json_schema", "json_schema": {"schema": schema}}
    )
    assert raw is None


# --- ADR-0004 slice 2: cancellation ------------------------------------------------------


def test_cancel_set_raises_even_when_child_exits_cleanly(monkeypatch):
    """HIGH-1 (council-pr R3, Codex) DATA INTEGRITY: a child that HANDLES SIGTERM and exits 0
    inside the 5s kill fence returns partial/buffered JSON. The old guard only raised when
    `returncode != 0`, so that envelope was treated as SUCCESS and the engine ADVANCED THE
    CURSOR — violating this slice's central invariant ("a cancel never advances the cursor").
    Whenever a cancel has landed, generate() must raise LlmCancelledError regardless of
    returncode. ADR-0004 slice 2: the cancel is now the module-level llm_cancel epoch, not an
    instance-scoped flag."""

    adapter = _adapter(model="haiku")
    llm_cancel.begin_lifespan()

    class _CleanExitOnCancelProc:
        """The shutdown cancel lands WHILE communicate() runs (as begin_cancel() would); the
        child then exits 0 with partial buffered output instead of dying by signal."""

        def __init__(self):
            self.returncode = 0
            self.killed = False

        def communicate(self, input=None, timeout=None):
            # The cancel lands mid-call, via the real public API — llm_cancel.begin_cancel()
            # bumps the epoch and marks the world cancelled in one atomic critical section.
            llm_cancel.begin_cancel(final=True)
            return json.dumps({"result": "partial buffered output"}), ""

        def terminate(self):
            pass

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.wait()
            return False

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: _CleanExitOnCancelProc())
    try:
        with pytest.raises(LlmCancelledError):
            adapter.generate("hi")
    finally:
        llm_cancel.begin_lifespan()


def test_cancel_during_poll_loop_raises_within_a_poll_interval(monkeypatch):
    """HIGH-2 (council-pr R3, Codex): a setsid grandchild escapes the group kill AND keeps our
    inherited stdout open, so communicate() can never reach EOF. Before the poll loop the whole
    generate() thread sat there until the provider timeout (60s here) and _stop_and_drain joined
    on it, damming the entire shutdown. The cancel must now land within ~one poll interval.

    The bound is observed IN-THREAD: no fd is closed from the cancelling thread (that would be
    undefined behaviour while communicate()'s selector is blocked on it)."""
    adapter = _adapter(model="haiku", timeout=60)  # a deliberately long provider budget
    proc = _NeverEofProc()
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: proc)
    llm_cancel.begin_lifespan()

    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e
        except Exception as e:  # noqa: BLE001
            outcome["other"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert _wait_until(lambda: proc.communicate_calls >= 1, timeout=5), \
        "generate() must reach the poll loop"

    start = time.monotonic()
    llm_cancel.begin_cancel(final=True)
    t.join(timeout=10)
    elapsed = time.monotonic() - start

    assert not t.is_alive(), "generate() must not wait out the 60s provider budget"
    assert isinstance(outcome.get("exc"), LlmCancelledError), \
        f"a cancel must raise LlmCancelledError, never a provider timeout: {outcome}"
    assert elapsed < 5.0, f"the cancel must land within ~a poll interval, took {elapsed:.2f}s"
    assert proc.inputs[0] == "hi" and all(i is None for i in proc.inputs[1:]), \
        "the prompt is handed over exactly once — CPython rejects re-sending it on a retry"
    llm_cancel.begin_lifespan()


def test_cancel_history_survives_a_resume_racing_the_final_gate(monkeypatch):
    """ITEM 1 (council-pr R4, Codex) DATA INTEGRITY: the final gate read the LIVE _cancel_event —
    the state AT READ TIME — while resume() clears that same mutable object from another thread.

    Reachable chain: the scheduler starts BEFORE start_session_watcher, so a maintenance call can
    be in flight when a watcher rollback runs _stop_and_drain(rearm=True). That cancels BOTH
    cached adapters (the maintenance one isn't the watcher's), the join fence only joins the
    watcher's drains, and the finally's resume_llm_adapters() CLEARS the event. The in-flight
    maintenance call then reached the gate with a clean event and accepted a cancelled child's
    partial JSON as SUCCESS — feeding graph mutations (dedup/merge/conflict). Same failure as
    R3's HIGH-1 by another route: we traded "the returncode masks the cancel" for "another
    thread can erase the cancel".

    A monotonic cancel epoch (now the module-level llm_cancel authority) fixes it: resume()
    re-opens admission for NEW calls without erasing the history of calls already in flight."""
    adapter = _adapter(model="haiku")
    llm_cancel.begin_lifespan()

    class _CancelThenResumeProc:
        """The rollback's cancel AND its finally-resume both land while this call is in flight;
        the child then exits 0 with partial buffered output."""

        def __init__(self):
            self.returncode = 0

        def communicate(self, input=None, timeout=None):
            llm_cancel.begin_cancel(final=False)  # the rollback cancels every in-flight call...
            llm_cancel.resume()                   # ...and its finally re-admits new calls
            return json.dumps({"result": "partial buffered output"}), ""

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.wait()
            return False

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: _CancelThenResumeProc())
    with pytest.raises(LlmCancelledError):
        adapter.generate("hi")

    # ...and the resume genuinely re-opened admission: a NEW call must succeed.
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=json.dumps({"result": "ok"})))
    assert adapter.generate("hi") == "ok"
    llm_cancel.begin_lifespan()


def test_previous_era_semaphore_waiter_never_spawns_after_cancel_resume(monkeypatch):
    """council-pr R5 MEDIUM (Cursor 0.85) — same root cause via the semaphore. `gen` was captured
    INSIDE `with sem:`, i.e. only after the waiter unblocked. A call already queued on the
    semaphore BEFORE the cancel — a previous-era call the cancel SHOULD have reached — woke up,
    captured the POST-cancel generation with the event already cleared by a rollback's resume(),
    and spawned a brand new child mid-shutdown.

    Fixed by capturing the era at ENTRY (before the semaphore) plus an (a)+(b) admission check.
    Affects the maintenance path, which has semaphore waiters; ingest has a single drain thread."""
    adapter = _adapter(model="haiku", max_concurrency=1, timeout=30)
    llm_cancel.begin_lifespan()

    popen_calls = []
    a_running = threading.Event()
    a_may_return = threading.Event()

    class _HolderProc:
        """Call A: occupies the single semaphore slot until released."""

        def __init__(self):
            self.returncode = 0
            self.pid = None

        def communicate(self, input=None, timeout=None):
            a_running.set()
            a_may_return.wait(timeout=10)
            return json.dumps({"result": "A"}), ""

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def popen(*a, **kw):
        popen_calls.append(1)
        return _HolderProc()

    monkeypatch.setattr(subprocess, "Popen", popen)

    outcome = {}

    def _call(key):
        try:
            outcome[key] = adapter.generate("hi")
        except LlmCancelledError as e:
            outcome[key] = e

    ta = threading.Thread(target=_call, args=("a",), daemon=True)
    ta.start()
    assert a_running.wait(timeout=5), "call A never took the semaphore"

    tb = threading.Thread(target=_call, args=("b",), daemon=True)
    tb.start()
    # B must be parked on the semaphore with its (previous) era already captured. Self-validating:
    # if the settle were too short B would not have entered generate() yet and we would say so
    # instead of testing nothing.
    time.sleep(0.2)
    assert "b" not in outcome, "call B should still be waiting on the semaphore (settle too short)"

    llm_cancel.begin_cancel(final=False)   # ends B's era (and A's era too)
    llm_cancel.resume()                    # a rollback's finally re-admits new calls

    a_may_return.set()        # A finishes, handing the semaphore to B
    ta.join(timeout=10)
    tb.join(timeout=10)

    assert len(popen_calls) == 1, \
        f"the previous-era waiter spawned a replacement child: {len(popen_calls)} Popen call(s)"
    assert isinstance(outcome.get("b"), LlmCancelledError), \
        f"the previous-era waiter must be treated as cancelled, got {outcome.get('b')!r}"
    # A was cancelled too (rc=0 but its era ended) — the R3/R4 invariant still holds.
    assert isinstance(outcome.get("a"), LlmCancelledError), \
        f"the cancelled in-flight call must also raise, got {outcome.get('a')!r}"
    llm_cancel.begin_lifespan()


def test_popen_creation_failure_is_fast_failure(monkeypatch):
    """council R2 (critical): Popen raising FileNotFoundError/OSError returns None (fast
    failure -> EXTRACT_ERR_CALL_FAILED -> TRANSIENT), never LlmTimeoutError and never a
    slice-specific error string."""
    monkeypatch.setattr(
        subprocess, "Popen",
        _fake_popen(construct_raises=FileNotFoundError("no claude binary")),
    )
    assert _adapter(model="haiku").generate("hi") is None


def test_adapter_generates_again_after_a_rollback_cancellation(monkeypatch):
    """council R6: a recoverable cancellation (startup rollback) must not poison the process —
    begin_cancel(final=False) then resume() -> generate() works."""
    llm_cancel.begin_lifespan()
    adapter = _adapter(model="haiku")
    llm_cancel.begin_cancel(final=False)
    llm_cancel.resume()
    monkeypatch.setattr(
        subprocess, "Popen", _fake_popen(stdout=json.dumps({"result": "ok"}))
    )
    assert adapter.generate("hi") == "ok"
    llm_cancel.begin_lifespan()


def test_cancel_between_creation_and_registration(monkeypatch):
    """codex R3 race: generate() is paused between process creation (Popen returning) and the
    post-spawn epoch re-check while a cancel lands and completes in that exact window. generate()
    must STILL raise LlmCancelledError promptly (post-spawn epoch re-check) and the fake child
    must be killed."""
    llm_cancel.begin_lifespan()
    entered = threading.Barrier(2)   # rendezvous: Popen() has been called (creation underway)
    release = threading.Event()      # the cancel has landed; let Popen() return the proc
    proc_holder = {}

    def popen(argv, **kwargs):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        proc = _FakeProc(returncode=0, stdout=json.dumps({"result": "ok"}))
        proc_holder["proc"] = proc
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)

    adapter = _adapter(model="haiku")
    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e

    t = threading.Thread(target=_run)
    t.start()

    entered.wait(timeout=5)                    # Popen() has been entered
    llm_cancel.begin_cancel(final=True)         # lands while still inside Popen()
    release.set()                                # let Popen() return; generate() re-checks

    t.join(timeout=5)
    assert not t.is_alive()
    assert isinstance(outcome.get("exc"), LlmCancelledError)
    assert proc_holder["proc"].killed, "the post-spawn re-check must still kill it"
    llm_cancel.begin_lifespan()


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.integration
def test_cancel_kills_whole_process_group_not_just_parent(tmp_path, monkeypatch):
    """HIGH-2 (council-pr, Codex): `claude -p` forks grandchildren (user-scoped MCP servers, no
    --strict-mcp-config) that inherit the child's stdout/stderr. A per-PID kill leaves such a
    grandchild holding the pipe open, so communicate() never sees EOF and the shutdown drain
    waits the full provider timeout. start_new_session=True + killpg must reach the WHOLE group.

    REAL subprocess (integration-marked). RED against the pre-fix per-PID kill: generate() does
    NOT return within 15s and the lingering grandchild survives the cancel."""
    llm_cancel.begin_lifespan()
    marker = tmp_path / "marker"
    marker.mkdir()
    script = tmp_path / "fake_claude.sh"
    # A parent shell that forks a background `sleep` (the grandchild) which inherits stdout, then
    # waits — mirroring a claude -p that spawns an MCP grandchild holding our stdout pipe open.
    script.write_text(
        "#!/bin/sh\n"
        "sleep 60 &\n"
        'echo "$!" > "$MARKER_DIR/grandchild.pid"\n'
        ': > "$MARKER_DIR/started"\n'
        "wait\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("MARKER_DIR", str(marker))

    adapter = _adapter(model="haiku", bin_path=str(script), timeout=120)
    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e
        except Exception as e:  # noqa: BLE001
            outcome["other"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert _wait_until(lambda: (marker / "started").exists(), timeout=10), \
        "the fake child never started"
    grandchild_pid = int((marker / "grandchild.pid").read_text().strip())
    assert _pid_alive(grandchild_pid), "grandchild must be live before the cancel"
    # ADR-0004 slice 2: cancellation is now detected in-thread, from generate()'s own poll loop
    # noticing llm_cancel.epoch_changed() — there is no external process registry to wait on, so
    # settle briefly to make sure the thread is genuinely inside the poll loop before cancelling.
    time.sleep(0.3)

    start = time.monotonic()
    llm_cancel.begin_cancel(final=True)
    t.join(timeout=15)
    elapsed = time.monotonic() - start

    try:
        assert not t.is_alive(), \
            "generate() did not return within 15s — a per-PID kill hangs on the grandchild"
        assert elapsed < 15.0
        assert isinstance(outcome.get("exc"), LlmCancelledError), \
            f"cancel must raise LlmCancelledError, got {outcome}"
        assert _wait_until(lambda: not _pid_alive(grandchild_pid), timeout=5), \
            "the grandchild survived — the whole process group was not killed"
    finally:
        # Never leak the 60s sleeper if an assertion above failed (the RED path).
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(grandchild_pid, signal.SIGKILL)
        llm_cancel.begin_lifespan()


@pytest.mark.integration
def test_group_sigkill_escalation_reaps_sigterm_ignoring_grandchild(tmp_path, monkeypatch):
    """HIGH-1 refine (council-pr R2, Codex): the exact edge the poll()-gated per-PID escalation
    missed. The DIRECT child (group leader) exits on SIGTERM, but an in-group grandchild TRAPS
    and IGNORES SIGTERM while holding our stdout open. The SIGKILL escalation must (a) target the
    GROUP via the pgid CAPTURED AT SPAWN (a pgid re-derived from the now-dead leader raises
    ProcessLookupError), and (b) fire UNCONDITIONALLY, not gated on the dead leader's poll().
    Otherwise the grandchild leaks and communicate()/the drain hang to the full timeout.

    REAL subprocess. RED against the pre-refine code (poll-gated + lazily-derived pgid):
    generate() does NOT return within 15s and the grandchild survives the cancel."""
    llm_cancel.begin_lifespan()
    marker = tmp_path / "marker"
    marker.mkdir()
    script = tmp_path / "fake_claude_trap.sh"
    # Grandchild: a shell that ignores SIGTERM (trap "" TERM) and holds stdout open via a busy
    # loop. Parent: no trap -> dies on the group SIGTERM (the "leader exits first" case).
    script.write_text(
        "#!/bin/sh\n"
        "sh -c 'trap \"\" TERM; while :; do sleep 1; done' &\n"
        'echo "$!" > "$MARKER_DIR/grandchild.pid"\n'
        ': > "$MARKER_DIR/started"\n'
        "wait\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("MARKER_DIR", str(marker))

    adapter = _adapter(model="haiku", bin_path=str(script), timeout=120)
    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e
        except Exception as e:  # noqa: BLE001
            outcome["other"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert _wait_until(lambda: (marker / "started").exists(), timeout=10), \
        "the fake child never started"
    grandchild_pid = int((marker / "grandchild.pid").read_text().strip())
    assert _pid_alive(grandchild_pid), "grandchild must be live before the cancel"
    # ADR-0004 slice 2: cancellation is now detected in-thread, from generate()'s own poll loop
    # noticing llm_cancel.epoch_changed() — there is no external process registry to wait on, so
    # settle briefly to make sure the thread is genuinely inside the poll loop before cancelling.
    time.sleep(0.3)

    start = time.monotonic()
    llm_cancel.begin_cancel(final=True)
    t.join(timeout=15)
    elapsed = time.monotonic() - start

    try:
        assert not t.is_alive(), \
            "generate() did not return within 15s — the SIGTERM-ignoring grandchild was not reaped"
        assert elapsed < 15.0
        assert isinstance(outcome.get("exc"), LlmCancelledError), \
            f"cancel must raise LlmCancelledError, got {outcome}"
        assert _wait_until(lambda: not _pid_alive(grandchild_pid), timeout=6), \
            "the SIGTERM-ignoring grandchild survived — the group SIGKILL escalation was skipped"
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(grandchild_pid, signal.SIGKILL)
        llm_cancel.begin_lifespan()


@pytest.mark.integration
def test_cancel_is_bounded_even_with_a_detached_setsid_grandchild(tmp_path, monkeypatch):
    """HIGH-2 (council-pr R3, Codex): the DETACHED-grandchild bound. The grandchild calls
    setsid(), so it lands in its OWN session/process group and survives our group kill — and it
    still holds the write end of our inherited stdout, so communicate() can NEVER reach EOF (EOF
    needs ALL write ends closed, not the leader's death).

    REAL subprocess. RED (single unbounded-until-EOF communicate): the cancel returns but
    generate() sits until the provider timeout (20s here), and _stop_and_drain joins on it.
    GREEN (poll loop): generate() abandons the read within ~one poll interval.

    The detached grandchild is NOT reaped (only cgroups/job objects could) — it survives as an
    orphan whose writes now take EPIPE. That residual is accepted; what matters is that it no
    longer dams our shutdown."""
    llm_cancel.begin_lifespan()
    marker = tmp_path / "marker"
    marker.mkdir()
    script = tmp_path / "fake_claude_setsid.sh"
    # The grandchild detaches with setsid() and holds the inherited stdout for 120s.
    script.write_text(
        "#!/bin/sh\n"
        f"'{sys.executable}' -c "
        "'import os,time; os.setsid(); time.sleep(120)' &\n"
        'echo "$!" > "$MARKER_DIR/grandchild.pid"\n'
        ': > "$MARKER_DIR/started"\n'
        "wait\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("MARKER_DIR", str(marker))

    adapter = _adapter(model="haiku", bin_path=str(script), timeout=20)
    outcome = {}

    def _run():
        try:
            adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["exc"] = e
        except Exception as e:  # noqa: BLE001
            outcome["other"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert _wait_until(lambda: (marker / "started").exists(), timeout=15), \
        "the fake child never started"
    grandchild_pid = int((marker / "grandchild.pid").read_text().strip())
    # Scenario integrity: the detached grandchild must really be alive and holding our stdout,
    # otherwise this test would pass vacuously on a child that simply exited.
    assert _pid_alive(grandchild_pid), "the setsid grandchild must be live before the cancel"
    # Settle so generate() is genuinely INSIDE the communicate() poll loop. Without this the
    # cancel can land on the earlier post-spawn re-check — a correct cancel, but it would not
    # measure the poll-loop bound this test exists to prove.
    time.sleep(0.3)

    start = time.monotonic()
    llm_cancel.begin_cancel(final=True)
    t.join(timeout=30)          # generous: in RED we want to MEASURE the provider-timeout wait
    elapsed = time.monotonic() - start

    try:
        assert not t.is_alive(), "generate() never returned even after the provider timeout"
        # The residual, asserted explicitly: the detached grandchild SURVIVES the group kill
        # (only cgroups/job objects could reap it) — the point is that it no longer dams us.
        assert _pid_alive(grandchild_pid), \
            "the setsid grandchild should have escaped the group kill (documented residual)"
        assert isinstance(outcome.get("exc"), LlmCancelledError), \
            f"a cancel must raise LlmCancelledError, never a provider timeout: {outcome}"
        assert elapsed < 5.0, (
            f"cancel took {elapsed:.2f}s — a detached setsid grandchild must not hold the "
            f"shutdown until the 20s provider timeout"
        )
    finally:
        # The detached grandchild is an accepted orphan — never leak it out of the test run.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(grandchild_pid, signal.SIGKILL)
        llm_cancel.begin_lifespan()


@pytest.mark.integration
def test_multi_poll_success_loses_no_output(tmp_path, monkeypatch):
    """ITEM 3 (council-pr R4, Cursor gap): the poll loop's SUCCESS path across MULTIPLE rounds.

    The cancel and timeout paths are covered; a SUCCESSFUL child whose output spans several
    expired polls rested only on CPython's contract ("retrying communication will not lose any
    output"). This locks it against a future refactor.

    REAL subprocess on purpose: a fake that hands back accumulated output would be testing the
    fake, not CPython's contract nor our loop. The child emits ONE JSON envelope in six pieces,
    so the document only parses if every piece survived every poll round."""

    class _CountingProc:
        """Wraps a REAL Popen to count poll rounds. Nothing is faked — the subprocess, its pipes
        and CPython's own retry bookkeeping all stay real."""

        def __init__(self, real):
            self._real = real
            self.communicate_calls = 0
            self.expired_polls = 0
            self.final = None

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            try:
                out, err = self._real.communicate(input=input, timeout=timeout)
            except subprocess.TimeoutExpired:
                self.expired_polls += 1
                raise
            self.final = (out, err)
            return out, err

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *a):
            return self._real.__exit__(*a)

        def __getattr__(self, item):        # pid / wait / poll / kill / returncode -> real proc
            return getattr(self._real, item)

    child = tmp_path / "chunked_child.py"
    # 6 pieces x 0.3s => ~1.8s of runtime against a 0.5s poll slice => several expired polls.
    child.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        "pieces = ['{\"result\": \"P0', 'P1', 'P2', 'P3', 'P4', 'P5\"}']\n"
        "for i, piece in enumerate(pieces):\n"
        "    sys.stdout.write(piece); sys.stdout.flush()\n"
        "    sys.stderr.write('E%d' % i); sys.stderr.flush()\n"
        "    time.sleep(0.3)\n"
    )
    child.chmod(0o755)

    real_popen = subprocess.Popen
    holder = {}

    def popen(argv, **kwargs):
        proxy = _CountingProc(real_popen(argv, **kwargs))
        holder["proc"] = proxy
        return proxy

    monkeypatch.setattr(subprocess, "Popen", popen)

    adapter = _adapter(model="haiku", bin_path=str(child), timeout=60)
    result = adapter.generate("hi")
    proxy = holder["proc"]

    # End-to-end: the envelope reassembled across poll rounds parsed into the full result.
    assert result == "P0P1P2P3P4P5", f"output lost across poll rounds: {result!r}"
    out, err = proxy.final
    assert out == '{"result": "P0P1P2P3P4P5"}', f"stdout incomplete or reordered: {out!r}"
    assert err == "E0E1E2E3E4E5", f"stderr incomplete or reordered: {err!r}"
    assert proxy.returncode == 0
    # Non-vacuity: without expired polls this would pass without ever exercising the retry.
    assert proxy.expired_polls >= 2, (
        f"only {proxy.expired_polls} poll(s) expired — the multi-poll retry was never exercised"
    )


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
    _adapter(model="claude-haiku-4-5-20251001", timeout=60).generate("Say OK.")
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
        adapter = _adapter(model="claude-haiku-4-5-20251001", timeout=90)
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
    adapter = _adapter(model="claude-haiku-4-5-20251001", timeout=60)
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
    from ormah.background.llm_client import extract_json

    adapter = _adapter(model="claude-haiku-4-5-20251001", timeout=60)
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


def test_a_cancelled_call_never_has_its_partial_output_accepted(monkeypatch):
    """R3 + R5 regression. A child that HANDLES SIGTERM and exits 0 emits partial
    buffered JSON. Accepting it made the engine advance the cursor on a cancelled
    extraction. The final gate must consult the epoch, not the return code."""
    from ormah.background import llm_cancel
    from ormah.background.llm import claude_cli_adapter as mod

    llm_cancel.begin_lifespan()
    adapter = _adapter(model="haiku", timeout=30)
    spawned = threading.Event()
    may_return = threading.Event()

    class _SigtermHandlingProc:
        returncode = 0
        pid = None

        def communicate(self, input=None, timeout=None):
            spawned.set()
            if not may_return.wait(timeout=5):
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)
            return json.dumps({"result": "PARTIAL buffered output"}), ""

        def terminate(self): pass
        def kill(self): pass          # handled the signal: returncode stays 0
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(mod, "_capture_pgid", lambda proc: None)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: _SigtermHandlingProc())

    outcome: dict = {}

    def run():
        try:
            outcome["result"] = adapter.generate("hi")
        except LlmCancelledError as e:
            outcome["raised"] = e

    t = threading.Thread(target=run)
    t.start()
    assert spawned.wait(timeout=5), "the child never spawned"
    llm_cancel.begin_cancel(final=True)
    may_return.set()
    t.join(timeout=10)
    assert not t.is_alive()

    assert "raised" in outcome, f"cancelled output was accepted: {outcome.get('result')!r}"
    llm_cancel.begin_lifespan()


def test_argv_pins_the_project_setting_source(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("hi")
    # "project" and never "": the empty value drops the operator's settings, and with them
    # alwaysThinkingEnabled:false -- the regression that got 34c41cd reverted.
    assert popen.argv[popen.argv.index("--setting-sources") + 1] == "project"


def test_the_child_runs_in_the_judge_workspace_not_the_tempdir(monkeypatch, tmp_path):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku", workspace_dir=tmp_path).generate("hi")
    # --setting-sources project resolves CLAUDE.md relative to cwd, so cwd IS the mechanism.
    assert popen.kwargs["cwd"] == tmp_path


def test_hardened_settings_switch_extended_thinking_off(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("hi")
    settings = json.loads(popen.argv[popen.argv.index("--settings") + 1])
    assert settings["alwaysThinkingEnabled"] is False

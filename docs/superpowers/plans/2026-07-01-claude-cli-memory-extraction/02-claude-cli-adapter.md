### Task 02: `ClaudeCliAdapter`

Shell out to `claude -p`, prompt on **stdin** (not argv — privacy + `ARG_MAX`), subscription-only,
hooks-off, bounded concurrency. Mirrors the `LLMAdapter` contract in
`src/ormah/background/llm/base.py`
(`generate(prompt, json_mode=True, *, response_format=None, temperature=None, max_tokens=None) -> str | None`).

Use the exact values Task 01 recorded (SPIKE-FINDINGS.md) for `_HOOKS_OFF_ARGS`, the envelope text
field, and `claude_cli_bin` if `claude` is not on the launchd PATH. Below assumes hooks-off via
`--settings '{"hooks":{}}'` and text at `envelope["result"]`; adjust to the spike if they differ.

**Files:**
- Create: `src/ormah/background/llm/claude_cli_adapter.py`
- Test: `tests/test_background/test_claude_cli_adapter.py`
- Fixture (from Task 01): `tests/fixtures/claude_cli_envelope.json`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_background/test_claude_cli_adapter.py
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
    assert "SECRET transcript text" not in run.argv           # never in the process list
    assert run.kwargs["input"] == "SECRET transcript text"    # fed via stdin


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


def test_argv_denies_all_tools(monkeypatch):
    # Untrusted transcript must not be able to drive agent tools (prompt-injection boundary).
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
    # Two adapters sharing the class semaphore must not both hold it beyond max_concurrency=1.
    import threading
    a = ClaudeCliAdapter(model="haiku", max_concurrency=1)
    inside = []
    barrier = threading.Event()

    def run(argv, **kwargs):
        inside.append(1)
        assert sum(inside) <= 1, "more than max_concurrency subprocesses ran at once"
        inside.pop()
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"result": "ok"}), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    threads = [threading.Thread(target=lambda: a.generate("hi")) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()


def test_worker_transcript_is_purged(monkeypatch, tmp_path):
    # After a run, the child's transcript dir under ~/.claude/projects must be removed.
    fake_home = tmp_path
    monkeypatch.setattr("os.path.expanduser", lambda p: p.replace("~", str(fake_home)))
    tdir = fake_home / ".claude" / "projects" / "-tmp-ormah-extractor"
    tdir.mkdir(parents=True)
    (tdir / "sess.jsonl").write_text("private conversation text")
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(stdout=json.dumps({"result": "ok"})))
    ClaudeCliAdapter(model="haiku", workdir="/tmp/ormah-extractor").generate("hi")
    assert not tdir.exists()  # at-rest copy deleted


def test_contract_real_envelope_fixture():
    envelope = json.loads(FIXTURE.read_text())
    assert isinstance(envelope.get("result"), str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: ormah.background.llm.claude_cli_adapter`.

- [ ] **Step 3: Write the adapter**

```python
# src/ormah/background/llm/claude_cli_adapter.py
"""Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid API)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading

from ormah.background.llm.base import LLMAdapter

logger = logging.getLogger(__name__)

# Hooks-off mechanism confirmed by Task 01 (SPIKE-FINDINGS.md). Keeps the child from firing
# ormah hooks → no extraction recursion.
_HOOKS_OFF_ARGS = ["--settings", '{"hooks":{}}']

# Trust boundary: the transcript is UNTRUSTED input (prompt-injection vector). Deny ALL agent
# tools so a malicious transcript can only produce text, never act (file/bash/etc.). Exact flag
# confirmed by Task 01 (`--allowed-tools ""` empties the allowlist; adjust to the spike finding).
_TOOL_DENY_ARGS = ["--allowed-tools", ""]

# Bound concurrent `claude -p` across all adapter instances/threads (watcher runs ingests in
# parallel). One shared semaphore per (interpreter, max) — keyed lazily below.
_SEMAPHORES: dict[int, threading.Semaphore] = {}
_SEM_LOCK = threading.Lock()


def _semaphore(max_concurrency: int) -> threading.Semaphore:
    with _SEM_LOCK:
        sem = _SEMAPHORES.get(max_concurrency)
        if sem is None:
            sem = threading.Semaphore(max_concurrency)
            _SEMAPHORES[max_concurrency] = sem
        return sem


class ClaudeCliAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        timeout: int = 120,
        bin_path: str | None = None,
        workdir: str = "/tmp/ormah-extractor",
        max_concurrency: int = 1,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.bin_path = bin_path or shutil.which("claude") or "claude"
        self.workdir = workdir
        self.max_concurrency = max(1, max_concurrency)

    def generate(
        self,
        prompt: str,
        json_mode: bool = True,
        *,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        os.makedirs(self.workdir, exist_ok=True)
        # Force subscription auth: strip the API key so the child never bills the paid API.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # Mark the child so ITS whisper-out hook no-ops (belt-and-suspenders vs hooks-off) —
        # blocks recursion even if the hooks-off mechanism silently fails. See Task 05.
        env["ORMAH_EXTRACTOR_CHILD"] = "1"
        # Prompt on stdin (never argv) — avoids leaking transcript text to the process list and
        # ARG_MAX failures on large transcripts.
        argv = [
            self.bin_path, "-p",
            "--model", self.model,
            "--output-format", "json",
            *_HOOKS_OFF_ARGS,
            *_TOOL_DENY_ARGS,
        ]
        sem = _semaphore(self.max_concurrency)
        with sem:
            try:
                proc = subprocess.run(
                    argv, input=prompt, capture_output=True, text=True,
                    timeout=self.timeout, cwd=self.workdir, env=env,
                )
            except subprocess.TimeoutExpired:
                logger.warning("claude -p timed out after %ss", self.timeout)
                return None
            except Exception as e:  # binary missing, OSError, etc.
                logger.warning("claude -p failed to run: %s", e)
                return None
            finally:
                # Privacy: the child writes its own transcript (private conversation text) under
                # ~/.claude/projects/<encoded-workdir>/. Delete it so no at-rest copy accumulates
                # outside Ormah's retention/deletion controls. Runs on success AND failure.
                self._purge_worker_transcripts()
        if proc.returncode != 0:
            logger.warning("claude -p exited %s: %s", proc.returncode, proc.stderr[:300])
            return None
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            logger.warning("claude -p returned a non-JSON envelope")
            return None
        result = envelope.get("result") if isinstance(envelope, dict) else None
        return result if isinstance(result, str) else None

    def _purge_worker_transcripts(self) -> None:
        """Delete the child's transcript dir so no at-rest copy of private text survives."""
        import shutil as _sh
        # Claude Code keys the dir off the REAL cwd path: /tmp -> /private/tmp on macOS. Resolve
        # symlinks or the purge (and Task 04's guard) silently target the wrong dir.
        real = os.path.realpath(self.workdir)
        encoded = "-" + real.strip("/").replace("/", "-")
        tdir = os.path.join(os.path.expanduser("~/.claude/projects"), encoded)
        try:
            _sh.rmtree(tdir, ignore_errors=True)
        except Exception:
            pass  # best-effort; the watcher also excludes this path (Task 04)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -v`
Expected: PASS (9 tests). If the spike found a different envelope field / hooks-off mechanism,
update `_HOOKS_OFF_ARGS` / the `envelope.get("result")` line and the matching tests first.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/llm/claude_cli_adapter.py \
        tests/test_background/test_claude_cli_adapter.py \
        tests/fixtures/claude_cli_envelope.json
git commit -m "feat(llm): ClaudeCliAdapter — stdin prompt, bounded concurrency, subscription, no API"
```

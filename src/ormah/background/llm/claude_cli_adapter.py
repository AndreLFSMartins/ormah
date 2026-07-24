"""Claude CLI LLM adapter — headless `claude -p` via subscription auth (no paid API)."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ormah.background.llm.base import LLMAdapter
from ormah.background.llm_errors import LlmCancelledError

logger = logging.getLogger(__name__)

# Trust boundary: the transcript is UNTRUSTED input (prompt-injection vector). The child must
# only ever emit text, never act. We pass ONE --settings override whose `permissions` block
# fully replaces whatever the operator's ~/.claude/settings.json has (verified 2026-07-02 on
# claude 2.1.156):
#   defaultMode "default" -> escape an inherited defaultMode:bypassPermissions. This is the
#     load-bearing key: neither `--allowed-tools ""`, nor the `--permission-mode default` CLI
#     flag, nor a `deny` list under an inherited bypass, overrides it. Setting defaultMode
#     here, on the same key, does. In headless -p with mode "default" and no allowed tools,
#     every tool the model attempts needs permission that no one can grant -> auto-denied.
#   allow []              -> drop the operator's inherited allow rules (e.g. Bash, Edit(./**)).
#   deny  [tool names]    -> belt-and-suspenders. NOTE: use bare tool names only. A glob rule
#     like "*"/"mcp__*" is rejected as invalid on claude 2.1.156, which discards the WHOLE
#     --settings block and silently falls back to the operator's bypassPermissions (verified
#     fail-open). Bare names are the safe form; MCP tools are already gated by defaultMode.
#   disableAllHooks true  -> the operator's own hooks AND plugin hooks otherwise FIRE in this
#     child (verified: a user SessionStart hook ran despite a hooks:{} override, because hooks
#     MERGE across sources rather than being replaced). disableAllHooks is a boolean, so the
#     --settings override actually takes effect, and it turns every non-managed hook off — no
#     recursion, no side effects. (We keep --no-session-persistence for the transcript; the
#     alternative, --setting-sources, disables hooks too but re-enables session persistence on
#     this CLI, so it is NOT used.)
_DENY_TOOLS = [
    "Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "Glob", "Grep",
    "LS", "WebFetch", "WebSearch", "Task",
]
_HARDENED_SETTINGS = json.dumps({
    "disableAllHooks": True,
    "permissions": {"defaultMode": "default", "allow": [], "deny": _DENY_TOOLS},
})

# Bound concurrent `claude -p`: one shared semaphore per distinct max_concurrency value. All
# adapters built with the same max share a bound (today ingest + maintenance read the same
# claude_cli_max_concurrency, so it is effectively global); adapters with different maxes get
# independent semaphores.
_SEMAPHORES: dict[int, threading.Semaphore] = {}
_SEM_LOCK = threading.Lock()


# session_id comes from the CLI envelope (untrusted). Only ever treat it as an exact,
# well-formed id — never as a glob pattern (a "*"/"?"/"[" could expand and delete unrelated
# transcripts). Real Claude session ids are UUIDs; this also admits hex/dash/underscore.
_SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


def _cleanup_persisted_stub(session_id: str) -> None:
    """Best-effort: delete the child's own transcript stub. Even with
    --no-session-persistence, `claude -p` writes a tiny ai-title record at
    ~/.claude/projects/<encoded-cwd>/<session_id>.jsonl. It carries ZERO conversation turns, so
    the session watcher skips it (not ingestible) — but removing it keeps ~/.claude clean and
    avoids leaving a prompt-derived title on disk. The id is validated and matched as an EXACT
    filename (no glob interpolation), so no other session's transcript is ever touched."""
    if not _SESSION_ID_RE.match(session_id or ""):
        return
    target = f"{session_id}.jsonl"
    try:
        for proj_dir in (Path.home() / ".claude" / "projects").iterdir():
            stub = proj_dir / target
            if stub.is_file():
                stub.unlink()
                return
    except OSError:
        pass


def _capture_pgid(proc):
    """Snapshot the child's process-group id AT SPAWN, while the leader is guaranteed alive.

    HIGH-1 refine (council-pr R2, Codex): the pgid MUST be captured once, up front, and stored —
    never re-derived from the pid on a later kill pass. ``claude -p`` is launched with
    ``start_new_session=True`` so the child is its own session/group leader (``pgid == pid``);
    once it exits, ``os.getpgid(pid)`` raises ProcessLookupError, so a lazily-derived pgid would
    vanish exactly when a surviving in-group grandchild still needs the escalation SIGKILL.

    Returns an ``int`` pgid for a real child, or ``None`` for a fake without a real ``pid`` (unit
    tests) so callers fall back to the per-PID ``terminate()``/``kill()`` shape.
    """
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int):
        return None
    try:
        return os.getpgid(pid)  # leader alive here -> == pid; robust if it ever differs
    except OSError:
        return pid


def _signal_group(pgid, sig: int) -> bool:
    """HIGH-2/HIGH-1 (council-pr, Codex): signal a child's WHOLE process group by its STORED pgid.

    ``claude -p`` forks grandchildren (this machine's ``~/.claude.json`` has user-scoped MCP
    servers and we pass no ``--strict-mcp-config``); those inherit the child's stdout/stderr.
    Killing only the tracked direct PID leaves a grandchild holding the pipe open, so
    ``communicate()`` never sees EOF and the shutdown drain waits the full provider timeout.
    The pgid is captured at spawn (see ``_capture_pgid``) so it survives the leader's death and
    still reaches a grandchild that ignored SIGTERM after the leader exited.

    Returns True when the group signal was delivered; False when the group is unavailable — a
    ``None`` pgid (a fake without a real pid, unit tests), or a group already fully gone — so
    callers fall back to the per-PID ``terminate()``/``kill()`` shape. ``os.killpg`` is
    suppressed on ``ProcessLookupError``/``PermissionError`` (the group may already be dead).

    RESIDUAL (accepted, tracked in the ADR): a grandchild that calls ``setsid()`` and daemonizes
    into its OWN session/process group escapes the group signal entirely — no signal-based
    approach can reap it (that needs cgroups on Linux / job objects on Windows). Out of scope.
    """
    if not isinstance(pgid, int):
        return False
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _terminate_group_or_proc(proc, pgid) -> None:
    """SIGTERM the child's process group (stored pgid); fall back to per-PID terminate()."""
    if not _signal_group(pgid, signal.SIGTERM):
        with contextlib.suppress(Exception):
            proc.terminate()


def _kill_group_or_proc(proc, pgid) -> None:
    """SIGKILL the child's process group (stored pgid); fall back to per-PID kill()."""
    if not _signal_group(pgid, signal.SIGKILL):
        with contextlib.suppress(Exception):
            proc.kill()


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
        max_concurrency: int = 1,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.bin_path = bin_path or shutil.which("claude") or "claude"
        self.max_concurrency = max(1, max_concurrency)
        # ADR-0004 slice 2: instance-scoped (never module-global — council R6). A module-level
        # flag would survive the shutdown that set it (main.lifespan catches a watcher startup
        # failure and keeps serving; nothing calls reset_adapter() on startup), poisoning every
        # later ingest/maintenance call for the life of the process.
        self._cancel_event = threading.Event()
        # HIGH-1 refine: map each in-flight proc to its pgid CAPTURED AT SPAWN, so the escalation
        # SIGKILL can target the group even after the leader dies (a re-derived pgid would be gone).
        self._active_procs: dict = {}
        self._active_lock = threading.Lock()

    def cancel_active(self) -> int:
        """Terminate this adapter's in-flight children; new calls abort until resume().

        Returns the number of processes terminated (0 when idle)."""
        self._cancel_event.set()
        return self._cancel_tracked_procs()

    def resume(self) -> None:
        """Re-arm after a RECOVERABLE cancellation (startup rollback keeps serving) or at the
        next lifespan startup (the adapter cache is module-level and outlives a reload)."""
        self._cancel_event.clear()

    def _cancel_tracked_procs(self) -> int:
        with self._active_lock:
            items = list(self._active_procs.items())  # (proc, pgid) snapshot
        for p, pgid in items:
            _terminate_group_or_proc(p, pgid)  # SIGTERM the whole group (no grandchild holds stdout)
        deadline = time.monotonic() + 5.0
        for p, _pgid in items:
            with contextlib.suppress(Exception):
                p.wait(timeout=max(0.1, deadline - time.monotonic()))
        # HIGH-1 refine (council-pr R2): escalate the group SIGKILL using the STORED pgid,
        # UNCONDITIONALLY — never gated on the direct child's poll(). If the leader already
        # exited on SIGTERM but an in-group grandchild ignored it (or still holds our stdout),
        # the group SIGKILL must still reap it; re-deriving the pgid from the dead leader would
        # raise ProcessLookupError and skip the kill, leaking the descendant and hanging the drain.
        for p, pgid in items:
            _kill_group_or_proc(p, pgid)
        return len(items)

    def generate(
        self,
        prompt: str,
        json_mode: bool = True,
        *,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_hint_seconds: float | None = None,
    ) -> str | None:
        # A batching caller can hint a longer budget for a fatter combined prompt; a plain
        # call keeps the constructor default.
        timeout = timeout_hint_seconds or self.timeout
        # Force subscription auth: strip the API key so the child never bills the paid API.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # Prompt on stdin (never argv) — avoids leaking transcript text to the process list and
        # ARG_MAX failures on large transcripts.
        schema = None
        if response_format and response_format.get("type") == "json_schema":
            schema = response_format.get("json_schema", {}).get("schema")
        argv = [
            self.bin_path, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--no-session-persistence",
            "--permission-mode", "default",
            "--settings", _HARDENED_SETTINGS,
        ]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema)]
        sem = _semaphore(self.max_concurrency)
        with sem:
            if self._cancel_event.is_set():
                # A waiter that acquired the semaphore AFTER the kill pass must not spawn a
                # replacement child mid-shutdown.
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            try:
                proc = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, cwd=tempfile.gettempdir(), env=env,
                    # HIGH-2: own session/process group so a cancel/timeout can SIGTERM the whole
                    # group (parent + any forked grandchild that inherited our stdout/stderr),
                    # not just the tracked direct PID — otherwise a grandchild keeps the pipe
                    # open, communicate() never EOFs, and the drain waits the full timeout.
                    start_new_session=True,
                )
            except Exception as e:  # binary missing, OSError, etc. -> FAST failure -> None,
                logger.warning("claude -p failed to start: %s", e)  # never slice-specific
                return None
            pgid = _capture_pgid(proc)  # snapshot NOW, while the group leader is alive (HIGH-1)
            with self._active_lock:
                self._active_procs[proc] = pgid
            if self._cancel_event.is_set():
                # Closes the creation/registration race: if cancel_active() snapshotted the
                # process set between our event check and the add() above, its kill pass never
                # saw this child. Re-checking AFTER registration guarantees either the kill pass
                # sees the proc, or we see the event.
                # B-3: kill() and wait() get their OWN suppress blocks — a single shared one
                # means a raising kill() (already-dead race) skips the reap entirely, leaking
                # the pipe fds on that path. wait() (not communicate()) matches base's
                # subprocess.run reap-only semantics: no pipe-EOF wait, just a status collect.
                _kill_group_or_proc(proc, pgid)  # group SIGKILL — reach any grandchild too (HIGH-2)
                with contextlib.suppress(Exception):
                    proc.wait()
                with self._active_lock:
                    self._active_procs.pop(proc, None)
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            # B-2: `with proc:` restores the base `subprocess.run` contract (it runs inside
            # `with Popen(...) as process:`) — __exit__ closes stdin/stdout/stderr and reaps via
            # wait() on EVERY exit path (return or exception), so a mid-flight OSError/ValueError
            # from communicate() can no longer orphan the child and retain the pipe fds. wait()
            # inside __exit__ never blocks here because every path that reaches it has already
            # killed (timeout/generic-exception) or fully drained (success) the child.
            with proc:
                try:
                    stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
                except subprocess.TimeoutExpired:
                    # B-1: base's subprocess.run does process.kill(); process.wait() on a
                    # timeout — it REAPS, it never waits for pipe EOF. communicate() here (no
                    # timeout arg) blocks until EOF on both pipes; if a grandchild inherited our
                    # stdout/stderr, that can never arrive and the drain thread hangs forever —
                    # exactly the unbounded wait this slice exists to remove. wait() only waits
                    # for the process itself to exit, which kill() already guarantees promptly.
                    _kill_group_or_proc(proc, pgid)  # group SIGKILL, then reap the direct child
                    proc.wait()
                    if self._cancel_event.is_set():
                        # A shutdown kill can surface as TimeoutExpired. It must NOT be reported
                        # as a provider timeout — slice 3 gives timeouts a failure-budget
                        # meaning, and a restart must never spend it on a cancellation.
                        raise LlmCancelledError("claude -p cancelled during shutdown") from None
                    logger.warning("claude -p timed out after %ss", timeout)
                    return None  # unchanged for now; slice 3 turns this into LlmTimeoutError
                except Exception as e:  # I/O failure mid-flight — fast failure
                    # B-2: base's subprocess.run does `except: process.kill(); raise` here —
                    # kill before the child is orphaned. HIGH-2: group SIGKILL (an already-dead
                    # process is tolerated inside _kill_group_or_proc / _signal_group).
                    _kill_group_or_proc(proc, pgid)
                    logger.warning("claude -p failed to run: %s", e)
                    return None
                finally:
                    with self._active_lock:
                        self._active_procs.pop(proc, None)
        if (proc.returncode or 0) < 0 or self._cancel_event.is_set():
            # Killed by cancel_active (negative = signal): cancelled, NOT slice evidence.
            # HIGH-1 (council-pr R3, Codex) DATA INTEGRITY: the cancel event ALONE is decisive —
            # never `and returncode != 0`. A child that HANDLES SIGTERM and exits 0 inside the 5s
            # kill fence emits partial/buffered JSON; accepting it as success made the engine
            # ADVANCE THE CURSOR on a cancelled extraction, violating this slice's invariant that
            # a cancel never advances the cursor. _cancel_event is instance-scoped and only set on
            # shutdown/rollback, so the happy path is unaffected.
            # F-4: `or 0` guards a (currently unreachable with a real Popen) None returncode —
            # a bare TypeError here would escape as a generic string and burn the per-slice cap.
            raise LlmCancelledError(f"claude -p cancelled (rc={proc.returncode})")
        if proc.returncode != 0:
            logger.warning("claude -p exited %s: %s", proc.returncode, stderr[:300])
            return None
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("claude -p returned a non-JSON envelope")
            return None
        if not isinstance(envelope, dict):
            return None
        _cleanup_persisted_stub(str(envelope.get("session_id") or envelope.get("sessionId") or ""))
        if envelope.get("is_error"):
            logger.warning("claude -p returned is_error envelope: %s", str(envelope.get("subtype"))[:100])
            return None
        if schema is not None:
            structured = envelope.get("structured_output")
            if structured is not None:
                return json.dumps(structured)
            # Fallback: for some prompt+schema pairs the CLI answers in a single text turn,
            # emitting valid schema-conformant JSON in `result` (```json-fenced) with
            # structured_output=null. Callers run extract_json + json.loads, so hand them the
            # raw result to recover; enum-integrity is normalized per-site by callers.
            result = envelope.get("result")
            return result if isinstance(result, str) and result.strip() else None
        result = envelope.get("result")
        return result if isinstance(result, str) else None

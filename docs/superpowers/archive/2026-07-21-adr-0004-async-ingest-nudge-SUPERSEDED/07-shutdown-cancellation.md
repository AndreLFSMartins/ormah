# Task 7: Bounded shutdown — cancel live `claude -p` extractions on stop

**Origin:** council R1 (codex HIGH). The shutdown drain is deliberately uncapped
(`_drain_handlers` `session_watcher.py:1358` — abandoning an in-flight ingest re-opens the
DB use-after-close window). With the worker always-on and a ~2400s extraction budget, EVERY
install could hang a restart for up to ~40 min waiting on one `subprocess.run` that cannot
see the stop event. Fix: keep the drain uncapped, but make the in-flight call FINISH FAST —
cancel the live child process. A killed extraction returns a failure, the cursor does NOT
advance, and the startup drain re-ingests the slice on next boot: durability is preserved
by the cursor, so cancellation is safe by construction.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (⚠️ FORK-ONLY — subprocess
  tracking + cancel; requires switching `subprocess.run` L137-140 to `Popen` + `communicate`)
- Modify: `src/ormah/background/llm_client.py` (upstream — generic `cancel_active_llm_calls()`
  dispatcher, no-op for adapters without `cancel_active`)
- Modify: `src/ormah/background/session_watcher.py:1374-1395` (`stop_session_watcher` calls
  the dispatcher after setting stop events, before draining)
- Test: `tests/test_background/test_claude_cli_adapter.py`, `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: always-on worker + stop path from Task 3; `LlmTimeoutError` module from Task 1.
- Produces:
  - `ClaudeCliAdapter.cancel_active() -> int` — sets a module-level cancellation event,
    then terminates every live child process (SIGTERM, then SIGKILL after 5s); returns the
    count. Each cancelled `generate()` raises **`LlmCancelledError`** (council R2 — NEVER
    `LlmTimeoutError`: a cancel says nothing about the slice; the engine maps it to
    `EXTRACT_ERR_CALL_FAILED` → uncapped TRANSIENT, so restarts can never quarantine a
    healthy slice). Calls still WAITING on the shared concurrency semaphore check the
    event after acquiring it and raise `LlmCancelledError` without spawning (council R2 —
    a single kill pass cannot see them).
  - **Declared limitation (mirrors Task 1's):** cancellation exists only in the
    `claude_cli` adapter; with ollama/litellm the drain remains bounded only by their own
    (much shorter) HTTP timeouts.
  - `llm_client.cancel_active_llm_calls() -> int` — calls `cancel_active()` on the cached
    maintenance AND ingest adapters when they define it (`getattr(..., None)`); returns
    total. Upstream-safe: adapters without the method are skipped.

- [ ] **Step 1: Write the failing tests**

```python
def test_cancel_active_terminates_running_generate(monkeypatch):
    """Start generate() on a long-lived fake child; from another thread call
    adapter.cancel_active(); generate() must raise **LlmCancelledError** (never
    LlmTimeoutError — council R4: a cancel must stay uncapped) well under 10s, and
    cancel_active() must return 1."""


def test_cancel_active_noop_when_idle():
    adapter = _make_adapter()
    assert adapter.cancel_active() == 0


def test_cancel_aborts_semaphore_waiter_without_spawning(monkeypatch):
    """council R2: max_concurrency=1, one generate() live on a long child, a second
    blocked on the semaphore. cancel_active() while both pending -> BOTH raise
    LlmCancelledError promptly and no replacement process is spawned (count Popen calls)."""


def test_popen_creation_failure_is_fast_failure(monkeypatch):
    """council R2 (critical): Popen raising FileNotFoundError/OSError returns None
    (fast failure -> EXTRACT_ERR_CALL_FAILED -> TRANSIENT), never LlmTimeoutError and
    never a slice-specific error string. Repeat > MAX_EXTRACT_FAILURES times at the
    watcher level -> cursor never advances, no skipped_slices."""


def test_adapter_generates_again_after_a_rollback_cancellation(monkeypatch):
    """council R6: a recoverable cancellation (startup rollback) must not poison the
    surviving cached adapter. cancel_active() then resume() -> generate() works."""
    adapter = _make_adapter()
    adapter.cancel_active()
    adapter.resume()
    # fake Popen returning a valid envelope
    assert adapter.generate("prompt") is not None


def test_cancel_between_creation_and_registration(monkeypatch):
    """codex R3 race: a threading.Barrier inside a fake Popen pauses generate() between
    process creation and _ACTIVE_PROCS registration while cancel_active() runs to
    completion (seeing an empty set). generate() must STILL raise LlmCancelledError
    promptly (post-registration event re-check) and the fake child must be killed."""


def test_stop_session_watcher_cancels_llm_calls(monkeypatch):
    """stop_session_watcher invokes llm_client.cancel_active_llm_calls exactly once,
    after setting handler stop events and before _drain_handlers (mock all three and
    assert call order)."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py -k cancel -v`
Expected: FAIL — `AttributeError: cancel_active`.

- [ ] **Step 3: Implement — adapter (fork-only)**

In `claude_cli_adapter.py`, replace the `subprocess.run` call (L137-140) with a tracked
`Popen`; keep every downstream branch (returncode/JSON/envelope handling) identical:

```python
# module level
_ACTIVE_PROCS: set = set()          # live Popen handles
_ACTIVE_LOCK = threading.Lock()


def _cancel_tracked_procs() -> int:
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE_PROCS)
    for p in procs:
        with contextlib.suppress(Exception):
            p.terminate()
    deadline = time.monotonic() + 5.0
    for p in procs:
        with contextlib.suppress(Exception):
            p.wait(timeout=max(0.1, deadline - time.monotonic()))
    for p in procs:
        if p.poll() is None:
            with contextlib.suppress(Exception):
                p.kill()
    return len(procs)
```

Inside `generate()` (replacing L135-146):

⚠️ **council R6 — cancellation state must be INSTANCE-scoped, not module-global.** A
module-level event stays set after the shutdown that set it: `main.lifespan` catches a
watcher startup failure and keeps serving, and nothing calls `reset_adapter()` on startup,
so the surviving cached adapter would raise `LlmCancelledError` on every later call —
poisoning all ingest AND maintenance for the life of the process. Put the event and the
process set on the adapter instance:

```python
    # in ClaudeCliAdapter.__init__
    self._cancel_event = threading.Event()
    self._active_procs: set = set()
    self._active_lock = threading.Lock()

    def cancel_active(self) -> int:
        """Terminate this adapter's in-flight children; new calls abort until resume()."""
        self._cancel_event.set()
        return self._cancel_tracked_procs()

    def resume(self) -> None:
        """Re-arm after a RECOVERABLE cancellation (startup rollback keeps serving)."""
        self._cancel_event.clear()
```

Replace every `_CANCEL_EVENT` / `_ACTIVE_PROCS` reference below with the instance
attributes. The startup-rollback path calls `cancel_active_llm_calls()` and then
`llm_client.resume_llm_adapters()` (a sibling dispatcher calling `resume()` where defined)
once the drain finishes — the app is still serving, so the adapters must work again.

⚠️ **Normal shutdown must ALSO be undone at the next startup** (council R7): the
`llm_client` caches are module-level and outlive a lifespan, so "shutdown never resumes"
would poison an in-process reload. Task 3 Step 4 calls `resume_llm_adapters()` early in
lifespan startup; this task ships that function and its regression
(`test_second_lifespan_can_generate_after_a_cancelled_first`), plus
`test_adapter_generates_again_after_a_rollback_cancellation`.

```python
        with sem:
            if _CANCEL_EVENT.is_set():
                # council R2: a waiter that acquired the semaphore AFTER the kill pass
                # must not spawn a replacement child mid-shutdown.
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            try:
                proc = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, cwd=tempfile.gettempdir(), env=env,
                )
            except Exception as e:  # council R2 (critical): missing binary/OSError is a
                logger.warning("claude -p failed to start: %s", e)   # FAST failure -> None,
                return None                                          # never slice-specific
            with _ACTIVE_LOCK:
                _ACTIVE_PROCS.add(proc)
            if _CANCEL_EVENT.is_set():
                # codex R3: closes the creation/registration race — if cancel_active()
                # snapshotted _ACTIVE_PROCS between our event check and the add() above,
                # its kill pass never saw this child. Re-checking AFTER registration
                # guarantees either the kill pass sees the proc, or we see the event.
                with contextlib.suppress(Exception):
                    proc.kill()
                    proc.communicate()
                with _ACTIVE_LOCK:
                    _ACTIVE_PROCS.discard(proc)
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                if _CANCEL_EVENT.is_set():
                    # council R4 race: a shutdown kill can surface as TimeoutExpired.
                    # Classifying it as a timeout would let a restart consume the
                    # quarantine cap for a perfectly healthy slice.
                    raise LlmCancelledError("claude -p cancelled during shutdown") from None
                logger.warning("claude -p timed out after %ss", timeout)
                raise LlmTimeoutError(f"claude -p timed out after {timeout}s") from None
            except Exception as e:  # I/O failure mid-flight — fast failure
                logger.warning("claude -p failed to run: %s", e)
                return None
            finally:
                with _ACTIVE_LOCK:
                    _ACTIVE_PROCS.discard(proc)
        if proc.returncode < 0 or (_CANCEL_EVENT.is_set() and proc.returncode != 0):
            # killed by cancel_active (negative = signal): cancelled, NOT slice evidence
            raise LlmCancelledError(f"claude -p cancelled (rc={proc.returncode})")
        if proc.returncode != 0:
            ...  # existing non-zero branch unchanged (return None)
```

plus on the class: `def cancel_active(self) -> int: _CANCEL_EVENT.set(); return
_cancel_tracked_procs()`. ⚠️ **council R4 — the event must not outlive the shutdown that
set it.** The same process can run a second FastAPI lifespan (the repo already tests that);
a stale `_CANCEL_EVENT` would make every later call raise `LlmCancelledError` forever.
With the instance scoping above, a rebuilt adapter starts clean and a surviving one is
re-armed by `resume()`. Assert both with a two-lifespan regression mirroring the existing
double-lifespan test in `tests/test_main_lifespan_shutdown.py` (~L292):
`test_second_lifespan_can_generate_after_a_cancelled_first`. `LlmCancelledError` comes from `ormah.background.llm_errors`
(Task 1). Adjust references from `proc.stdout`/`proc.stderr` to the `communicate()`
results. Add a test-only reset (`_CANCEL_EVENT.clear()`) invoked from the existing
`reset_adapter()`/fixture path so suites stay independent.

- [ ] **Step 4: Implement — dispatcher + stop hook (upstream side)**

`llm_client.py`:

Discover the caches defensively — the Beta has both, a future upstream port has only
`_cached_adapter`:

```python
def cancel_active_llm_calls() -> int:
    """Best-effort cancellation of in-flight LLM calls at shutdown.
    Adapters opt in by defining cancel_active(); others are skipped."""
    total = 0
    for name in ("_cached_adapter", "_cached_ingest_adapter"):
        adapter = globals().get(name)          # ingest cache exists only on the Beta
        cancel = getattr(adapter, "cancel_active", None)
        if callable(cancel):
            total += cancel()
    return total


def resume_llm_adapters() -> None:
    """Re-arm cancelled adapters. Called at lifespan startup and after a recoverable
    startup rollback — the module-level caches outlive a lifespan (council R7)."""
    for name in ("_cached_adapter", "_cached_ingest_adapter"):
        resume = getattr(globals().get(name), "resume", None)
        if callable(resume):
            resume()
```

⚠️ **An adapter created AFTER the cancellation snapshot is not cancelled** (council R7): a
handler still running when the stop event fires can lazily build a fresh adapter whose
event is clear, and then block for the full budget. Mitigate by calling the dispatcher in
a short loop while handlers are still in flight — e.g. cancel, then re-cancel once after a
brief wait inside `_stop_and_drain`, so a late-built adapter is caught on the second pass.
Note this as a residual race in the ADR if a loop is judged too blunt.

(On the Beta both caches exist; the `globals().get` form is what keeps this function
portable if it is ever re-derived upstream.)

`session_watcher.py` `stop_session_watcher` (L1374) — ⚠️ **order matters (council R4):** the
current body joins `startup_thread` (L1388-1390) BEFORE `_drain_handlers` (L1391), and that
join blocks on the running extraction. Cancelling only just before the drain would still
hang for the full budget. Required order:

1. `w.handler._stop_event.set()` (all handlers)
2. `w.handler.cancel_pending_timers()`
3. **`cancel_active_llm_calls()`**  ← new, BEFORE any join
4. `w.observer.stop()` (guarded `is not None`)
5. `w.startup_thread.join()`
6. `_drain_handlers(...)` (still uncapped — correctness over a deadline)

⚠️ **The transactional startup-rollback block (L1339-1354) must use the SAME sequence**
(council R5): with several watch roots, an Observer failure on root 2 while root 1 already
has a live extraction would otherwise join and wait out the whole budget. Extract the
sequence into one module-level helper (e.g. `_stop_and_drain(watches)`) and call it from
BOTH `stop_session_watcher` and the rollback path. Regression:
`test_startup_rollback_cancels_active_extraction`.

Extend the shutdown-order test to assert cancellation is called before the join:

```python
    from ormah.background.llm_client import cancel_active_llm_calls
    cancelled = cancel_active_llm_calls()
    if cancelled:
        logger.info("Cancelled %d in-flight LLM call(s) for shutdown", cancelled)
```

- [ ] **Step 4b: Migrate the subprocess.run patch sites (codex R3)**

The Popen migration breaks every test that patches `subprocess.run` (Task 1's timeout test
included) — they would hit the real binary. Build ONE fake-Popen helper in
`tests/test_background/test_claude_cli_adapter.py` implementing `communicate` (honoring the
`timeout=` kwarg), `wait`, `poll`, `terminate`, `kill`, and `returncode`; then
`grep -n "subprocess.run" tests/test_background/test_claude_cli_adapter.py` and migrate
EVERY patch site to it (zero remaining hits). Task 1's
`test_raises_llm_timeout_error_on_timeout` re-targets the fake's `communicate` raising
`subprocess.TimeoutExpired`; cancellation tests assert `LlmCancelledError` (NEVER
`LlmTimeoutError` — the amended contract).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py tests/test_background/test_session_watcher.py tests/test_main_lifespan_shutdown.py -v`
Expected: PASS, including Task 3's lifespan test (drain now bounded in practice).

- [ ] **Step 6: Lint + commit**

One commit (Beta-only, like the rest of this plan):

```bash
ruff check src/ tests/
git add src/ormah/background/llm_client.py src/ormah/background/session_watcher.py \
        src/ormah/background/llm/claude_cli_adapter.py tests/
git commit -m "feat(ingest): cancel in-flight LLM extractions before joining on shutdown (ADR-0004)"
```

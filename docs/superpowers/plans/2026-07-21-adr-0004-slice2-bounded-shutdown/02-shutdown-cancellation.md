# Task 2: Bounded shutdown — cancel live `claude -p` extractions on stop

**Origin:** council review of ADR-0004. **(Anchors refreshed 2026-07-23 for merged slice 1.)**
The shutdown wait is deliberately uncapped — abandoning an in-flight ingest re-opens the DB
use-after-close window (#52). Post-slice-1 that wait is **`SessionWatch.handler.join_drain()`**
(`stop_session_watcher` `session_watcher.py:1538-1539`), followed by `_drain_handlers`
(L1507-1520) polling `in_flight_count()`. With the worker always-on (`_drain_forever` L1180)
and a ~2400s extraction budget, EVERY install could hang a restart for up to ~40 min waiting
on one `subprocess.run` (L137-140) that cannot see the stop event: `_run_job` (L1231) checks
`_stop_event` only BEFORE it starts, so a call already inside `_ingest_session` runs to the
timeout. Fix: keep the wait uncapped, but make the in-flight call FINISH FAST — cancel the
live child process. A killed extraction raises `LlmCancelledError`, which — once the Task-2
engine mapping treats it as a provider-wide transient (see Step 3b) — requeues the job and
does NOT advance the cursor, so the startup drain re-ingests the slice on next boot.
Durability is preserved by the cursor; cancellation is safe **provided the cancel is mapped
away from the per-slice failure cap** (`_record_extract_failure` L947-1001).

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (subprocess tracking + cancel;
  switch `subprocess.run` L137-140 to `Popen` + `communicate`, keeping the `with sem:` guard
  L135 and `_cleanup_persisted_stub(...)` L157 intact)
- Modify: `src/ormah/background/llm_client.py` (`cancel_active_llm_calls()` /
  `resume_llm_adapters()` dispatchers, no-ops for adapters without the methods)
- 🔴 Modify: `src/ormah/engine/memory_engine.py` (`_extract_memories_llm` L2842 — add
  `except LlmCancelledError: return EXTRACT_ERR_CALL_FAILED` BEFORE the generic
  `except Exception` L2903, so a cancel never reaches `_ingest_session`'s per-slice cap)
- Modify: `src/ormah/main.py` (call `resume_llm_adapters()` right after `engine.startup()`
  L191, before the scheduler/watcher start — ships in THIS commit so no window exists where a
  cancelled adapter survives un-re-armed). NOTE: the R1 `app.state.session_watches` unification
  already landed in slice 1 (L250 / L293-294) — do NOT re-do it.
- Modify: `src/ormah/background/session_watcher.py` — extract a `_stop_and_drain(watches)`
  helper and call it from both `stop_session_watcher` (L1523) and the transactional startup
  rollback (L1487-1503); the helper fires `cancel_active_llm_calls()` after `wake()`, before
  `join_drain()`
- Test: `tests/test_background/test_claude_cli_adapter.py`,
  `tests/test_background/test_session_watcher.py`, `tests/test_engine/test_ingest_extraction.py`

**Interfaces:**
- Consumes: the always-on worker + stop path from slice 1; `llm_errors` from Task 1.
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
    process creation and its registration in _active_procs while cancel_active() runs to
    completion (seeing an empty set). generate() must STILL raise LlmCancelledError
    promptly (post-registration event re-check) and the fake child must be killed."""


def test_stop_session_watcher_cancels_llm_calls(monkeypatch):
    """stop_session_watcher (via _stop_and_drain) invokes cancel_active_llm_calls exactly
    once, AFTER setting handler stop events + wake() and BEFORE join_drain()/_drain_handlers
    (mock them and assert call order)."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py -k cancel -v`
Expected: FAIL — `AttributeError: cancel_active`.

- [ ] **Step 3: Implement — adapter (fork-only)**

In `claude_cli_adapter.py`, replace the `subprocess.run` call (L137-140) with a tracked
`Popen`; keep every downstream branch (returncode/JSON/envelope handling) identical:

```python
    # method on ClaudeCliAdapter — instance-scoped, see the note above
    # (council R1/MEDIUM-D: indentation fixed — the whole body is INSIDE the method)
    def _cancel_tracked_procs(self) -> int:
        with self._active_lock:
            procs = list(self._active_procs)
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

Every snippet below uses those instance attributes. The startup-rollback path calls `cancel_active_llm_calls()` and then
`llm_client.resume_llm_adapters()` (a sibling dispatcher calling `resume()` where defined)
once the drain finishes — the app is still serving, so the adapters must work again.

⚠️ **Normal shutdown must ALSO be undone at the next startup:** the `llm_client` caches
are module-level and outlive a lifespan, so "shutdown never resumes" would poison an
in-process reload. This task ships `resume_llm_adapters()`, its call early in
`main.lifespan` startup, and the regression
(`test_second_lifespan_can_generate_after_a_cancelled_first`), plus
`test_adapter_generates_again_after_a_rollback_cancellation`.

```python
        with sem:
            if self._cancel_event.is_set():
                # A waiter that acquired the semaphore AFTER the kill pass must not spawn
                # a replacement child mid-shutdown.
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            try:
                proc = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, cwd=tempfile.gettempdir(), env=env,
                )
            except Exception as e:  # council R2 (critical): missing binary/OSError is a
                logger.warning("claude -p failed to start: %s", e)   # FAST failure -> None,
                return None                                          # never slice-specific
            with self._active_lock:
                self._active_procs.add(proc)
            if self._cancel_event.is_set():
                # Closes the creation/registration race — if cancel_active() snapshotted
                # the process set between our event check and the add() above, its kill
                # pass never saw this child. Re-checking AFTER registration guarantees
                # either the kill pass sees the proc, or we see the event.
                with contextlib.suppress(Exception):
                    proc.kill()
                    proc.communicate()
                with self._active_lock:
                    self._active_procs.discard(proc)
                raise LlmCancelledError("llm call aborted: shutdown in progress")
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                if self._cancel_event.is_set():
                    # A shutdown kill can surface as TimeoutExpired. It must NOT be
                    # reported as a provider timeout — slice 3 gives timeouts a
                    # failure-budget meaning, and a restart must never spend it.
                    raise LlmCancelledError("claude -p cancelled during shutdown") from None
                logger.warning("claude -p timed out after %ss", timeout)
                return None      # unchanged for now; slice 3 turns this into LlmTimeoutError
            except Exception as e:  # I/O failure mid-flight — fast failure
                logger.warning("claude -p failed to run: %s", e)
                return None
            finally:
                with self._active_lock:
                    self._active_procs.discard(proc)
        if proc.returncode < 0 or (self._cancel_event.is_set() and proc.returncode != 0):
            # killed by cancel_active (negative = signal): cancelled, NOT slice evidence
            raise LlmCancelledError(f"claude -p cancelled (rc={proc.returncode})")
        if proc.returncode != 0:
            ...  # existing non-zero branch unchanged (return None)
```

plus `cancel_active()` / `resume()` exactly as shown in the instance-scoping note above. ⚠️ **council R4 — the event must not outlive the shutdown that
set it.** The same process can run a second FastAPI lifespan (the repo already tests that);
a module-level flag would make every later call raise `LlmCancelledError` forever.
With the instance scoping above, a rebuilt adapter starts clean and a surviving one is
re-armed by `resume()`. Assert both with a two-lifespan regression mirroring the existing
double-lifespan test in `tests/test_main_lifespan_shutdown.py` (~L292):
`test_second_lifespan_can_generate_after_a_cancelled_first`. `LlmCancelledError` comes from `ormah.background.llm_errors` (Task 1). Adjust references
from `proc.stdout`/`proc.stderr` to the `communicate()` results. Because the event lives on
the instance, a fresh adapter per test is isolated by construction — no global reset.

- [ ] **Step 3b: 🔴 Map cancel away from the per-slice cap (engine) — MANDATORY**

Making the adapter *raise* introduces a data-loss path that did not exist while it only
returned `None`. In `memory_engine.py._extract_memories_llm` (L2842), the extraction body is
wrapped in a broad `except Exception` (L2903) that returns a **generic** error string. That
string is neither `EXTRACT_ERR_NO_PROVIDER` nor `EXTRACT_ERR_CALL_FAILED`, so
`_ingest_session` (L1044) routes it to `_record_extract_failure` — the per-slice cap that
SKIPS the slice after `MAX_EXTRACT_FAILURES` (observable data loss). Add a dedicated catch
ABOVE the generic one:

```python
        except LlmCancelledError:
            # A host cancellation (shutdown/stop) says NOTHING about this slice. Route it to
            # the provider-wide transient sentinel so _ingest_session requeues (never counts
            # it toward the per-slice cap). ADR-0004 H1: a cancel must never burn a slice.
            return EXTRACT_ERR_CALL_FAILED
        except Exception as e:
            ...  # existing generic handler unchanged
```

Import `LlmCancelledError` from `ormah.background.llm_errors` (Task 1). Failing test
(`tests/test_engine/test_ingest_extraction.py`):

```python
def test_cancelled_extraction_maps_to_call_failed_not_slice_failure(monkeypatch):
    """A LlmCancelledError from the adapter must surface as EXTRACT_ERR_CALL_FAILED
    (provider-wide transient), NOT as a slice-specific failure that _ingest_session
    would count toward MAX_EXTRACT_FAILURES and eventually skip (data loss)."""
    from ormah.background import llm_client
    from ormah.background.llm_errors import LlmCancelledError

    def _raise(*a, **k):
        raise LlmCancelledError("shutdown")
    monkeypatch.setattr(llm_client, "ingest_llm_generate", _raise)
    # provider configured so the None-path would say CALL_FAILED anyway; assert the RAISE path
    assert engine._extract_memories_llm("x" * 200) == EXTRACT_ERR_CALL_FAILED
```

Plus a watcher-level regression proving the cap is not burned:
`test_repeated_cancellations_never_skip_a_slice` — feed `_ingest_session` a cancel
`MAX_EXTRACT_FAILURES + 1` times at the same offset and assert the cursor never advances and
`skipped_slices` stays empty. Mirror the EXISTING `test_provider_wide_call_failure_never_skips_slice`
(`tests/test_background/test_session_watcher.py:463-488`), which already proves this for the
`None` path — swap `None` for a raised `LlmCancelledError` (council LOW-F: the previously-cited
`test_reconcile_never_parks_transient_failures` does not exist).

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

⚠️ **An adapter created AFTER the cancellation snapshot is not cancelled** (council R7 →
upgraded to HIGH-C): a handler still running when the stop event fires can lazily build a
fresh adapter whose event is clear, and then block for the full budget. **This is NOT a
documented residual — it is closed deterministically** by the `_stop_and_drain` fence loop
above (`while any drain alive: cancel_active_llm_calls(); join_drain(timeout=0.2)`): a
late-built adapter registers its `Popen` in `_active_procs`, and the next loop iteration's
`cancel_active_llm_calls()` kills it. The loop terminates only when every drain thread has
exited, so shutdown is bounded by construction, not by a fixed number of passes.

(On the Beta both caches exist; the `globals().get` form is what keeps this function
portable if it is ever re-derived upstream.)

`session_watcher.py` — ⚠️ **the wait point moved in slice 1 (anchors refreshed).** There is
no `startup_thread` join anymore (the startup discovery sweep is a daemon, L1478-1481). The
uncapped wait is now **`w.handler.join_drain()`** — it blocks until `_drain_forever` finishes
its current `_run_job`, which is stuck in `subprocess.run`. Cancelling must happen **after
`wake()`, before `join_drain()`**. Extract the shared sequence into one module-level helper
`_stop_and_drain(watches, *, rearm=False)` and call it from BOTH `stop_session_watcher`
(L1523-1545) and the transactional startup-rollback block inside `start_session_watcher`
(L1487-1503).

🔴 **HIGH-B (council R1, Codex) — rollback must OWN the root it is constructing.** Today
`handler.start_drain()` (L1470) starts the drain BEFORE `observer.start()` (L1475), and the
`SessionWatch` is appended to `watches` only AFTER (L1482). If `observer.start()` raises, the
current root's handler is already draining (possibly extracting a recovered `spool.recover()`
job) but is **absent from `watches`** — so `_stop_and_drain(watches)` never `join_drain()`s
it, and because `main.lifespan` catches the failure and keeps serving (`main.py:265-266`) it
is also absent from `app.state.session_watches`. That orphan drain thread can then touch the
DB after `engine.shutdown()` closes it (#52 use-after-close). **Fix:** append a **provisional
`SessionWatch` BEFORE `observer.start()`** (observer filled in after it returns), so every
started handler is always in `watches`; the rollback then cancels AND joins it. Regression:
`test_startup_rollback_drains_failing_roots_own_inflight_extraction` — the root whose Observer
fails has a recovered in-flight extraction; assert it is cancelled, its drain thread joined,
and no engine access after rollback.

🔴 **HIGH-C (council R2, Codex; = Cursor's "2nd pass optional") — the cancel fence must be
DETERMINISTIC, not a single timed re-pass.** A job that passed `_run_job`'s stop-check (L1235)
before `_stop_event` was set can still be in parse/metadata during the cancel pass, then
lazily build its (instance-scoped, clean) adapter AFTER the snapshot and spawn a fresh 2400s
`Popen` — `join_drain()` then waits the full budget. A fixed second pass does not close this.
**Fix:** `_stop_and_drain` loops cancel + bounded join until every drain is dead:

```python
def _stop_and_drain(watches, *, rearm=False):
    for w in watches:
        w.handler._stop_event.set()          # 1. no NEW job starts (L1235 refuses)
    for w in watches:
        if w.observer is not None:
            w.observer.stop()
        w.handler.cancel_pending_timers()
        w.handler.wake()                     # 2. unblock the idle wait
    # 3. DETERMINISTIC FENCE: repeatedly cancel + bounded-join until all drains exit.
    #    A late-built adapter is registered in _active_procs by the time the NEXT
    #    iteration's cancel runs, so it is killed on the following pass — bounded, not "documented".
    while any(w.handler.drain_alive() for w in watches):
        cancel_active_llm_calls()            # global (module-level adapter caches) -> covers late adapters
        for w in watches:
            w.handler.join_drain(timeout=0.2)
    _drain_handlers([w.handler for w in watches])   # 4. in_flight_count()==0 -> returns at once
    for w in watches:
        if w.observer is not None:
            w.observer.join(timeout=5)
    if rearm:                                # 5. HIGH-A: rollback keeps serving -> re-arm adapters
        resume_llm_adapters()
```

`drain_alive()` is a tiny new `SessionHandler` accessor (`return self._drain_thread.is_alive()`).
`stop_session_watcher` calls `_stop_and_drain(watches)` (rearm defaults False — a normal
shutdown must NOT resume: the process is going away and the DB is about to close). The rollback
`except` calls `_stop_and_drain(watches, rearm=True)` **before** `raise`.

🔴 **HIGH-A (council R1, Cursor) — rollback must `resume_llm_adapters()`; shutdown must NOT.**
`_stop_and_drain` is shared, and the scheduler is already live (`main.py:205`) before the
watcher (`main.py:246`). After a rollback the process keeps serving, so leaving the adapters
cancelled poisons every later maintenance AND ingest LLM call until restart. The `rearm=True`
branch above fixes it; the normal shutdown path leaves `rearm=False`. Regression:
`test_startup_rollback_rearms_adapters_and_serves` (scheduler active; after rollback a
maintenance `llm_generate` still succeeds).

Replace the earlier Step-1 `test_stop_session_watcher_cancels_llm_calls` "exactly once"
assertion with a **barrier test** that delays adapter construction until after the first cancel
pass and still proves `join_drain()` completes in bounded time
(`test_late_built_adapter_is_still_cancelled_bounded`).

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
EVERY patch site to it (zero remaining hits).

🔴 **MEDIUM-E (council, Codex) — a provider TIMEOUT must STILL return `None` in slice 2,
never raise.** `LlmTimeoutError` is DEFINED in Task 1 but nothing raises it this slice (Task 2
only adds an engine catch for `LlmCancelledError`). If a `TimeoutExpired` were mapped to a
raised `LlmTimeoutError` now, it would propagate past the engine's `LlmCancelledError`-only
catch → generic string → `_record_extract_failure` → **the exact per-slice cap burn Step 3b
prevents for cancel, reintroduced for timeout.** So the fake's `communicate` raising
`subprocess.TimeoutExpired` must exercise the **returns-`None`** path (rename the existing
regression, e.g. `test_generate_returns_none_on_timeout`), NOT a raise. Raising
`LlmTimeoutError` — with its full engine/watcher classification and cap policy — is slice 3's
job. Cancellation tests assert `LlmCancelledError` (NEVER `LlmTimeoutError`).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py tests/test_background/test_session_watcher.py tests/test_main_lifespan_shutdown.py -v`
Expected: PASS, including Task 3's lifespan test (drain now bounded in practice).

- [ ] **Step 6: Lint + commit**

One commit — adapter, dispatchers, stop ordering and lifespan re-arm are a single
behavioural change and must not be split:

```bash
ruff check src/ tests/
git add src/ormah/background/llm_client.py src/ormah/background/session_watcher.py \
        src/ormah/background/llm/claude_cli_adapter.py src/ormah/engine/memory_engine.py \
        src/ormah/main.py tests/
git commit -m "feat(ingest): cancel in-flight LLM extractions before joining on shutdown (ADR-0004)"
```

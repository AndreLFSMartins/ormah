# Council PR Operability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the council-pr HIGH findings on operability masking: C1 (`run_all_tasks` always returns `status: "completed"` and HTTP 200 even when a task fails) and C2 (scheduler-independent backfill fallback gives up silently after 5 attempts, with no degraded signal and no lifecycle control). Expanded after `/council` plan review surfaced two convergent HIGH blockers (CH1 daemon lifecycle/singleton, CH2 outage invisible to `/admin/health`) plus two scope decisions (I1 HTTP status, I2 UI), both resolved by André: **I1 = HTTP 503 on degraded**, **I2 = UI fix in this PR**.

**Architecture:** Three tasks. Task 1 derives `status` from results in `routes_admin.py` and returns HTTP 503 (via `JSONResponse`) when any task failed. Task 2 rewrites `_start_backfill_fallback` in `main.py` to be lifecycle-aware — a `threading.Event` stop signal, a singleton guard, an indefinite backoff-capped retry loop (subsumes the old C2 `while True`), and a module-level `_fallback_degraded` flag that `/admin/health` consults when no scheduler is present; lifespan shutdown stops and joins the thread. Task 3 makes the UI consume the new degraded contract. No new infrastructure, no new dependencies.

**Tech Stack:** Python 3.11, FastAPI, Starlette `JSONResponse`, pytest, monkeypatch; UI is React + TypeScript (Vite), verified via `tsc && vite build` (no UI test harness exists — out of scope, see Task 3 note).

---

## File Map

| Action | File | Change |
|--------|------|--------|
| Modify | `src/ormah/api/routes_admin.py` (`run_all_tasks`, ~L269-291) | Derive `status` from results; return `JSONResponse(503)` when any task failed (C1 / I1) |
| Modify | `src/ormah/api/routes_admin.py` (`health`, ~L103-112) | When no scheduler, consult `main._fallback_degraded` and report `status: "degraded"` (CH2) |
| Modify | `src/ormah/main.py` (L47-85, lifespan shutdown ~L140-152) | Lifecycle-aware fallback: stop event, singleton guard, indefinite retry, `_fallback_degraded` flag, stop+join on shutdown (CH1 + C2) |
| Modify | `tests/test_api/test_admin_embedding_backfill_task.py` | C1/I1 regression tests (degraded body + HTTP 503) |
| Modify | `tests/test_main_backfill_fallback.py` | Replace give-up test; add indefinite-retry, singleton, stop-on-shutdown, degraded-flag tests |
| Modify | `tests/test_api/test_routes.py` | Health-degraded-when-no-scheduler regression test |
| Modify | `ui/src/api.ts` (`runAllTasks`, L109-111) | Tolerate HTTP 503 + return parsed degraded body |
| Modify | `ui/src/components/AdminPanel.tsx` (`handleRunAll`, L111-124) | Branch on `result.status`; warn and name failed tasks when degraded |

---

### Task 1: C1 / I1 — `run_all_tasks` returns `status: "degraded"` and HTTP 503 when any task fails

**Files:**
- Modify: `src/ormah/api/routes_admin.py` (`run_all_tasks`, ~L269-291)
- Test: `tests/test_api/test_admin_embedding_backfill_task.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api/test_admin_embedding_backfill_task.py`:

```python
def test_run_all_tasks_degraded_returns_503_when_a_task_raises(monkeypatch):
    """C1/I1: a failed task yields status=degraded AND HTTP 503 (not 200)."""
    import importlib
    import json
    from unittest.mock import MagicMock

    from fastapi.responses import JSONResponse

    import ormah.background.embedding_backfill as ebf
    from ormah.api import routes_admin

    def _raise(engine):
        raise RuntimeError("encoder down")

    monkeypatch.setattr(ebf, "run_embedding_backfill", _raise)

    # Stub every other runner so real background code doesn't run with a mock engine.
    for task_id, (module_path, func_name) in routes_admin._TASK_RUNNERS.items():
        if task_id != "embedding_backfill":
            mod = importlib.import_module(module_path)
            monkeypatch.setattr(mod, func_name, lambda e: None)

    mock_request = MagicMock()
    mock_request.app.state.engine = MagicMock()

    result = routes_admin.run_all_tasks(mock_request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    body = json.loads(bytes(result.body))
    assert body["status"] == "degraded"
    assert body["results"]["embedding_backfill"].startswith("error:")


def test_run_all_tasks_completed_returns_dict_when_all_ok(monkeypatch):
    """Happy path stays a plain dict (HTTP 200) with status=completed."""
    import importlib
    from unittest.mock import MagicMock

    from ormah.api import routes_admin

    for task_id, (module_path, func_name) in routes_admin._TASK_RUNNERS.items():
        mod = importlib.import_module(module_path)
        monkeypatch.setattr(mod, func_name, lambda e: None)

    mock_request = MagicMock()
    engine = MagicMock()
    engine.builder.incremental_update.return_value = (0, 0)
    mock_request.app.state.engine = engine

    result = routes_admin.run_all_tasks(mock_request)

    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert all(v == "ok" for v in result["results"].values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api/test_admin_embedding_backfill_task.py -v`
Expected: `test_run_all_tasks_degraded_returns_503_when_a_task_raises` FAILS — current code returns a `dict` with `status: "completed"`, so `isinstance(result, JSONResponse)` is False. The happy-path test passes already.

- [ ] **Step 3: Implement the fix**

In `src/ormah/api/routes_admin.py`, add the import near the top of the file (next to the existing FastAPI imports):

```python
from fastapi.responses import JSONResponse
```

Replace the final `return` of `run_all_tasks` (currently `return {"status": "completed", "results": results}`):

```python
    has_errors = any(v.startswith("error:") for v in results.values())
    if has_errors:
        # I1: a partial failure must not look like success to HTTP-only callers
        # (cron, scripts). Surface it as 503 while keeping the per-task body.
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "results": results},
        )
    return {"status": "completed", "results": results}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api/test_admin_embedding_backfill_task.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/api/routes_admin.py tests/test_api/test_admin_embedding_backfill_task.py
git commit -m "fix(api): run_all_tasks returns status=degraded + HTTP 503 when any task fails (C1/I1)"
```

---

### Task 2: CH1 + CH2 + C2 — lifecycle-aware fallback with degraded signal and indefinite retry

**Files:**
- Modify: `src/ormah/main.py` (L47-85; lifespan shutdown ~L140-152)
- Modify: `src/ormah/api/routes_admin.py` (`health`, ~L103-112)
- Modify: `tests/test_main_backfill_fallback.py`
- Modify: `tests/test_api/test_routes.py`

This task subsumes the original C2 (`while True`): the new retry loop is indefinite (backoff-capped) **and** lifecycle-aware. The module-level `_fallback_degraded` flag is the CH2 fix; the stop event + singleton guard are the CH1 fix.

- [ ] **Step 1: Write the failing fallback tests**

In `tests/test_main_backfill_fallback.py`:

Remove the entire test `test_fallback_gives_up_after_budget_without_raising` (it codifies the broken give-up behavior and references `main._BACKFILL_FALLBACK_MAX_ATTEMPTS`, which is being deleted).

**Also update the pre-existing `test_fallback_retries_until_success`** (already in the file): its `monkeypatch.setattr("time.sleep", lambda s: real_sleep(0.001))` line must become `monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)`. The new loop sleeps via `stop_event.wait(delay)` (a `threading.Event` method), so patching `time.sleep` is a no-op — shrinking the backoff constant is what makes the interruptible wait return fast in tests while preserving the production stop-event pattern.

Add a fixture-style reset at the top of the file (after `real_sleep = _time.sleep`) so module-global state never leaks between tests:

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_fallback_state():
    main._stop_backfill_fallback()  # tear down any thread a prior test started
    main._fallback_degraded = False
    yield
    main._stop_backfill_fallback()
    main._fallback_degraded = False
```

Add these tests:

```python
def test_fallback_keeps_retrying_past_old_budget(monkeypatch):
    """C2: fallback does not give up after 5 attempts — retries until success."""
    calls = []

    def _mostly_failing(engine):
        calls.append(engine)
        if len(calls) <= 6:  # fail more than the old hard budget of 5
            raise RuntimeError("still incomplete")
        # 7th call succeeds (returns None)

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill",
        _mostly_failing,
    )
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 7, timeout=3.0)
    real_sleep(0.05)
    assert len(calls) == 7  # succeeded on the 7th attempt (past the old budget of 5)


def test_fallback_sets_degraded_flag_on_failure_clears_on_success(monkeypatch):
    """CH2: persistent failure is observable via _fallback_degraded; clears on recovery."""
    calls = []

    def _flaky(engine):
        calls.append(engine)
        if len(calls) < 3:
            raise RuntimeError("still incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _flaky)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    # After the first failure, before success, the flag is set.
    _wait_for(lambda: main._fallback_degraded is True, timeout=2.0)
    assert main._fallback_degraded is True
    # On eventual success it clears.
    _wait_for(lambda: main._fallback_degraded is False and len(calls) >= 3, timeout=2.0)
    assert main._fallback_degraded is False


def test_fallback_is_singleton(monkeypatch):
    """CH1: a second start while one is alive does not spawn a second thread."""
    started = []

    def _block_forever(engine):
        started.append(engine)
        raise RuntimeError("never closes")  # keeps the loop alive

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _block_forever)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: main._fallback_thread is not None
              and main._fallback_thread.is_alive(), timeout=2.0)
    first = main._fallback_thread
    main._start_backfill_fallback(object())  # second start — must be a no-op
    assert main._fallback_thread is first  # same thread, not replaced


def test_fallback_stops_on_shutdown(monkeypatch):
    """CH1: _stop_backfill_fallback stops a permanently-failing fallback."""
    calls = []

    def _boom(engine):
        calls.append(engine)
        raise RuntimeError("permanently incomplete")

    monkeypatch.setattr(
        "ormah.background.embedding_backfill.run_embedding_backfill", _boom)
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)

    main._start_backfill_fallback(object())
    _wait_for(lambda: len(calls) >= 1, timeout=2.0)
    main._stop_backfill_fallback()
    assert main._fallback_thread is None or not main._fallback_thread.is_alive()
    settled = len(calls)
    real_sleep(0.1)
    assert len(calls) == settled  # no further attempts after stop
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: FAILs / collection errors — `main._stop_backfill_fallback`, `main._fallback_degraded`, and `main._fallback_thread` do not exist yet.

- [ ] **Step 3: Implement the fallback rewrite in `src/ormah/main.py`**

**3a.** Replace the constants block (lines 47-53). Remove `_BACKFILL_FALLBACK_MAX_ATTEMPTS`:

**Before:**
```python
# Embedding-backfill fallback: how many times the daemon thread retries the
# reconciliation (with exponential backoff) before giving up. The recurring job /
# sleep-cycle remains the long-term net; this only covers a scheduler that failed
# to start plus a transient encoder outage at boot.
_BACKFILL_FALLBACK_MAX_ATTEMPTS = 5
_BACKFILL_FALLBACK_BASE_BACKOFF = 30.0  # seconds
_BACKFILL_FALLBACK_MAX_BACKOFF = 600.0  # seconds
```

**After:**
```python
import threading

# Embedding-backfill fallback (#32, council C2/CH1/CH2): when the scheduler fails
# to start, a daemon thread heals missing vectors off the bind path. It retries
# indefinitely with backoff (capped) so a persistent encoder outage recovers
# automatically when the encoder returns. Lifecycle is controlled by a stop event
# and a singleton guard; _fallback_degraded exposes a persistent outage to
# /admin/health while no scheduler exists.
_BACKFILL_FALLBACK_BASE_BACKOFF = 30.0  # seconds
_BACKFILL_FALLBACK_MAX_BACKOFF = 600.0  # seconds

_fallback_thread: threading.Thread | None = None
_fallback_stop_event: threading.Event | None = None
_fallback_degraded: bool = False
```

**3b.** Replace `_start_backfill_fallback` (lines 56-85) and add `_stop_backfill_fallback`:

```python
def _start_backfill_fallback(engine) -> None:
    """Heal missing vectors off a daemon thread when the scheduler is unavailable
    (#32). Off the bind path -- never blocks startup. Retries with backoff
    (capped) until the gap closes; never gives up, so a persistent encoder outage
    recovers automatically. Singleton: a second call while one thread is alive is
    a no-op, so a lifespan restart cannot accumulate concurrent fallbacks."""
    global _fallback_thread, _fallback_stop_event, _fallback_degraded
    import time

    if _fallback_thread is not None and _fallback_thread.is_alive():
        return  # singleton guard (CH1)

    stop_event = threading.Event()
    _fallback_stop_event = stop_event
    _fallback_degraded = False

    def _run():
        global _fallback_degraded
        from ormah.background.embedding_backfill import run_embedding_backfill

        delay = _BACKFILL_FALLBACK_BASE_BACKOFF
        attempt = 0
        while not stop_event.is_set():
            attempt += 1
            try:
                run_embedding_backfill(engine)
                _fallback_degraded = False  # gap closed (CH2: recovery observable)
                return
            except Exception as e:
                _fallback_degraded = True  # CH2: persistent outage is observable
                logger.warning(
                    "Embedding backfill fallback attempt %d failed: %s", attempt, e,
                )
                # Interruptible sleep -- shutdown wakes us immediately (CH1).
                if stop_event.wait(delay):
                    return
                delay = min(delay * 2, _BACKFILL_FALLBACK_MAX_BACKOFF)

    thread = threading.Thread(
        target=_run, name="embedding-backfill-fallback", daemon=True
    )
    _fallback_thread = thread
    thread.start()


def _stop_backfill_fallback() -> None:
    """Signal the fallback thread to stop and join it (CH1). Idempotent."""
    global _fallback_thread
    if _fallback_stop_event is not None:
        _fallback_stop_event.set()
    if _fallback_thread is not None:
        _fallback_thread.join(timeout=5.0)
        _fallback_thread = None
```

**3c.** In `lifespan`, add the fallback teardown to the shutdown section. After the hippocampus shutdown block and before/with the scheduler shutdown (around line 147-150), add:

```python
    # Shutdown — stop the scheduler-independent backfill fallback if it is running
    _stop_backfill_fallback()
```

(Place it just before `if hasattr(app.state, "scheduler"):` so it runs regardless of scheduler presence.)

- [ ] **Step 4: Implement the health-degraded signal in `src/ormah/api/routes_admin.py`**

Replace the `health` function body (currently L103-112) so that, when no scheduler/job tracker exists, it consults the fallback degraded flag:

```python
@router.get("/health")
def health(request: Request):
    tracker = getattr(request.app.state, "job_tracker", None)
    result: dict = {"status": "ok"}
    if tracker is not None:
        result["jobs"] = tracker.snapshot()
    else:
        # No scheduler: the backfill fallback is the only healer. Surface a
        # persistent outage that would otherwise be invisible (council CH2).
        from ormah import main as _main

        if getattr(_main, "_fallback_degraded", False):
            result["status"] = "degraded"
            result["embedding_backfill"] = "degraded: fallback retrying"
    manager = getattr(request.app.state, "maintenance_manager", None)
    if manager is not None:
        result["maintenance"] = manager.get_status()
    return result
```

(The `from ormah import main` is a deferred import inside the function to avoid an import cycle at module load — `main` imports the admin router at startup.)

- [ ] **Step 5: Write the health regression test**

Add to `tests/test_api/test_routes.py`:

```python
def test_health_degraded_when_no_scheduler_and_fallback_failing(monkeypatch):
    """CH2: with no scheduler, a degraded fallback makes /admin/health degraded."""
    from unittest.mock import MagicMock

    from ormah import main as _main
    from ormah.api import routes_admin

    monkeypatch.setattr(_main, "_fallback_degraded", True)

    request = MagicMock()
    # No job_tracker on app.state -> getattr returns the default (None).
    request.app.state = MagicMock(spec=[])  # empty spec: no job_tracker, no manager

    result = routes_admin.health(request)

    assert result["status"] == "degraded"
    assert result["embedding_backfill"].startswith("degraded")


def test_health_ok_when_no_scheduler_and_fallback_healthy(monkeypatch):
    """Inverse: a healthy fallback (flag False) leaves health ok."""
    from unittest.mock import MagicMock

    from ormah import main as _main
    from ormah.api import routes_admin

    monkeypatch.setattr(_main, "_fallback_degraded", False)

    request = MagicMock()
    request.app.state = MagicMock(spec=[])

    result = routes_admin.health(request)

    assert result["status"] == "ok"
```

- [ ] **Step 6: Run the affected tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py tests/test_api/test_routes.py tests/test_api/test_admin_embedding_backfill_task.py -v`
Expected: all PASS (fallback: retry/degraded/singleton/stop; health: degraded + ok).

- [ ] **Step 7: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -m 'not integration' -q`
Expected: pass count up by the new tests; the only failures are the known pre-existing/flaky ones — `test_config.py::test_llm_provider_defaults_to_none`, `TestRemoveFastembedCache` ×3, and the timing-flaky `test_background/test_hippocampus.py::test_new_file_triggers_ingestion`. No new failures attributable to this change.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/main.py src/ormah/api/routes_admin.py tests/test_main_backfill_fallback.py tests/test_api/test_routes.py
git commit -m "fix(main): lifecycle-aware backfill fallback with degraded health signal (C2/CH1/CH2)"
```

---

### Task 3: I2 — UI consumes the degraded contract

**Files:**
- Modify: `ui/src/api.ts` (`runAllTasks`, L109-111)
- Modify: `ui/src/components/AdminPanel.tsx` (`handleRunAll`, L111-124)

**Note (no UI test harness):** the `ui/` project has no test runner (no vitest, no `test` script, no `.test`/`.spec` files). Standing one up is out of scope for this PR (André's decision). Verification is `tsc && vite build` (typecheck + build) plus the explicit logic review below. A vitest harness can be a follow-up.

- [ ] **Step 1: Make `runAllTasks` tolerate the 503 degraded response**

In `ui/src/api.ts`, replace `runAllTasks` (L109-111):

**Before:**
```typescript
export function runAllTasks(): Promise<{ status: string; results: Record<string, string> }> {
  return post("/admin/tasks/run-all");
}
```

**After:**
```typescript
export async function runAllTasks(): Promise<{ status: string; results: Record<string, string> }> {
  // A 503 with a degraded body is an expected partial-failure signal (C1/I1),
  // not a transport error — read the body instead of throwing on it.
  const res = await fetch(`${BASE}/admin/tasks/run-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok && res.status !== 503) {
    throw new Error(`POST /admin/tasks/run-all: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Branch on `result.status` in `handleRunAll`**

In `ui/src/components/AdminPanel.tsx`, replace `handleRunAll` (L111-124):

**Before:**
```typescript
  const handleRunAll = useCallback(async () => {
    setRunningAll(true);
    setLastResult(null);
    try {
      await runAllTasks();
      setLastResult({ task: "__all__", ok: true });
      onToast("Sleep cycle complete", "success");
    } catch {
      setLastResult({ task: "__all__", ok: false });
      onToast("Sleep cycle failed", "error");
    } finally {
      setRunningAll(false);
    }
  }, [onToast]);
```

**After:**
```typescript
  const handleRunAll = useCallback(async () => {
    setRunningAll(true);
    setLastResult(null);
    try {
      const result = await runAllTasks();
      if (result.status === "completed") {
        setLastResult({ task: "__all__", ok: true });
        onToast("Sleep cycle complete", "success");
      } else {
        const failed = Object.entries(result.results)
          .filter(([, v]) => v.startsWith("error:"))
          .map(([task]) => task);
        setLastResult({ task: "__all__", ok: false });
        onToast(`Sleep cycle degraded — failed: ${failed.join(", ")}`, "error");
      }
    } catch {
      setLastResult({ task: "__all__", ok: false });
      onToast("Sleep cycle failed", "error");
    } finally {
      setRunningAll(false);
    }
  }, [onToast]);
```

- [ ] **Step 3: Typecheck + build**

Run: `cd ui && npm run build`
Expected: `tsc` passes with no type errors and `vite build` completes. (`onToast`'s severity arg already accepts `"error"`, used elsewhere in this file.)

- [ ] **Step 4: Logic review (manual, since no UI test harness)**

Confirm by reading the diff:
- completed → success toast "Sleep cycle complete"; degraded → error toast naming failed tasks; thrown (non-503 / network) → error toast "Sleep cycle failed".
- `failed` is derived from the same `error:` prefix the backend writes (`results[task_id] = f"error: {exc}"`), matching C1's `has_errors` predicate.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api.ts ui/src/components/AdminPanel.tsx
git commit -m "fix(ui): AdminPanel surfaces degraded sleep-cycle instead of false success (I2)"
```

---

## Post-implementation

- [ ] Re-run `/council-pr` on the branch for a fresh code review of the implemented diff.
- [ ] Known unrelated red tests (do not block this PR): `test_config.py::test_llm_provider_defaults_to_none`, `TestRemoveFastembedCache` ×3 (pre-existing), and `test_background/test_hippocampus.py::test_new_file_triggers_ingestion` (timing-flaky watcher test; passes intermittently; zero diff vs `main`).

# PR B — Admin triggers must not start a job that is already running

Branch: `fix/admin-task-run-concurrency` off **`upstream/main`** (independent of PR A).
Read [00-overview.md](00-overview.md) first. All line numbers refer to `upstream/main`.

**Why:** `POST /admin/tasks/{task_id}/run` (`routes_admin.py:250-269`) calls `runner(engine)` directly, bypassing the scheduler entirely. On 2026-07-13 a manual trigger started a second `auto_linker` while the scheduled one was ~11 minutes into its run; both read the same frozen watermark, enumerated the same candidates in the same order, and raced each other's edge writes. The route also returns `{"status": "completed"}` **unconditionally** — it reported success for the run that had just failed, which is how the outage stayed invisible. `POST /admin/tasks/run-all` (`routes_admin.py:272-293`) has the same hole.

> **Do NOT add `max_instances=1` to the scheduler.** Verified: it is already the APScheduler 3.11 default (`BackgroundScheduler()._job_defaults == {'misfire_grace_time': 1, 'coalesce': True, 'max_instances': 1}`). The scheduled path was never the problem.

---

### Task 4: `JobTracker` knows which jobs are in flight

The routes need to ask "is this job running right now?". `JobTracker` already wraps every scheduled job via `tracked()` and is already exposed as `app.state.job_tracker`, so it is the natural place — but it only records outcomes, never in-flight state.

**Files:**
- Modify: `src/ormah/background/job_tracker.py`
- Test: `tests/test_background/test_job_tracker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_job_tracker.py`:

```python
def test_tracker_reports_a_job_as_running_while_it_executes():
    from ormah.background.job_tracker import JobTracker, tracked

    tracker = JobTracker()
    seen = {}

    def job():
        seen["running_during"] = tracker.is_running("demo")

    assert tracker.is_running("demo") is False
    tracked(tracker, "demo", job)()
    assert seen["running_during"] is True
    assert tracker.is_running("demo") is False   # cleared after completion


def test_tracker_clears_the_running_flag_when_the_job_raises():
    from ormah.background.job_tracker import JobTracker, tracked

    tracker = JobTracker()

    def boom():
        raise RuntimeError("nope")

    tracked(tracker, "demo", boom)()
    assert tracker.is_running("demo") is False   # a stuck flag would wedge the job forever


def test_run_guard_refuses_a_second_concurrent_claim():
    from ormah.background.job_tracker import JobTracker

    tracker = JobTracker()
    inner = []

    with tracker.run_guard("demo") as acquired:
        assert acquired is True
        with tracker.run_guard("demo") as second:
            inner.append(second)
    assert inner == [False]

    with tracker.run_guard("demo") as third:   # released -> claimable again
        assert third is True


def test_tracked_skips_a_run_when_the_job_is_already_running():
    from ormah.background.job_tracker import JobTracker, tracked

    tracker = JobTracker()
    calls = []

    with tracker.run_guard("demo"):
        tracked(tracker, "demo", lambda: calls.append(1))()

    assert calls == []   # the wrapped function never ran
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah/.claude/worktrees/edges-117
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_job_tracker.py -v
```

Expected: FAIL with `AttributeError: 'JobTracker' object has no attribute 'is_running'`.

- [ ] **Step 3: Implement**

In `src/ormah/background/job_tracker.py`, add to the imports:

```python
import contextlib
```

Add the running-set to `JobTracker.__init__`:

```python
    def __init__(self) -> None:
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()
        self._running: set[str] = set()
```

Add two methods to `JobTracker`:

```python
    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._running

    @contextlib.contextmanager
    def run_guard(self, job_id: str):
        """Yield True if this caller claimed the job, False if it was already running.

        An edge-writing job (auto_linker, conflict_detector) must never run twice at
        once: both instances read the same watermark, enumerate the same candidates,
        and race each other's edge writes (#117). APScheduler's max_instances=1 covers
        the scheduled path; this covers the manual admin routes, which call the
        runners directly and never touch the scheduler.
        """
        with self._lock:
            acquired = job_id not in self._running
            if acquired:
                self._running.add(job_id)
        try:
            yield acquired
        finally:
            if acquired:
                with self._lock:
                    self._running.discard(job_id)
```

Make `tracked()` claim the job for the whole run — replace `_wrapper`:

```python
    def _wrapper():
        t0 = time.monotonic()
        with tracker.run_guard(job_id) as acquired:
            if not acquired:
                logger.warning("Job %s is already running; skipping this trigger", job_id)
                return
            try:
                fn(*args)
                duration_ms = (time.monotonic() - t0) * 1000
                tracker.record_success(job_id, duration_ms)
            except Exception as e:
                duration_ms = (time.monotonic() - t0) * 1000
                tracker.record_failure(job_id, str(e), duration_ms)
                logger.warning("Job %s failed after %.0fms: %s", job_id, duration_ms, e)

    return _wrapper
```

- [ ] **Step 4: Run them to verify they pass**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_job_tracker.py -v
```

Expected: PASS (4 new + all pre-existing).

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/job_tracker.py tests/test_background/test_job_tracker.py
git commit -m "feat(job-tracker): track in-flight jobs and expose run_guard

Two concurrent runs of an edge-writing job read the same watermark, enumerate the
same candidates and race each other's writes (#117). JobTracker now knows which
jobs are in flight; run_guard() lets a caller claim a job or learn it is already
running. tracked() claims for the duration and always releases, even on failure."
```

---

### Task 4b: the runners must stop swallowing their own failures

**Without this, Task 5 does not work.** `run_auto_linker` and `run_conflict_detection` on `upstream/main` end with:

```python
    except Exception as e:
        logger.warning("Auto-linker failed: %s", e)
```

They catch everything, log, and return `None`. So a route that inspects the return value or catches exceptions sees **success** for a run that just died — which is exactly what happened during the incident: `POST /admin/tasks/auto_linker/run` answered `{"status": "completed"}` while the run had failed with the UNIQUE collision. Fixing only the route (Task 5) would leave the lie intact (Codex R2, critical #3).

The Beta already returns `{"error": str(e)}` here; this brings `upstream/main` in line.

**Files:**
- Modify: `src/ormah/background/auto_linker.py` (top-level `except` of `run_auto_linker`), `src/ormah/background/conflict_detector.py` (top-level `except` of `run_conflict_detection`)
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_auto_linker_reports_a_fatal_error_instead_of_returning_none(engine, monkeypatch):
    """A run that dies must say so in its return value — the job tracker and the admin
    route both read it. Returning None made a dead run look like a clean one (#117)."""
    from ormah.background import auto_linker as al

    engine.settings.llm_enabled = True

    def boom(*_a, **_kw):
        raise RuntimeError("vector store exploded")

    monkeypatch.setattr(al, "_get_watermark", boom)

    result = al.run_auto_linker(engine)

    assert isinstance(result, dict)
    assert "vector store exploded" in result["error"]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py::test_run_auto_linker_reports_a_fatal_error_instead_of_returning_none -v
```

Expected: FAIL — `assert isinstance(None, dict)`.

- [ ] **Step 3: Implement**

In `src/ormah/background/auto_linker.py`:

```python
    except Exception as e:
        logger.warning("Auto-linker failed: %s", e)
        return {"error": str(e)}
```

In `src/ormah/background/conflict_detector.py`:

```python
    except Exception as e:
        logger.warning("Conflict detection failed: %s", e)
        return {"error": str(e)}
```

`tracked()` already treats a returned dict containing `error` as a failure (`record_failure`), so this also makes `/admin/health` reflect a dead run instead of a stale `ok`.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_auto_linker.py tests/test_background/test_conflict_detector.py \
  tests/test_background/test_job_tracker.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py src/ormah/background/conflict_detector.py \
        tests/test_background/test_auto_linker.py
git commit -m "fix(background): a dead run must report an error, not None

run_auto_linker and run_conflict_detection caught every exception, logged it and
returned None — so the job tracker recorded a success and the admin route replied
'completed' for a run that had just died. That is how the #117 outage stayed
invisible for a day. They now return {'error': ...}, which tracked() already
understands as a failure."
```

---

### Task 5: the admin routes refuse a duplicate run, and `run_task` stops lying

**Files:**
- Modify: `src/ormah/api/routes_admin.py:250-293` (`run_task` and `run_all_tasks`)
- Create: `tests/test_api/test_routes_admin_run_task.py`

Note: the existing API `client` fixture (`tests/test_api/test_routes.py:19-36`) does **not** set `app.state.job_tracker`, so the routes currently see `tracker is None`. The new test file needs its own fixture that wires one up.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_routes_admin_run_task.py`:

```python
"""The manual task-trigger routes must not start a job that is already running,
and must report what actually happened (#117)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api.routes_admin import router as admin_router
from ormah.background.job_tracker import JobTracker
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine


@pytest.fixture
def app_and_client(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir, backup_dir=tmp_memory_dir.parent / "backups")
    engine = MemoryEngine(settings)
    engine.startup()

    app = FastAPI()
    app.include_router(admin_router)
    app.state.engine = engine
    app.state.job_tracker = JobTracker()

    with TestClient(app) as c:
        yield app, c

    engine.shutdown()


def test_run_task_rejects_a_job_that_is_already_running(app_and_client):
    """A manual trigger during the scheduled run used to start a second concurrent
    run over the same watermark (#117). It must 409 instead."""
    app, client = app_and_client

    with app.state.job_tracker.run_guard("auto_linker") as acquired:
        assert acquired is True
        resp = client.post("/admin/tasks/auto_linker/run")

    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"].lower()


def test_run_task_reports_a_failure_instead_of_completed(app_and_client, monkeypatch):
    """The route returned {'status': 'completed'} unconditionally — a run that blew
    up was reported to the caller as a success."""
    _app, client = app_and_client
    import ormah.background.auto_linker as al

    def boom(_engine):
        raise RuntimeError("watermark exploded")

    monkeypatch.setattr(al, "run_auto_linker", boom)
    resp = client.post("/admin/tasks/auto_linker/run")

    assert resp.status_code == 500
    assert "watermark exploded" in resp.json()["detail"]


def test_run_task_returns_the_stats_on_success(app_and_client, monkeypatch):
    _app, client = app_and_client
    import ormah.background.auto_linker as al

    monkeypatch.setattr(al, "run_auto_linker", lambda _e: None)
    resp = client.post("/admin/tasks/auto_linker/run")

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_run_all_skips_a_task_that_is_already_running(app_and_client, monkeypatch):
    """run-all calls the runners directly too — same hole."""
    app, client = app_and_client
    import ormah.background.auto_linker as al

    calls = []
    monkeypatch.setattr(al, "run_auto_linker", lambda _e: calls.append(1))

    with app.state.job_tracker.run_guard("auto_linker"):
        resp = client.post("/admin/tasks/run-all")

    assert calls == []                                  # never started a second run
    assert resp.json()["results"]["auto_linker"] == "skipped: already running"
```

> `run_auto_linker` returns `None` on `upstream/main`, hence the success test asserts only on `status`. A job that signals failure by returning `{"error": ...}` is a Beta-only shape today; Task 8 adds that assertion when the change lands there.

- [ ] **Step 2: Run them to verify they fail**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_api/test_routes_admin_run_task.py -v
```

Expected: the 409 test FAILS with `200 != 409` (a second run starts happily); the failure test FAILS because the exception escapes as an unhandled 500 with a different body, or the route answers `200 {"status": "completed"}`; the run-all test FAILS because the runner is called.

- [ ] **Step 3: Implement**

In `src/ormah/api/routes_admin.py`, add logging near the top (the module has no logger today):

```python
import logging

logger = logging.getLogger(__name__)
```

Replace `run_task`:

```python
@router.post("/tasks/{task_id}/run")
def run_task(task_id: str, request: Request):
    """Manually trigger a background task by ID."""
    engine = request.app.state.engine

    # index_updater is a method on engine.builder, not a standalone function
    if task_id == "index_updater":
        added, updated = engine.builder.incremental_update()
        return {"status": "completed", "task": task_id, "added": added, "updated": updated}

    if task_id not in _TASK_RUNNERS:
        raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}. Available: {list(_TASK_RUNNERS.keys()) + ['index_updater']}")

    import importlib
    module_path, func_name = _TASK_RUNNERS[task_id]
    module = importlib.import_module(module_path)
    runner = getattr(module, func_name)

    tracker = getattr(request.app.state, "job_tracker", None)
    if tracker is None:
        return _run_and_report(task_id, runner, engine)

    # This route bypasses the scheduler, so APScheduler's max_instances=1 does not
    # apply to it. Without this guard a manual trigger during a scheduled run starts a
    # second concurrent run over the same watermark, and the two race each other's
    # edge writes (#117).
    with tracker.run_guard(task_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail=f"Task {task_id} is already running")
        return _run_and_report(task_id, runner, engine)


def _run_and_report(task_id: str, runner, engine) -> dict:
    """Run a task and report what actually happened.

    The route used to return {"status": "completed"} unconditionally: a run that
    raised, or that returned {"error": ...}, was reported to the caller as a success.
    """
    try:
        result = runner(engine)
    except Exception as e:
        logger.warning("Manual run of %s failed: %s", task_id, e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    stats = result if isinstance(result, dict) else None
    if stats is not None and "error" in stats:
        raise HTTPException(status_code=500, detail=str(stats["error"]))
    payload = {"status": "completed", "task": task_id}
    if stats is not None:
        payload["stats"] = stats
    return payload
```

Replace the loop in `run_all_tasks`. **Claim each task with `run_guard`, do not merely check `is_running`** — a check-then-act leaves the race open, and PR A's idempotent edge write does not cover the whole-file markdown load/modify/save, which can still lose updates (Codex R2, critical #2):

```python
    engine = request.app.state.engine
    tracker = getattr(request.app.state, "job_tracker", None)
    results: dict[str, str] = {}

    for task_id in _SLEEP_CYCLE_ORDER:
        with _guard(tracker, task_id) as acquired:
            if not acquired:
                # Same hole as run_task: this bypasses the scheduler, so a job already
                # in flight would get a second concurrent run over the same watermark,
                # racing its edge and markdown writes (#117).
                results[task_id] = "skipped: already running"
                continue
            try:
                if task_id == "index_updater":
                    engine.builder.incremental_update()
                elif task_id in _TASK_RUNNERS:
                    module_path, func_name = _TASK_RUNNERS[task_id]
                    module = importlib.import_module(module_path)
                    runner = getattr(module, func_name)
                    result = runner(engine)
                    if isinstance(result, dict) and "error" in result:
                        results[task_id] = f"error: {result['error']}"
                        continue
                results[task_id] = "ok"
            except Exception as exc:
                results[task_id] = f"error: {exc}"

    has_errors = any(v.startswith("error:") for v in results.values())
    if has_errors:
        return JSONResponse(status_code=503, content={"status": "degraded", "results": results})
    return {"status": "completed", "results": results}
```

Add the small helper next to `_run_and_report` — it keeps a missing tracker from silently disabling the guard on one path but not another:

```python
@contextlib.contextmanager
def _guard(tracker, task_id: str):
    """Claim task_id for the duration of the block, or yield False if it is running.

    A missing tracker (scheduler never started) means no scheduled job can be running
    either, so there is nothing to collide with — but two concurrent HTTP requests
    still could, so the app always builds a JobTracker (main.py), tracker=None is only
    reachable in tests.
    """
    if tracker is None:
        yield True
        return
    with tracker.run_guard(task_id) as acquired:
        yield acquired
```

Import `contextlib` and `JSONResponse` at the top of the module if they are not already there.

Also **guard `index_updater` in `run_task`**: it currently returns before the tracker is consulted, so a manual index run can still overlap the scheduled one. Move the guard above the `index_updater` branch:

```python
    tracker = getattr(request.app.state, "job_tracker", None)

    if task_id == "index_updater":
        with _guard(tracker, task_id) as acquired:
            if not acquired:
                raise HTTPException(status_code=409, detail=f"Task {task_id} is already running")
            added, updated = engine.builder.incremental_update()
            return {"status": "completed", "task": task_id, "added": added, "updated": updated}
```

- [ ] **Step 4: Run the API suite**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_api/ -v
```

Expected: PASS. `run_task`'s success response gains a `stats` key only when the runner returns a dict, so existing assertions on `{"status": "completed", "task": ...}` still hold.

- [ ] **Step 5: Full suite + lint, then commit and open the PR**

```bash
PYTHONPATH=$PWD/src /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/ -q --ignore=tests/test_cloud 2>&1 | tail -3
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ruff check src/ tests/
```

Expected: the same ~12 environmental failures as the baseline, no new ones.

```bash
git add src/ormah/api/routes_admin.py tests/test_api/test_routes_admin_run_task.py
git commit -m "fix(api): manual task triggers refuse a duplicate run and report the real outcome

POST /admin/tasks/{id}/run and /admin/tasks/run-all call the runners directly,
bypassing the scheduler — so APScheduler's max_instances=1 never applied to them.
A manual trigger during a scheduled run started a second concurrent execution over
the same watermark; both enumerated the same candidates and raced each other's
edge writes (#117). They now refuse (409 / skipped).

run_task also returned {'status': 'completed'} unconditionally: a run that raised,
or that returned {'error': ...}, was reported as a success."

git push -u fork fix/admin-task-run-concurrency
gh pr create --repo r-spade/ormah --base main \
  --title "fix(api): manual task triggers start a second concurrent run and always report success" \
  --body "The admin trigger routes call the job runners directly, bypassing the scheduler entirely — so APScheduler's \`max_instances=1\` (which is the default, and does protect the scheduled path) never applied to them.

On 2026-07-13 a manual \`POST /admin/tasks/auto_linker/run\` started while the scheduled \`auto_linker\` was ~11 minutes into its run. Both read the same (frozen) watermark, so both enumerated the same candidate pairs in the same order and raced each other's edge writes. The scheduled run died with \`UNIQUE constraint failed: edges...\` (#117).

Separately, \`run_task\` returned \`{\"status\": \"completed\"}\` unconditionally — the failing run above was reported to the caller as a success, which is how the outage stayed invisible.

**Changes**
- \`JobTracker\` tracks in-flight jobs (\`is_running\`, \`run_guard\`); \`tracked()\` claims for the duration of a run and always releases.
- \`POST /admin/tasks/{id}/run\` → 409 when the job is already running; propagates a raised exception or an \`{'error': ...}\` result as a 500.
- \`POST /admin/tasks/run-all\` → skips a task already in flight instead of starting a second copy.

Does **not** touch \`scheduler.py\`: \`max_instances=1\` is already the APScheduler default and the scheduled path was never the problem.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

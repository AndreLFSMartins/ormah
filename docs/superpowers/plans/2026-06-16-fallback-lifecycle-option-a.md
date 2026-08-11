# Fallback Daemon Lifecycle — Option A (simplified) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the council-pr round-2 lifecycle cluster (CRA use-after-close, CRB non-atomic singleton, CRC run-all→health gap, IA orphan-blocks-new-fallback) on `fix/embedding-delta-backfill` by making the embedding backfill *cancellable*, locking the singleton, feeding run-all failures into the JobTracker, and reverting the band-aid CR1.

**Architecture:** The fallback daemon stays (council I1 requires scheduler-independent recovery), but `backfill_embeddings` becomes cooperatively cancellable via a `stop_event` checked between encodes and — critically — **before every DB write**. A bounded `join` then guarantees the thread has released the DB before `engine.shutdown()` closes it. A module `threading.Lock` makes the singleton start atomic. `run_all_tasks` records per-task outcomes into the JobTracker so `/admin/health` reflects manual runs. CR1 (preserve-handle-on-join-timeout) is reverted: with cancellation the join succeeds, so the handle is always cleared.

**Tech Stack:** Python 3.11, threading, pytest (`asyncio_mode=auto`), FastAPI.

**Branch:** `fix/embedding-delta-backfill` (verify before every commit). Use `.venv/bin/python -m pytest`.

**Reverts:** CR1 = commit `e2fd81c` (`_stop_backfill_fallback` keeps the handle when the thread survives the join).

---

### Task A: Make `backfill_embeddings` cancellable (closes CRA + IA)

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`_embed_node_rows` ~1006-1061, `backfill_embeddings` ~1085-1155)
- Modify: `src/ormah/background/embedding_backfill.py` (`run_embedding_backfill`)
- Test: locate the existing engine/backfill test file (`grep -rl "backfill_embeddings" tests/`); add cases there.

- [ ] **Step 1: Write failing tests**

```python
# in the existing backfill test module — fixtures create an engine with embeddable
# nodes that are missing vectors (so a delta backfill has work to do).
import threading

def test_backfill_stops_before_db_writes_when_event_set(engine_with_missing_vectors):
    eng = engine_with_missing_vectors
    stop = threading.Event()
    stop.set()  # already cancelled
    result = eng.backfill_embeddings(stop_event=stop)
    # Nothing persisted; the gap is reported honestly.
    assert result["embedded"] == 0
    assert result["missing"] > 0

def test_backfill_completes_when_event_not_set(engine_with_missing_vectors):
    eng = engine_with_missing_vectors
    result = eng.backfill_embeddings(stop_event=threading.Event())  # never set
    assert result["missing"] == 0

def test_schema_version_not_advanced_when_interrupted(engine_schema_bump):
    # engine_schema_bump: stored embedding_schema_version < current -> mode "schema"
    eng = engine_schema_bump
    stop = threading.Event(); stop.set()
    before = eng.db.conn.execute(
        "SELECT value FROM meta WHERE key='embedding_schema_version'").fetchone()
    eng.backfill_embeddings(stop_event=stop)
    after = eng.db.conn.execute(
        "SELECT value FROM meta WHERE key='embedding_schema_version'").fetchone()
    assert (before["value"] if before else None) == (after["value"] if after else None)

def test_run_embedding_backfill_accepts_stop_event(engine_with_missing_vectors):
    from ormah.background.embedding_backfill import run_embedding_backfill
    stop = threading.Event(); stop.set()
    # Incomplete (interrupted) -> raises, matching the existing missing>0 contract.
    import pytest
    with pytest.raises(RuntimeError):
        run_embedding_backfill(engine_with_missing_vectors, stop_event=stop)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest <test_file> -k "stop or interrupted or stop_event" -v`
Expected: FAIL — `backfill_embeddings() got an unexpected keyword argument 'stop_event'`.

- [ ] **Step 3: Implement cancellation in `_embed_node_rows`**

Change the signature and add a check before each encode and **before every DB write**. Track only ids actually upserted:

```python
def _embed_node_rows(self, nodes, stop_event=None) -> tuple[list[str], list[str]]:
    ...
    all_items: list[tuple[str, Any]] = []
    failed_ids: list[str] = []
    for idx, n in enumerate(nodes):
        if stop_event is not None and stop_event.is_set():
            break  # cooperative cancel — stop accumulating work
        text = _embedding_text(n["title"], n["content"], max_chars)
        if text:
            try:
                embedding = encoder.encode(text)
                all_items.append((n["id"], embedding))
            except Exception as e:
                logger.warning("Failed to embed node %s: %s", n["id"][:8], e)
                failed_ids.append(n["id"])
        done = idx + 1
        if done % log_every == 0 or done == total:
            logger.info("Embedding memories: %d/%d", done, total)

    # Upsert in small chunks with WAL checkpoint after each.
    chunk_size = 100
    upserted_ids: list[str] = []
    for i in range(0, len(all_items), chunk_size):
        # Check BEFORE each DB write: this is what closes the use-after-close
        # window (CRA) — once stop is set we never start a new DB op.
        if stop_event is not None and stop_event.is_set():
            break
        chunk = all_items[i : i + chunk_size]
        vec_store.upsert_batch(chunk)
        self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        upserted_ids.extend(item[0] for item in chunk)

    embedded_ids = upserted_ids
    vec_count = self.db.conn.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
    logger.info(
        "Embedded %d/%d nodes (vec_count=%d, failed=%d)",
        len(embedded_ids), total, vec_count, len(failed_ids),
    )
    if vec_count < len(embedded_ids):
        logger.warning(
            "Vec table has fewer entries (%d) than embedded (%d) — "
            "possible sqlite-vec persistence issue",
            vec_count, len(embedded_ids),
        )
    return embedded_ids, failed_ids
```

- [ ] **Step 4: Thread `stop_event` through `backfill_embeddings` and guard the schema version advance**

```python
def backfill_embeddings(self, stop_event=None) -> dict:
    ...
    embedded_ids, failed_ids = self._embed_node_rows(rows, stop_event=stop_event)

    interrupted = stop_event is not None and stop_event.is_set()

    if mode == "schema" and failed_ids:
        with self.db.transaction() as conn:
            for nid in failed_ids:
                conn.execute("DELETE FROM node_vectors WHERE id = ?", (nid,))

    # Only advance the version on a COMPLETE schema pass. An interrupted pass
    # must be re-run as schema next time — advancing here would make a partial
    # reprocess look complete and hide un-reprocessed nodes from delta runs.
    if mode == "schema" and not interrupted:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES "
                "('embedding_schema_version', ?)",
                (str(_EMBEDDING_SCHEMA_VERSION),),
            )

    missing = self._missing_embeddable_count()
    ...  # unchanged return dict
```

- [ ] **Step 5: Thread `stop_event` through `run_embedding_backfill`**

```python
def run_embedding_backfill(engine, stop_event=None) -> None:
    ...
    result = engine.backfill_embeddings(stop_event=stop_event)
    ...  # unchanged: missing>0 still raises RuntimeError
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest <test_file> -v`
Expected: PASS. Existing backfill tests still green (default `stop_event=None` preserves behaviour).

- [ ] **Step 7: Commit** (`git add` only the two src files + test file)

```bash
git commit -m "fix(engine): make embedding backfill cooperatively cancellable (CRA/IA)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task B: Atomic singleton + thread the stop_event + revert CR1 (closes CRB, completes CRA/IA)

**Files:**
- Modify: `src/ormah/main.py` (`_start_backfill_fallback` ~64-106, `_stop_backfill_fallback` ~109-128, module globals ~55-61)
- Test: `tests/test_main_backfill_fallback.py` (has an autouse `_reset_fallback_state` fixture; patch `_BACKFILL_FALLBACK_BASE_BACKOFF` to a tiny value)

- [ ] **Step 1: Write failing tests**

```python
import threading
from ormah import main

def test_concurrent_start_creates_single_thread(monkeypatch):
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    started = []
    engine = _FakeEngine()  # backfill_embeddings blocks on an event so the thread stays alive
    barrier = threading.Barrier(8)
    def racer():
        barrier.wait()
        main._start_backfill_fallback(engine)
    threads = [threading.Thread(target=racer) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    alive = [t for t in threading.enumerate() if t.name == "embedding-backfill-fallback" and t.is_alive()]
    assert len(alive) == 1
    main._stop_backfill_fallback()

def test_stop_clears_handle(monkeypatch):
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    main._start_backfill_fallback(_QuickEngine())  # completes immediately
    main._stop_backfill_fallback()
    assert main._fallback_thread is None  # CR1 reverted: handle always cleared

def test_stop_cancels_long_backfill_within_join(monkeypatch):
    monkeypatch.setattr(main, "_BACKFILL_FALLBACK_BASE_BACKOFF", 0.001)
    # _CancellableEngine.backfill_embeddings loops checking stop_event; exits when set
    eng = _CancellableEngine()
    main._start_backfill_fallback(eng)
    eng.entered.wait(timeout=2)
    main._stop_backfill_fallback()
    assert main._fallback_thread is None
    assert eng.saw_stop is True  # stop_event reached the engine
```

(Define `_FakeEngine`/`_QuickEngine`/`_CancellableEngine` as small test doubles whose `backfill_embeddings(self, stop_event=None)` respect the event. `run_embedding_backfill` will call `engine.backfill_embeddings(stop_event=...)`.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -k "concurrent or clears_handle or cancels_long" -v`
Expected: FAIL (no lock yet / handle preserved by CR1 / stop_event not forwarded).

- [ ] **Step 3: Add the module lock and forward the stop_event**

```python
# with the other module globals (~line 59)
_fallback_lock = threading.Lock()
```

In `_start_backfill_fallback`, wrap the check-and-set under the lock and forward the event:

```python
def _start_backfill_fallback(engine) -> None:
    global _fallback_thread, _fallback_stop_event, _fallback_degraded
    with _fallback_lock:  # CRB: make the singleton check-and-set atomic
        if _fallback_thread is not None and _fallback_thread.is_alive():
            return
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
                    run_embedding_backfill(engine, stop_event=stop_event)  # forward
                    _fallback_degraded = False
                    return
                except Exception as e:
                    _fallback_degraded = True
                    logger.warning(
                        "Embedding backfill fallback attempt %d failed: %s", attempt, e,
                    )
                    if stop_event.wait(delay):
                        return
                    delay = min(delay * 2, _BACKFILL_FALLBACK_MAX_BACKOFF)

        thread = threading.Thread(
            target=_run, name="embedding-backfill-fallback", daemon=True
        )
        _fallback_thread = thread
        thread.start()
```

- [ ] **Step 4: Revert CR1 in `_stop_backfill_fallback`**

```python
def _stop_backfill_fallback() -> None:
    """Signal the fallback thread to stop and join it. Idempotent. With the
    backfill now cancellable, the join succeeds quickly, so the handle is always
    cleared — the engine can then be shut down safely (no use-after-close)."""
    global _fallback_thread, _fallback_stop_event
    with _fallback_lock:
        if _fallback_stop_event is not None:
            _fallback_stop_event.set()
        thread = _fallback_thread
    if thread is not None:
        thread.join(timeout=_FALLBACK_JOIN_TIMEOUT)
        if thread.is_alive():
            logger.warning(
                "Embedding backfill fallback did not stop within %.1fs", _FALLBACK_JOIN_TIMEOUT,
            )
    with _fallback_lock:
        _fallback_thread = None
        _fallback_stop_event = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_main_backfill_fallback.py -v`
Expected: PASS. Delete/invert the obsolete CR1 test `test_stop_preserves_handle_when_thread_survives_join` (it asserted the reverted behaviour).

- [ ] **Step 6: Commit** (`git add` main.py + test file)

```bash
git commit -m "fix(main): atomic fallback singleton + forward stop_event; revert CR1 (CRB)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task C: run-all feeds the JobTracker (closes CRC)

**Files:**
- Modify: `src/ormah/api/routes_admin.py` (`run_all_tasks` ~289-318)
- Test: `tests/test_api/test_routes.py`

- [ ] **Step 1: Write failing test**

```python
def test_run_all_records_failure_in_tracker_so_health_degrades():
    """CRC: a failed task in run-all must persist to the JobTracker so a later
    GET /admin/health reports degraded (not a stale ok)."""
    from unittest.mock import MagicMock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ormah.api.routes_admin import router as admin_router
    from ormah.background.job_tracker import JobTracker
    # Build an app whose engine makes embedding_backfill raise; attach a real tracker.
    app = FastAPI(); app.include_router(admin_router)
    app.state.engine = _EngineWhereBackfillRaises()
    app.state.job_tracker = JobTracker()
    app.state.maintenance_manager = None
    with TestClient(app) as c:
        r = c.post("/admin/tasks/run-all")
        assert r.status_code == 503
        h = c.get("/admin/health")
        assert h.json()["status"] == "degraded"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api/test_routes.py -k run_all_records_failure -v`
Expected: FAIL — health returns `ok` (failure not persisted).

- [ ] **Step 3: Record per-task outcomes in `run_all_tasks`**

```python
@router.post("/tasks/run-all")
def run_all_tasks(request: Request):
    """Run all background tasks sequentially in sleep-cycle order."""
    import importlib
    import time as _time

    engine = request.app.state.engine
    tracker = getattr(request.app.state, "job_tracker", None)
    results: dict[str, str] = {}

    for task_id in _SLEEP_CYCLE_ORDER:
        t0 = _time.monotonic()
        try:
            if task_id == "index_updater":
                engine.builder.incremental_update()
            elif task_id in _TASK_RUNNERS:
                module_path, func_name = _TASK_RUNNERS[task_id]
                module = importlib.import_module(module_path)
                runner = getattr(module, func_name)
                runner(engine)
            results[task_id] = "ok"
            if tracker is not None:
                tracker.record_success(task_id, (_time.monotonic() - t0) * 1000)
        except Exception as exc:
            results[task_id] = f"error: {exc}"
            # CRC: persist the failure so /admin/health reflects this manual run
            # instead of reverting to a stale ok.
            if tracker is not None:
                tracker.record_failure(task_id, str(exc), (_time.monotonic() - t0) * 1000)

    has_errors = any(v.startswith("error:") for v in results.values())
    if has_errors:
        return JSONResponse(status_code=503, content={"status": "degraded", "results": results})
    return {"status": "completed", "results": results}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api/test_routes.py -v`
Expected: PASS. The existing `test_health_degraded_when_scheduler_job_embedding_backfill_failing` / `_recovered` still green.

- [ ] **Step 5: Commit** (`git add` routes_admin.py + test file)

```bash
git commit -m "fix(api): run-all records task outcomes in JobTracker so health reflects manual runs (CRC)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Verification (after all tasks)

- [ ] `.venv/bin/python -m pytest tests/ -v` — only the 5 known-unrelated reds remain (`test_llm_provider_defaults_to_none`, `TestRemoveFastembedCache` ×3, flaky `test_new_file_triggers_ingestion`). No new failures.
- [ ] `make lint` clean on changed files.
- [ ] `graphify update .`
- [ ] Re-run `/council-pr --skip-preflight-tests` (André-triggered) to confirm CRA/CRB/CRC/IA resolved.

## Self-review notes
- CRA closed by: cancel check **before every DB write** + bounded join in a reverted (always-clears) `_stop`. When `_stop` returns, the thread has released the DB → `engine.shutdown()` is safe.
- CRB closed by: `_fallback_lock` around check-and-set in `_start` (and handle mutation in `_stop`).
- CRC closed by: `record_success`/`record_failure` per task in run-all.
- IA closed by: cancellation → join succeeds → handle cleared → a restarted lifespan starts a fresh fallback for the new engine.
- CR1 reverted: handle is always cleared; the preserve-on-timeout branch (and its test) are removed.
- Backward compat: `stop_event=None` default keeps the scheduler job and `/admin/tasks/{id}/run` callers unchanged.

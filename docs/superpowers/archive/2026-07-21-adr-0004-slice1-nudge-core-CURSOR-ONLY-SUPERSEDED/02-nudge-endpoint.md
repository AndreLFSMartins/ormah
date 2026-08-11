# Task 2: `POST /ingest/nudge` — 202, feeds the worker

**Files:**
- Modify: `src/ormah/api/routes_ingest.py` (add model + route; `/conversation` and `/file` stay — other clients use them)
- Modify: `src/ormah/background/session_watcher.py` (`SessionHandler.nudge()` public method, next to `_schedule_ingest` L1084)
- Test: create `tests/test_api/test_routes_ingest.py`

**Interfaces:**
- Consumes: `app.state.session_watches` and `SessionWatch`/`SessionHandler` from Task 1.
- Produces:
  - `SessionHandler.nudge(path: Path) -> None` — thread-safe enqueue with **boundary
    semantics**, all of it DURABLE. It merges `{"boundary_target": <file size at nudge
    time>}` into the transcript's state entry — creating the entry with `end_offset: 0`
    only when none exists, and NEVER touching an existing cursor — then schedules the
    ingest with **zero debounce**.
    ⚠️ **A byte offset, not a boolean** (council R10). A boolean cannot say WHICH boundary
    was accepted: PreCompact also nudges, so the transcript keeps growing while a capped
    drain runs, and a boolean would keep `force_flush` alive over turns appended *after*
    the accepted boundary — ingesting un-nudged growth even with automatic watching off.
    `boundary_target` is the EOF at acceptance: force-flush applies only while
    `end_offset < boundary_target`. A second nudge raises the target (`max(old, new)`),
    which is also what makes repeated nudges distinguishable and idempotent. The flag lives in the state file, so a crash, a timeout, or a
    provider failure cannot lose the boundary intent: every later attempt (retry, reconcile,
    startup drain) re-derives `force_flush` from it. It is cleared only when the cursor
    actually advances or the closed delta is verified empty.
  - **Zero debounce** (council R6): `session_watcher_debounce_seconds` defaults to 60s, so
    routing a nudge through the ordinary debounce would delay a SessionEnd delta by a
    minute for no reason — the session already ended. `nudge()` must schedule immediately
    (e.g. `_schedule_ingest(path, delay=0)` / `Timer(0, ...)`, matching whatever the real
    `_schedule_ingest` signature at L1084 allows), while keeping the in-flight guard so a
    concurrent Observer event still coalesces.
  - `_ingest_session(...)` reads `boundary_target` from the entry it already loads
    (`existing`, L765) and derives `force_flush = prev_offset < boundary_target`: it
    bypasses ONLY the idle-threshold and `min_turns` gates, and only up to that target. The safe-boundary rule (closed content only) and
    every cap/quarantine rule stay untouched: a session that ENDED is final, but a still
    in-flight response must never be split from its prompt.
  - `POST /ingest/nudge` body `{"path": str, "session_id": str|null}` → `202 {"status": "accepted"}`;
    `404` file missing; `422` path outside every watch dir (path traversal guard — the
    endpoint must never let an arbitrary client path reach the engine).

- [ ] **Step 1: Write the failing tests**

Look at an existing `tests/test_api/` file first (e.g. `test_routes.py`) and reuse its
FastAPI `TestClient`/app fixture pattern. Then:

```python
from pathlib import Path
from unittest.mock import MagicMock


def _watch_stub(watch_dir: Path):
    w = MagicMock()
    w.watch_dir = watch_dir
    return w


def test_nudge_accepts_and_schedules(client, app, tmp_path):
    t = tmp_path / "proj" / "session.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user"}\n')
    watch = _watch_stub(tmp_path)
    app.state.session_watches = [watch]
    r = client.post("/ingest/nudge", json={"path": str(t)})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    watch.handler.nudge.assert_called_once_with(t.resolve())


def test_nudge_rejects_path_outside_watch_dirs(client, app, tmp_path):
    app.state.session_watches = [_watch_stub(tmp_path / "watched")]
    (tmp_path / "watched").mkdir()
    outside = tmp_path / "evil.jsonl"
    outside.write_text("x")
    r = client.post("/ingest/nudge", json={"path": str(outside)})
    assert r.status_code == 422
    assert not any(w.handler.nudge.called for w in app.state.session_watches)


def test_nudge_404_on_missing_file(client, app, tmp_path):
    app.state.session_watches = [_watch_stub(tmp_path)]
    r = client.post("/ingest/nudge", json={"path": str(tmp_path / "gone.jsonl")})
    assert r.status_code == 404


def test_nudge_persists_boundary_flag_before_202(client, app, engine, tmp_path):
    """council R5/R6: a 202 must be durably recoverable, and an existing cursor must
    never be reset. Uses a REAL SessionHandler so the state file is actually written."""
    from ormah.background.session_watcher import SessionHandler, _load_state, _save_state

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    jsonl.write_text('{"type":"user","message":{"role":"user","content":"hi there"}}\n')
    rel = str(jsonl.relative_to(watch_dir))
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 600.0, 72)   # match the real ctor
    watch = MagicMock(); watch.watch_dir = watch_dir; watch.handler = handler
    app.state.session_watches = [watch]

    # never-seen transcript -> entry created with a zero cursor and the boundary flag
    assert client.post("/ingest/nudge", json={"path": str(jsonl)}).status_code == 202
    entry = _load_state(watch_dir)[rel]
    assert entry["boundary_target"] == jsonl.stat().st_size
    assert entry["end_offset"] == 0

    # an EXISTING cursor must survive a later nudge untouched
    state = _load_state(watch_dir)
    state[rel] = {"end_offset": 4242, "hash": "deadbeef"}
    _save_state(watch_dir, state)
    assert client.post("/ingest/nudge", json={"path": str(jsonl)}).status_code == 202
    entry = _load_state(watch_dir)[rel]
    assert entry["end_offset"] == 4242
    assert entry["boundary_target"] == jsonl.stat().st_size


def test_nudge_schedules_without_debounce(engine, tmp_path):
    """council R6: a SessionEnd nudge must not wait out the 60s debounce."""
    from ormah.background.session_watcher import SessionHandler

    watch_dir = tmp_path / "projects"
    (watch_dir / "p").mkdir(parents=True)
    jsonl = watch_dir / "p" / "s.jsonl"
    jsonl.write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n')
    handler = SessionHandler(engine, watch_dir, 60.0, 5, 600.0, 72)
    with patch.object(handler, "_do_ingest") as do:
        handler.nudge(jsonl)
        time.sleep(1.0)
        assert do.called, "nudge must schedule immediately, not after the 60s debounce"


def test_boundary_flag_survives_a_transient_failure(engine, tmp_path):
    """council R6: the durable intent must outlive a failed attempt — a TRANSIENT
    result leaves boundary_target in place so the retry still bypasses the idle gate."""
    from ormah.background.session_watcher import (
        IngestResult, SessionHandler, _ingest_session, _load_state,
    )

    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)          # below min_turns and NOT idle
    rel = str(jsonl.relative_to(watch_dir))

    handler = SessionHandler(engine, watch_dir, 60.0, 5, 600.0, 72)
    handler.nudge(jsonl)
    assert _load_state(watch_dir)[rel]["boundary_target"] == jsonl.stat().st_size

    state = _load_state(watch_dir)
    with patch(_LLM_PATCH, return_value=None), \
         patch("ormah.background.session_watcher.ingest_provider_configured", return_value=True):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.TRANSIENT
    assert _load_state(watch_dir)[rel].get("boundary_target"), \
        "a failed attempt must not consume the boundary intent"

    state = _load_state(watch_dir)
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(
            engine, jsonl, state, watch_dir, min_turns=5) == IngestResult.OK
    entry = _load_state(watch_dir)[rel]
    assert entry["end_offset"] >= entry["boundary_target"]


def test_boundary_flag_cleared_on_idle_empty_delta(engine, tmp_path):
    """council R9: a nudge for a transcript with no closed delta left must clear the
    flag at the L829-835 return — otherwise the always-on reconcile re-queues that
    transcript on every tick forever."""
    # ingest a transcript to EOF, then nudge it again WITHOUT appending anything;
    # run _ingest_session and assert the result is NO_PROGRESS and the flag is gone.


def test_boundary_flag_kept_while_a_capped_drain_continues(engine, tmp_path):
    """council R9: a boundary delta bigger than flush_bytes drains in several capped
    batches. The flag must SURVIVE each capped batch, or the sub-cap tail falls back to
    the 600s idle gate. Use _make_jsonl(user_turns=12) with a small flush_bytes and
    assert the entry's end_offset is still BELOW boundary_target after the first
    (capped) OK, so force_flush survives into the next batch."""
```

And in `tests/test_background/test_session_watcher.py`:

```python
def test_force_flush_ingests_fresh_small_transcript(engine, tmp_path):
    """council R5 boundary semantics: a JUST-written transcript (not idle) with fewer
    than min_turns user turns is ingested when force_flush=True, and is NOT ingested
    without it — that gap is what makes a SessionEnd nudge useless otherwise."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)          # below min_turns, and NOT _mark_idle'd
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5) != IngestResult.OK
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5, force_flush=True) == IngestResult.OK
```

Also a unit test in `tests/test_background/test_session_watcher.py`:

```python
def test_handler_nudge_delegates_to_schedule(tmp_path):
    """nudge() routes through _schedule_ingest so debounce + in-flight guard apply."""
    # build a SessionHandler with the module's standard fixture; monkeypatch
    # handler._schedule_ingest with a MagicMock; call handler.nudge(p);
    # assert _schedule_ingest called once with (p) and the immediate/no-debounce arg
    # the implementation chooses (see Step 3).
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api/test_routes_ingest.py -v`
Expected: FAIL — 404/405 (route absent).

- [ ] **Step 3: Implement — `SessionHandler.nudge`**

Read `_schedule_ingest` (L1084-1099) first. Add below it:

```python
    def nudge(self, path: Path) -> None:
        """External enqueue with DURABLE session-boundary semantics (ADR-0004, council R5/R6).

        A nudge means the session ENDED, so the intent must outlive this process: it is
        written to the state file, not held in memory. Any later attempt — retry after a
        timeout, periodic reconcile, or the next startup drain — re-derives force_flush
        from it. Scheduling is immediate: the 60s debounce exists for files still being
        written, which is exactly what this is not.
        """
        rel = str(path.relative_to(self.watch_dir))
        # council R11: do NOT swallow this. The route answers 202 on a normal return, and
        # the hook then drops its outbox record AND retires its legacy cursor key. A
        # stat() failure means nothing was persisted, so it must surface as a failure.
        target = path.stat().st_size              # OSError propagates -> route returns 503
        # council R7: the read-modify-write MUST hold the SAME lock _commit_state uses
        # (`_state_lock`), not the handler's `_lock` — otherwise an extraction committing
        # cursor progress between our read and write is lost, or clobbers our target.
        with self._state_lock:
            entry = dict(self._state.get(rel) or {})
            entry.setdefault("end_offset", 0)     # never overwrite a real cursor
            entry["boundary_target"] = max(entry.get("boundary_target") or 0, target)
            _commit_state(self._state, rel, entry, None, self.watch_dir)  # lock already held
        self._schedule_ingest(path, delay=0)      # adapt to the real signature at L1084

Check `_commit_state`'s re-entrancy (L706-714) before writing this: if it always takes the
lock itself, do the read under that same lock via a small helper rather than passing None.
```

Read `_schedule_ingest` (L1084) and the handler's state/lock attribute names before
writing this — adapt the call, keep the semantics. If `_schedule_ingest` has no delay
parameter, add one defaulting to the configured debounce.

In `_ingest_session`, derive the intent from the entry already loaded at L765:

```python
    boundary_target = (existing or {}).get("boundary_target") or 0
    force_flush = prev_offset < boundary_target
```

⚠️ **A flush flag alone does NOT keep ingestion inside the accepted boundary**
(council R11, both peers). `parse_transcript` has no absolute offset ceiling: if the
transcript grows between the nudge and the worker running it (PreCompact nudges a LIVE
session), the payload can run past `boundary_target` and ingest turns nobody nudged —
which is exactly the consent violation the disabled-watcher scope is meant to prevent. So
when a boundary is active and discovery is off, cap the parse as well:

```python
    slice_bytes = flush_bytes
    if force_flush and not self_discover:      # disabled watcher: never exceed the target
        slice_bytes = max(1, min(flush_bytes, boundary_target - prev_offset))
    result = parse_transcript(path, start_offset=prev_offset, max_bytes=slice_bytes)
```

The safe-boundary rule still applies inside that cap, so a response is never split from its
prompt. With the watcher ENABLED the cap is unnecessary (discovery is consented) and would
only slow the drain. Regression: `test_growth_after_nudge_is_not_ingested_when_disabled`.

and apply it at exactly two places: the idle/flush gate (`_should_flush`, L717-725/L840)
and the `min_turns` comparison. It must NOT touch the safe-boundary parse or any
cap/quarantine rule — an ended session is final, but a response still being written must
never be split from its prompt.

### Clearing the flag — the part that is easy to get wrong

⚠️ **Do NOT clear it on the first successful advance** (council R9). A boundary delta
larger than `flush_bytes` drains in several capped batches: clearing after batch 1 drops
`force_flush` for the remainder, and the final sub-cap tail — neither idle nor capped, and
possibly under `min_turns` — then waits out the 600s idle threshold. The "immediate
SessionEnd flush" would be immediate only for small sessions.

So the flag is **a target, not a one-shot**: it stays set until the transcript has drained
through the boundary, and is cleared exactly on the returns that PROVE there is nothing
closed left:

| Site | Condition | Action |
|------|-----------|--------|
| L770-771 | unchanged hash AND cursor at EOF (already consumed) | clear |
| L829-835 | `payload_offset <= prev_offset` on an IDLE file (verified empty closed delta) | clear |
| L970-983 | successful ingest that reaches the target (`payload_offset >= boundary_target`) | clear |
| L970-983 | successful ingest still short of the target (capped drain) | **keep** — the drain continues |
| any TRANSIENT return | — | **keep** (council R6: durability is the point) |
| file no longer exists | `path.exists()` is False | **clear the whole entry** |

The last row is council R10 (cursor): a deleted transcript returns TRANSIENT forever, and
with the always-on reconcile that entry would be retried on every tick for good. Detect it
at the top of `_ingest_session` (the `_file_hash`/`stat` OSError paths, L753-762) and drop
the entry instead of keeping a doomed intent.

⚠️ **Do not clobber a nudge that arrived mid-extraction — on ANY write path**
(council R10/R11). `_ingest_session` reads `existing` at L765 and commits a rebuilt entry
minutes later. A nudge accepted during that window writes `boundary_target` into the file,
and a stale rebuild erases it — the 202 is already sent, the hook already dropped its
cursor key, and the boundary is silently lost.

This is NOT only the success path. Every exit that calls `_commit_state` builds from the
same pre-extraction snapshot: the success rebuild (L970-983), `_record_extract_failure`'s
counter write (L902-908) and quarantine write (L869-889), and the clearing sites in the
table above. **All of them** must re-read the entry under `state_lock` and merge rather
than overwrite — `boundary_target` takes `max(stale, current)` and is never dropped by a
writer that never saw it. The cleanest implementation is a single helper
(`_merge_state(state, rel, updates, state_lock, watch_dir)`) that does read-merge-write
under the lock, and making every call site use it instead of `_commit_state` with a
hand-built dict. Regression: `test_nudge_during_extraction_is_not_clobbered`, parameterised
over the success, failure-counter and quarantine paths.

The L829-835 site matters twice over (council R9 / cursor): with the reconcile always on,
a flag stranded there makes that transcript be re-queued on every single tick, forever.
The `not is_idle` branch just above it returns TRANSIENT for a still-growing file — keep
the flag there, the session is still being written.

⚠️ **Crash-safety is a precondition, not a detail** (council R9). This task promises a 202
whose intent survives a crash, but `_save_state` (L700-703) does
`state_path.write_text(...)` straight over the shared JSON file. A crash mid-write leaves
truncated JSON, and `_load_state` (L689-697) treats a corrupt file as "start fresh" —
losing `boundary_target` AND every cursor in that watch dir, while the hook has already
retired its legacy cursor on the 202. Make the write atomic in THIS task:

```python
def _save_state(watch_dir: Path, state: dict) -> None:
    """Persist state atomically — a torn write would discard every cursor in this dir."""
    state_path = watch_dir / _STATE_FILENAME
    tmp = state_path.with_suffix(state_path.suffix + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, state_path)
    with contextlib.suppress(OSError):          # durability of the rename itself
        dir_fd = os.open(state_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
```

Regression: `test_save_state_is_atomic_under_a_torn_write` — write a large state, simulate
a failure between the temp write and the replace (patch `os.replace` to raise), and assert
the ORIGINAL file is still valid JSON with every prior entry intact.

- [ ] **Step 4: Implement — route**

In `routes_ingest.py` (imports: add `from pathlib import Path`):

```python
class NudgeRequest(BaseModel):
    path: str
    session_id: str | None = None


@router.post("/nudge", status_code=202)
def ingest_nudge(req: NudgeRequest, request: Request):
    """ADR-0004: fire-and-forget ingest trigger. The server owns the cursor; the worker
    ingests the delta on its own schedule. The client never waits on extraction."""
    watches = getattr(request.app.state, "session_watches", [])
    path = Path(req.path).resolve()
    for w in watches:
        try:
            path.relative_to(Path(w.watch_dir).resolve())
        except ValueError:
            continue
        if not path.is_file():
            raise HTTPException(status_code=404, detail="transcript not found")
        try:
            w.handler.nudge(path)      # persists the pending marker BEFORE we answer 202
        except OSError as e:
            # council R5: never acknowledge what we could not record — the hook retires
            # its legacy cursor on 202 and does not retry.
            raise HTTPException(status_code=503, detail=f"could not accept nudge: {e}")
        return {"status": "accepted"}
    raise HTTPException(status_code=422, detail="path outside watched directories")
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_api/test_routes_ingest.py tests/test_background/test_session_watcher.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/api/routes_ingest.py src/ormah/background/session_watcher.py tests/
git commit -m "feat(api): POST /ingest/nudge — fire-and-forget trigger into the ingest worker (ADR-0004)"
```

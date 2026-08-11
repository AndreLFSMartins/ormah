# Task 4: `POST /ingest/nudge` — 202, feeds the worker

**Files:**
- Modify: `src/ormah/api/routes_ingest.py` (add model + route; `/conversation` and `/file` stay — other clients use them)
- Modify: `src/ormah/background/session_watcher.py` (`SessionHandler.nudge()` public method, next to `_schedule_ingest` L1084)
- Test: create `tests/test_api/test_routes_ingest.py`

**Interfaces:**
- Consumes: `app.state.session_watches` and `SessionWatch`/`SessionHandler` from Task 3.
- Produces:
  - `SessionHandler.nudge(path: Path) -> None` — thread-safe enqueue with **boundary
    semantics**, all of it DURABLE (council R5/R6): it merges `{"boundary_pending": True}`
    into the transcript's state entry — creating the entry with `end_offset: 0` only when
    none exists, and NEVER touching an existing cursor — then schedules the ingest with
    **zero debounce**. The flag lives in the state file, so a crash, a timeout, or a
    provider failure cannot lose the boundary intent: every later attempt (retry, reconcile,
    startup drain) re-derives `force_flush` from it. It is cleared only when the cursor
    actually advances or the closed delta is verified empty.
  - **Zero debounce** (council R6): `session_watcher_debounce_seconds` defaults to 60s, so
    routing a nudge through the ordinary debounce would delay a SessionEnd delta by a
    minute for no reason — the session already ended. `nudge()` must schedule immediately
    (e.g. `_schedule_ingest(path, delay=0)` / `Timer(0, ...)`, matching whatever the real
    `_schedule_ingest` signature at L1084 allows), while keeping the in-flight guard so a
    concurrent Observer event still coalesces.
  - `_ingest_session(...)` reads `boundary_pending` from the entry it already loads
    (`existing`, L765) and treats it as `force_flush`: it bypasses ONLY the
    idle-threshold and `min_turns` gates. The safe-boundary rule (closed content only) and
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
    assert entry["boundary_pending"] is True
    assert entry["end_offset"] == 0

    # an EXISTING cursor must survive a later nudge untouched
    state = _load_state(watch_dir)
    state[rel] = {"end_offset": 4242, "hash": "deadbeef"}
    _save_state(watch_dir, state)
    assert client.post("/ingest/nudge", json={"path": str(jsonl)}).status_code == 202
    entry = _load_state(watch_dir)[rel]
    assert entry["end_offset"] == 4242
    assert entry["boundary_pending"] is True


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
    result leaves boundary_pending set so the retry still bypasses the idle gate."""
    from ormah.background.session_watcher import _ingest_session, _load_state
    # nudge -> patch the LLM to fail transiently -> _ingest_session returns TRANSIENT
    # assert _load_state(watch_dir)[rel]["boundary_pending"] is still True
    # then succeed -> assert the flag is gone
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
        # council R7: read-modify-write MUST hold the SAME lock _commit_state uses
        # (`_state_lock`), not the handler's `_lock`. Otherwise an extraction committing
        # cursor progress between our read and write is lost — or clobbers our flag.
        with self._state_lock:
            entry = dict(self._state.get(rel) or {})
            entry.setdefault("end_offset", 0)   # never overwrite a real cursor
            entry["boundary_pending"] = True
            _commit_state(self._state, rel, entry, None, self.watch_dir)  # lock already held
        self._schedule_ingest(path, delay=0)    # adapt to the real signature at L1084

Check `_commit_state`'s re-entrancy (L706-714) before writing this: if it always takes the
lock itself, do the read under that same lock via a small helper rather than passing None.
```

Read `_schedule_ingest` (L1084) and the handler's state/lock attribute names before
writing this — adapt the call, keep the semantics. If `_schedule_ingest` has no delay
parameter, add one defaulting to the configured debounce.

In `_ingest_session`, derive the flag from the entry already loaded at L765:

```python
    force_flush = bool((existing or {}).get("boundary_pending"))
```

and apply it at exactly two places: the idle/flush gate (`_should_flush`, L717-725/L840)
and the `min_turns` comparison. It must NOT touch the safe-boundary parse or any
cap/quarantine rule — an ended session is final, but a response still being written must
never be split from its prompt. Clear `boundary_pending` ONLY on real progress: pop it in
the success path that rebuilds the entry (L970-981) and in the verified-empty-delta path.
A TRANSIENT result must LEAVE IT SET (council R6) — that is the whole point of durability.

⚠️ Also clear it on the **already-consumed early return** (council R7): `_ingest_session`
returns `NO_PROGRESS` at L770-771 when the hash is unchanged and the cursor is at EOF,
BEFORE any flush logic. A nudge for an already-ingested transcript would otherwise leave
`boundary_pending=True` forever. Pop the flag there too — the delta really is empty, which
is exactly the "verified empty" condition.

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

# Task 3: `POST /ingest/nudge` — enqueue to the spool, answer 202

**Files:**
- Modify: `src/ormah/api/routes_ingest.py` (add model + route; `/conversation` and `/file`
  stay — other clients use them)
- Modify: `src/ormah/background/session_watcher.py` — `_ingest_session` gains a
  `boundary: int | None` parameter (force-flush + hard ceiling)
- Modify: `src/ormah/transcript/parser.py` — `parse_transcript` gains an absolute
  `stop_offset` (⚠️ see the risk note in Step 4; own commit, own regression suite)
- Test: create `tests/test_api/test_routes_ingest.py`

**Interfaces:**
- Consumes: `IngestSpool` (Task 1) and `app.state.session_watches` (Task 2).
- Produces:
  - `POST /ingest/nudge` body `{"path": str, "session_id": str|null}` →
    `202 {"status": "accepted"}`; `404` file missing; `422` path outside every acceptance
    root; `503` if the spool write failed.
  - The endpoint **enqueues and returns**. It computes the boundary (`stat().st_size` at
    acceptance), writes one spool file, and answers. It never touches the Cursor, never
    schedules a timer, never waits on extraction.

**What this task is NOT any more.** The cursor-only design had the endpoint merge a
`boundary_target` field into the shared state file under a lock, then keep it alive across
capped drains and clear it on exactly the right four return sites — roughly 250 lines of
plan and a race per field. The spool absorbs all of it: the boundary is the job, the job is
a file, and a completed job is an unlinked file. If you find yourself adding a flag to the
state entry, stop — that is the design this amendment replaced.

- [ ] **Step 1: Write the failing tests**

Look at an existing `tests/test_api/` file first (e.g. `test_routes.py`) and reuse its
FastAPI `TestClient`/app fixture pattern.

```python
from pathlib import Path
from unittest.mock import MagicMock

from ormah.background.ingest_spool import IngestSpool


def _watch_stub(watch_dir: Path, spool: IngestSpool):
    w = MagicMock()
    w.watch_dir = watch_dir
    w.spool = spool
    return w


def test_nudge_enqueues_and_accepts(client, app, tmp_path):
    t = tmp_path / "proj" / "session.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user"}\n')
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]

    r = client.post("/ingest/nudge", json={"path": str(t)})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}

    job = spool.claim_next()
    assert job is not None
    assert job.path == t.resolve()
    assert job.boundary == t.stat().st_size, "the boundary is the EOF at acceptance"
    assert job.reason == "nudge"


def test_the_job_is_durable_BEFORE_the_202(client, app, tmp_path):
    """The hook drops its outbox record on a 202. If the file is not on disk by then,
    the boundary is lost on a crash. Assert against the filesystem, not a mock."""
    t = tmp_path / "p" / "s.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user"}\n')
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    assert client.post("/ingest/nudge", json={"path": str(t)}).status_code == 202
    assert spool.pending_count() == 1


def test_nudge_returns_503_when_the_spool_write_fails(client, app, tmp_path, monkeypatch):
    """council R5/R11: never acknowledge what we could not record. A 202 the hook cannot
    trust is worse than an error it will retry."""
    t = tmp_path / "p" / "s.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text("x")
    spool = IngestSpool(tmp_path / "queue")
    monkeypatch.setattr(spool, "enqueue", MagicMock(side_effect=OSError("disk full")))
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    assert client.post("/ingest/nudge", json={"path": str(t)}).status_code == 503


def test_nudge_rejects_path_outside_acceptance_roots(client, app, tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(watched, spool)]
    outside = tmp_path / "evil.jsonl"
    outside.write_text("x")
    assert client.post("/ingest/nudge", json={"path": str(outside)}).status_code == 422
    assert spool.pending_count() == 0


def test_nudge_404_on_missing_file(client, app, tmp_path):
    app.state.session_watches = [_watch_stub(tmp_path, IngestSpool(tmp_path / "q"))]
    assert client.post(
        "/ingest/nudge", json={"path": str(tmp_path / "gone.jsonl")}).status_code == 404


def test_symlinked_spellings_do_not_double_enqueue(client, app, tmp_path):
    """Two paths for one transcript must not become two independent ingests."""
    real = tmp_path / "p" / "s.jsonl"
    real.parent.mkdir(parents=True)
    real.write_text("x")
    link = tmp_path / "p" / "alias.jsonl"
    link.symlink_to(real)
    spool = IngestSpool(tmp_path / "queue")
    app.state.session_watches = [_watch_stub(tmp_path, spool)]
    client.post("/ingest/nudge", json={"path": str(real)})
    client.post("/ingest/nudge", json={"path": str(link)})
    jobs = []
    while (j := spool.claim_next()) is not None:
        jobs.append(j)
        spool.complete(j)
    assert len({j.path for j in jobs}) == 1
```

And in `tests/test_background/test_session_watcher.py`:

```python
def test_force_flush_ingests_fresh_small_transcript(engine, tmp_path):
    """A JUST-written transcript (not idle) with fewer than min_turns user turns is
    ingested when a boundary is present, and is NOT ingested without one — that gap is
    what makes a SessionEnd nudge useless otherwise."""
    watch_dir = tmp_path / "projects"
    project_dir = watch_dir / "-Users-alice-Code-myproject"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "abc123.jsonl"
    _make_jsonl(jsonl, user_turns=2)          # below min_turns, and NOT _mark_idle'd
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5) != IngestResult.OK
        assert _ingest_session(
            engine, jsonl, {}, watch_dir, min_turns=5,
            boundary=jsonl.stat().st_size) == IngestResult.OK


def test_ingest_never_reads_past_the_accepted_boundary(engine, tmp_path):
    """council R11: PreCompact nudges a LIVE session. If the transcript grows between the
    nudge and the worker running it, turns nobody nudged must not be ingested — that is
    the consent violation, and parse_transcript has no absolute ceiling of its own."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "s.jsonl"
    _make_jsonl(jsonl, user_turns=4)
    boundary = jsonl.stat().st_size
    _make_jsonl(jsonl, user_turns=12)         # grew AFTER the nudge was accepted
    rel = str(jsonl.relative_to(watch_dir))
    state = {}
    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        _ingest_session(engine, jsonl, state, watch_dir, min_turns=5, boundary=boundary)
    assert state[rel]["end_offset"] <= boundary


# NOTE: the capped-drain case is owned by Task 2 and is implemented there as
# test_a_capped_batch_re_enqueues_the_remainder — do not duplicate it here.
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_api/test_routes_ingest.py -v
```

Expected: FAIL — 404/405, the route does not exist.

- [ ] **Step 3: Implement the route**

In `routes_ingest.py` (imports: add `from pathlib import Path`):

```python
class NudgeRequest(BaseModel):
    path: str
    session_id: str | None = None


@router.post("/nudge", status_code=202)
def ingest_nudge(req: NudgeRequest, request: Request):
    """ADR-0004: fire-and-forget ingest trigger. The server owns the cursor; the worker
    drains the spool on its own schedule. The client never waits on extraction."""
    watches = getattr(request.app.state, "session_watches", [])
    path = Path(req.path).resolve()
    for w in watches:
        try:
            path.relative_to(Path(w.watch_dir).resolve())
        except ValueError:
            continue
        try:
            boundary = path.stat().st_size
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="transcript not found")
        try:
            # DURABLE BEFORE THE 202: the hook drops its outbox record on this response
            # and never retries, so an unrecorded nudge is a lost session.
            w.spool.enqueue(path, boundary=boundary, reason="nudge")
        except OSError as e:
            raise HTTPException(status_code=503, detail=f"could not accept nudge: {e}")
        w.handler.wake()          # Task 2: nudge the worker loop; never blocks
        return {"status": "accepted"}
    raise HTTPException(status_code=422, detail="path outside watched directories")
```

Note what is absent: no lock, no read-modify-write, no state-file access, no timer, no
debounce discussion. The 60s debounce problem does not arise because the endpoint does not
schedule — it enqueues, and the worker is already awake or is woken.

- [ ] **Step 4: Implement — `_ingest_session(..., boundary=None)`**

Two effects, both narrow:

⚠️ **`max_bytes` IS NOT A CEILING — this needs a parser change** (council R12, codex;
confirmed verbatim in the source). An earlier draft of this task wrote:

```python
    slice_bytes = max(1, min(flush_bytes, boundary - prev_offset))   # WRONG: not a ceiling
    result = parse_transcript(path, start_offset=prev_offset, max_bytes=slice_bytes)
```

That is a **budget**, not a limit. `parse_transcript`'s own docstring
([parser.py:222-223](../../../../src/ormah/transcript/parser.py#L222-L223)) says it plainly:

> *"A single turn larger than max_bytes is committed anyway (there is no smaller slice to
> make progress with)."*

So a session that grew after the nudge — PreCompact nudges a **live** session — can have one
oversized turn committed straight past the accepted boundary and shipped to a remote
extractor. That is precisely the consent violation the boundary exists to prevent, and no
amount of arithmetic on `max_bytes` closes it.

**Required:** an absolute `stop_offset` parameter on `parse_transcript`, honoured as a hard
limit: no turn is committed whose end exceeds it, and `safe_end_offset` is never returned
beyond it. Then:

```python
    force_flush = boundary is not None
    result = parse_transcript(
        path,
        start_offset=prev_offset,
        max_bytes=flush_bytes,        # batching budget, unchanged
        stop_offset=boundary,         # absolute ceiling: a nudge authorises exactly the
    )                                 # bytes it measured, and not one more
```

⚠️ **Apply it on EVERY parse in this lane, not just the happy path.** The orphan-recovery
rewind (`should_rewind`, [parser.py:368](../../../../src/ormah/transcript/parser.py#L368),
ADR-0003) re-parses from an earlier offset and must carry the same ceiling — otherwise the
recovery path becomes the leak.

⚠️ **Risk, flagged deliberately.** This is the only part of slice 1 that modifies
`transcript/parser.py`, which stabilised only at merge 66405d9 (ADR-0003 orphan handling).
Treat it as its own commit with its own regression suite, and if it starts touching the
safe-boundary logic rather than merely bounding it, **stop and split it into its own slice**
— the ceiling is worth having, but not at the cost of destabilising the parser. Required
tests: an oversized first turn that arrives after acceptance, and the legacy rewind branch.

`force_flush` bypasses ONLY the idle-threshold and the `min_turns` gate (`_should_flush`
L717-725/L840, and the `min_turns` comparison). It must NOT touch the safe-boundary rule or
any cap/quarantine rule: an ended session is final, but a response still being written must
never be split from its prompt.

Everything the cursor-only plan said about *clearing* the flag is gone. There is no flag.
The job's lifetime is the file's lifetime, and Task 2 owns the "capped drain → re-enqueue
the remainder" loop.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_api/test_routes_ingest.py tests/test_background/test_session_watcher.py -v
```

Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/api/routes_ingest.py src/ormah/background/session_watcher.py tests/
git commit -m "feat(api): POST /ingest/nudge enqueues a durable spool job and returns 202 (ADR-0004)"
```

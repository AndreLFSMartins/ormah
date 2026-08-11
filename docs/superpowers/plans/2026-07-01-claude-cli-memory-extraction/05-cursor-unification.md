### Task 05: Hook defers to a RUNNING watcher (single extraction path, no silent loss)

Both extraction paths hit a metered LLM, so they must not double-extract — but deferring purely on a
config flag is wrong: if `session_watcher_enabled=true` yet the watcher is not actually running, the
hook would skip and **nobody extracts** → silent loss. Fix: the hook defers only when the server
reports the watcher genuinely active; otherwise it extracts. The child extractor also no-ops its own
hook via `ORMAH_EXTRACTOR_CHILD` (set by the adapter, Task 02) — belt-and-suspenders vs recursion.

**Health lives in `routes_admin.py` at `/admin/health`** (NOT `routes_health.py` / `/health`);
`cli_adapter.py:236` (`cmd_status`) already calls `/admin/health`.

**Files:**
- Modify: `src/ormah/api/routes_admin.py` (add `session_watcher_active` to the `/admin/health` payload)
- Modify: `src/ormah/main.py` (record `app.state.session_watcher_active` after startup)
- Modify: `src/ormah/adapters/cli_adapter.py` (`cmd_whisper_store`, ~line 412)
- Test: `tests/test_adapters/test_whisper_store_gate.py`, `tests/test_api/test_health_watcher.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api/test_health_watcher.py
from tests.test_api.conftest import make_client  # or the module's existing app factory

def test_admin_health_reports_watcher_active(tmp_path):
    client = make_client(tmp_path)                 # existing helper used by test_routes.py
    client.app.state.session_watcher_active = True
    assert client.get("/admin/health").json()["session_watcher_active"] is True

# tests/test_adapters/test_whisper_store_gate.py
import io, json, sys
import pytest
from ormah.adapters import cli_adapter


def _run(monkeypatch, watcher_active, child=False):
    monkeypatch.setattr(cli_adapter, "_watcher_active", lambda: watcher_active)
    monkeypatch.setenv("ORMAH_EXTRACTOR_CHILD", "1" if child else "")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"transcript_path": "/nonexistent.jsonl", "cwd": "/x", "session_id": "s1"})))
    extracted = {"called": False}
    monkeypatch.setattr(cli_adapter, "_whisper_store_client",
        lambda: (extracted.__setitem__("called", True), (_ for _ in ()).throw(SystemExit(0))))
    with pytest.raises(SystemExit):
        cli_adapter.cmd_whisper_store(object())
    return extracted["called"]


def test_hook_skips_when_watcher_active(monkeypatch):
    assert _run(monkeypatch, watcher_active=True) is False    # defers to running watcher


def test_hook_extracts_when_watcher_down(monkeypatch):
    assert _run(monkeypatch, watcher_active=False) is True     # fallback, no silent loss


def test_child_extractor_hook_is_noop(monkeypatch):
    # The claude -p child's own hook must never extract (recursion guard, even if watcher is down).
    assert _run(monkeypatch, watcher_active=False, child=True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_adapters/test_whisper_store_gate.py tests/test_api/test_health_watcher.py -v`
Expected: FAIL — `session_watcher_active` not in `/admin/health`; `_watcher_active` / child-guard absent.

- [ ] **Step 3: Expose RUNTIME watcher liveness (not a startup flag)**

A cached `bool(session_watches)` only proves observers were created at boot; if one dies later,
health would still report active and the hook would defer forever → silent loss. Compute liveness
dynamically from the observer objects at request time.

In `src/ormah/main.py` lifespan, keep the watches/observers on app.state (already done for
shutdown):
```python
        app.state.session_watches = session_watches   # list of observers/handles (may be empty)
```

In `src/ormah/api/routes_admin.py`, add a live helper + field to the `/admin/health` payload:
```python
def _watcher_alive(app) -> bool:
    watches = getattr(app.state, "session_watches", None) or []
    # A watch is alive if its observer thread is still running (watchdog Observer.is_alive()).
    return any(getattr(w, "is_alive", lambda: False)() for w in watches)
```
```python
    "session_watcher_active": _watcher_alive(request.app),
```

(If `session_watches` holds handles wrapping an observer, unwrap to the observer before `is_alive()`
— match whatever `start_session_watcher` returns on this branch.)

- [ ] **Step 3-test: regression — a dead observer flips health to inactive**

```python
# tests/test_api/test_health_watcher.py  (add)
def test_admin_health_false_when_observer_stopped(tmp_path):
    client = make_client(tmp_path)
    class _DeadObs:
        def is_alive(self): return False
    client.app.state.session_watches = [_DeadObs()]
    assert client.get("/admin/health").json()["session_watcher_active"] is False
```

- [ ] **Step 4: Gate the hook (child-guard + real availability)**

In `src/ormah/adapters/cli_adapter.py`, add the helper and gate at the top of `cmd_whisper_store`
(after parsing `hook_data`, before resolving the transcript):

```python
def _watcher_active() -> bool:
    """True if the server reports a running session watcher. Any error -> inactive."""
    try:
        with _whisper_client() as c:  # short-timeout client
            return bool(c.get("/admin/health").json().get("session_watcher_active"))
    except Exception:
        return False
```

```python
    # The claude -p extractor child must never run this hook (recursion guard).
    if os.environ.get("ORMAH_EXTRACTOR_CHILD"):
        sys.exit(0)
    # Defer to the watcher ONLY when it is actually running; otherwise extract (no silent loss).
    if _watcher_active():
        sys.exit(0)
```

(Ensure `import os` is present in the module.)

- [ ] **Step 5: Cursor-desync trade-off (documented + fallback test)**

Deferring does NOT advance the hook's own cursor (`~/.cache/ormah/whisper-cursors.json`). If the
watcher later dies, the hook resumes from the old cursor and re-POSTs slices the watcher already
ingested. This is an ACCEPTED trade-off: the watcher's `.session_watcher_state` is authoritative
while it runs, and server-side dedup (`_is_duplicate_memory` in `ingest_conversation`) collapses the
overlap into no new nodes. Add a regression test asserting the overlap produces zero new memories:

```python
# tests/test_whisper/test_whisper_out.py  (add)
def test_defer_then_watcher_down_dedupes_overlap(engine, sample_transcript):
    # Watcher ingests slice A; watcher down; hook re-sends A -> dedup yields no new nodes.
    first = engine.ingest_conversation(content=sample_transcript, agent_id="session-transcript")
    again = engine.ingest_conversation(content=sample_transcript, agent_id="anon")
    assert isinstance(first, list) and len(first) >= 1
    assert again == [] or all(m.get("duplicate") for m in again)
```

- [ ] **Step 5c: Do NOT advance the hook cursor on a 200-with-error ingest (silent-loss fix)**

`/ingest/conversation` returns **HTTP 200 with `{"status":"error", "extracted":0}`** when extraction
fails (e.g. claude_cli returned `None`). The current hook advances its cursor after
`r.raise_for_status()` — which passes on a 200 — so a failed extraction would advance the cursor and
**permanently skip that transcript slice**. In the hook's fallback extraction path
(`cmd_whisper_store`, near the existing cursor-save at ~line 482), gate the cursor advance on the
response body:

Only a genuine **error** blocks the cursor. A `status:processed` with `extracted == 0` is a
LEGITIMATE empty extraction (nothing memorable in the slice) — it MUST advance the cursor, else the
same slice is re-processed forever. Gate strictly on the error status:

```python
        resp = r.json()
        if resp.get("status") == "error":
            sys.exit(0)  # extraction failed — do NOT advance the cursor; retry next time
        # status == "processed" (even with extracted == 0) is success: advance past this slice.
        cursors[cursor_key] = result.safe_end_offset
        _save_cursors(cursors)
```

Add two tests — the error case AND the legitimate-empty case (regression guard):
```python
# tests/test_adapters/test_whisper_store_gate.py  (add)
def test_hook_does_not_advance_cursor_on_ingest_error(monkeypatch, tmp_path):
    # 200-with-status:error must leave the cursor untouched so the slice is retried.
    ...  # stub _whisper_store_client to return {"status":"error","extracted":0}; assert cursor unchanged

def test_hook_advances_cursor_on_processed_zero_memories(monkeypatch, tmp_path):
    # status:processed + extracted:0 is a valid empty extraction — cursor MUST advance (no infinite retry).
    ...  # stub to return {"status":"processed","extracted":0}; assert cursor advanced to safe_end_offset
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_adapters/test_whisper_store_gate.py tests/test_api/test_health_watcher.py tests/test_whisper/test_whisper_out.py -v`
Expected: PASS. If `make_client`/fixtures differ, mirror the pattern already in `tests/test_api/test_routes.py`.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/api/routes_admin.py src/ormah/main.py src/ormah/adapters/cli_adapter.py \
        tests/test_adapters/test_whisper_store_gate.py tests/test_api/test_health_watcher.py \
        tests/test_whisper/test_whisper_out.py
git commit -m "feat(whisper): hook defers to running watcher via /admin/health + child-hook guard"
```

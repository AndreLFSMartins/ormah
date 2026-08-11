# Task 3: Hook becomes a pure nudge — client cursor machinery deleted

**Files:**
- Modify: `src/ormah/adapters/cli_adapter.py` — rewrite `cmd_whisper_store` (L423-519);
  delete `_whisper_store_timeout` (L387-396), `_whisper_store_client` (L399-401); repurpose
  the cursor file for nudge counters only (see Step 3); check `_spawn_background_store`
  (L364-384) callers still make sense (they do — a periodic store is now a cheap nudge).
- Modify: `integrations/claude-plugin/hooks/hooks.json` — `PreCompact`/`SessionEnd` timeout 300 → 30.
- Modify: `src/ormah/setup.py` `configure_claude_hooks` (L337-373) — same timeout change;
  keep `PreCompact` `"async": True`; check `configure_codex_hooks` (L457) for the same pattern.
- Test: `tests/test_whisper/test_whisper_out.py` (major rewrite), `tests/test_setup.py` (timeout assertions).

**Interfaces:**
- Consumes: `POST /ingest/nudge` from Task 2.
- Produces: `cmd_whisper_store` that reads the hook JSON from stdin, resolves
  `transcript_path`, POSTs `{"path": ..., "session_id": ...}` to `/ingest/nudge` with the
  SHORT client (`_client()`, 30s — the generous-timeout coupling dies with the sync POST),
  and always exits 0. No parse, no min-turns, no space-detect, no cursor (ADR consequence:
  "the hook is a trigger"). Space + min-turns + safe-boundary logic already live
  server-side in `_ingest_session` — that is WHY they can be deleted here.

**Outbox — a server outage must not lose the only SessionEnd nudge.** Server-side
reconcile cannot recover a boundary event it never heard about, so the hook keeps a durable
client-side queue. Four rules, each from a specific failure the review found:

1. **Queue FIRST, then send** (council R9). Never do network work before the current event
   is durable, or a slow drain can kill the hook before the event that just happened is
   recorded. Order: append current → send it → on ITS 202 remove it → drain older entries.
2. **Never hold the lock across the network** (council R10). Holding an exclusive lock
   through up to 20 HTTP calls blocks every concurrent hook inside `_queue_nudge`, which
   is precisely the window where their own boundary is not yet durable. The drain is
   therefore three phases: (a) take the lock, read, release; (b) do the requests with NO
   lock held; (c) re-take the lock, re-read, and rewrite only the records still present.
3. **Budget the drain in the same currency as the hook timeout** (council R9/R10). The
   manifest allows 30s. `_client()`'s own 30s timeout means ONE hung request could eat it
   all, so the hook's nudge client uses a SHORT timeout (5s) and the drain is bounded by
   both wall clock (`time.monotonic`) and request count. Current event first, always.
4. **Acknowledge by record id, not by path** (council R10). Each queued record carries a
   unique `id`; `_unqueue_nudge` removes THAT id. Removing every record for a path would
   delete a later PreCompact/SessionEnd event that never got its own 202.
5. **Lock a separate, stable file** (council R9). `flock` is an INODE lock: if the drain
   rewrites the outbox via `os.replace`, an appender blocked on the OLD inode wakes up and
   writes into an unlinked file — the event is gone. Take every lock on a dedicated
   `whisper-nudge-outbox.lock` whose inode is never replaced.

Storage is append-only JSONL. **Cap by age, not by count** — truncating to the last N would
silently drop exactly the old SessionEnd events the outbox exists to keep; drop entries
older than ~30 days or whose transcript no longer exists.

⚠️ **Declared limitation (council R9):** `fcntl.flock` is POSIX-only. On Windows the hook
falls back to no locking, so two hooks firing concurrently can interleave appends. Guard
the import (`try: import fcntl / except ImportError: fcntl = None`) and no-op the locking
there rather than crashing the hook — a lost duplicate nudge is recoverable, a crashed
SessionEnd hook is not. Document it; do not pretend it is safe.

**Nudge-counter caveat:** `_load_cursors`/`_save_cursors` also store `nudge:<session_id>`
prompt counters used by the inject path (~L298-301). Those survive, but move to their own
file so the ADR's "whisper-cursors.json is deleted" holds.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_whisper/test_whisper_out.py` top-of-file fixtures first (hook-stdin
builder, httpx mocking pattern) and reuse them:

```python
def test_whisper_store_posts_nudge(monkeypatch, tmp_path):
    """SessionEnd hook posts {path, session_id} to /ingest/nudge and exits 0 — no content,
    no parse, no cursor file."""
    # stdin: {"transcript_path": str(t), "session_id": "abc", "cwd": str(tmp_path)}
    # mock httpx: capture request; respond 202 {"status": "accepted"}
    # assert: POST to "/ingest/nudge"; json == {"path": str(t), "session_id": "abc"}
    # assert: SystemExit(0); whisper-cursors.json NOT created


def test_whisper_store_exits_zero_when_server_down(monkeypatch, tmp_path):
    """Server unreachable -> exit 0 silently (never block compaction) AND the path is
    queued in the outbox (the boundary event must not be lost)."""
    # patch httpx to raise ConnectError; run cmd_whisper_store with a temp XDG_CACHE_HOME
    # assert SystemExit(0)
    # the outbox is JSONL, one object per line:
    # recs = [json.loads(l) for l in outbox.read_text().splitlines() if l.strip()]
    # assert [r["path"] for r in recs] == [str(transcript)]


def test_current_event_is_queued_before_any_network_call(monkeypatch, tmp_path):
    """council R9: the current boundary must be durable BEFORE the POST. Patch the
    client so .post() raises SystemExit (simulating the hook being killed mid-request)
    and assert the outbox already contains this transcript."""


def test_drain_is_budgeted_and_cannot_starve_the_current_event(monkeypatch, tmp_path):
    """council R9: seed the outbox with many entries and make each POST sleep past the
    budget. The current transcript must still have been queued and POSTed first, and the
    drain must stop at _OUTBOX_DRAIN_SECONDS/_OUTBOX_DRAIN_MAX leaving the rest queued."""


def test_entry_removed_only_on_its_own_202(monkeypatch, tmp_path):
    """council R9: with a mixed response map (202 for A, 500 for B), A leaves the outbox
    and B stays — removal is never batch-wide."""


def test_concurrent_append_during_drain_is_not_lost(tmp_path):
    """council R9 (the inode trap): start a drain that rewrites the outbox while a second
    process appends. Because both take the STABLE lock file, the appended record must
    survive the os.replace. Use multiprocessing with a barrier; skip on Windows where
    fcntl is unavailable (documented degraded mode)."""


def test_outbox_is_drained_on_the_next_fire(monkeypatch, tmp_path):
    """A queued nudge is re-sent (and removed) the next time the hook runs with the
    server back up; a still-failing entry stays queued; a vanished file is dropped."""
    # seed the outbox with [gone.jsonl, old.jsonl]; delete gone.jsonl
    # mock httpx to 202 everything; run the hook for a new transcript
    # assert the POSTs include old.jsonl and the new path, never gone.jsonl
    # assert the outbox file no longer exists


def test_whisper_store_exits_zero_on_missing_transcript(monkeypatch):
    """No transcript_path and unresolvable session_id -> exit 0, no HTTP call."""


def test_legacy_cursor_key_removed_only_after_202(monkeypatch, tmp_path):
    """council R4 + R10: on 202 ONLY this transcript's key leaves whisper-cursors.json —
    other sessions' cursors survive (the file is multi-session). On 422/404 or with the
    server down nothing is removed at all."""
    # seed cursors {"sess-A": 100, "sess-B": 200}; nudge for sess-A gets 202
    # assert the file still exists and equals {"sess-B": 200}
    # then a nudge for sess-B that 422s must leave {"sess-B": 200} untouched
```

Delete the now-obsolete client-cursor tests (`test_cursor_saves_after_success` L315,
`test_cursor_not_advanced_on_extraction_error` L615, `test_cursor_advances_on_empty_processed_extraction`
L646, `test_cursor_not_advanced_on_unknown_200_status` L711, `test_cursor_not_advanced_on_client_timeout`
L732, `test_api_error_orphan_advances_cursor_without_full_reextract` L427, and any other
test exercising parse/min-turns/space inside the hook). Their BEHAVIOR is not lost — it is
covered server-side by `test_session_watcher.py`; note each deletion in the commit message.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_whisper/test_whisper_out.py -v`
Expected: new tests FAIL (hook still posts `/ingest/conversation`); obsolete ones deleted.

- [ ] **Step 3: Implement — cli_adapter.py**

1. Move nudge counters to their own file. Replace L404-420 with:

```python
_WHISPER_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))) / "ormah"
_NUDGE_COUNTER_FILE = _WHISPER_CACHE_DIR / "whisper-nudge-counters.json"
_LEGACY_CURSOR_FILE = _WHISPER_CACHE_DIR / "whisper-cursors.json"  # pre-ADR-0004, multi-session


def _retire_legacy_cursor(session_id: str, path: str) -> None:
    """Drop only this transcript's key; delete the file once it is empty (council R10)."""
    try:
        cursors = json.loads(_LEGACY_CURSOR_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(cursors, dict):
        return
    for key in (session_id, path):                # the old code keyed on either
        cursors.pop(key, None)
    try:
        if cursors:
            _LEGACY_CURSOR_FILE.write_text(json.dumps(cursors))
        else:
            _LEGACY_CURSOR_FILE.unlink(missing_ok=True)
    except OSError:
        pass
```

   and rename `_load_cursors`/`_save_cursors` → `_load_nudge_counters`/`_save_nudge_counters`
   operating on `_NUDGE_COUNTER_FILE` (same bodies). Update the inject-path call sites
   (~L298-301) — they keep only the `nudge:<session_id>` keys they already use.
2. Rewrite `cmd_whisper_store` (replaces L423-519 entirely):

```python
def cmd_whisper_store(args):
    """PreCompact/SessionEnd hook: pure nudge (ADR-0004). The server owns the cursor and
    does the extraction on its own schedule; this process never waits on it."""
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    transcript_path = hook_data.get("transcript_path", "")
    session_id = hook_data.get("session_id", "")
    if not transcript_path and session_id:
        resolved = _resolve_transcript_path(session_id)
        transcript_path = str(resolved) if resolved else ""
    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    # council R9: make the CURRENT event durable before any network work — a slow or
    # backlogged drain must never be able to lose the boundary that just happened.
    rec_id = _queue_nudge(transcript_path)
    accepted = False
    try:
        with _nudge_client() as c:          # SHORT timeout (5s), not the 30s _client()
            r = c.post("/ingest/nudge", json=body)
            accepted = r.status_code == 202
            if accepted:
                _unqueue_nudge(rec_id)      # remove THIS record, not every one for the path
            _drain_nudge_outbox(c)          # older entries, budgeted, no lock over the wire
    except Exception:
        accepted = False                    # server down — the record stays queued
    if accepted:
        # Retire the legacy client cursor for THIS transcript only, and only once the
        # server has taken ownership of it (council R4 + R10). Two traps:
        #  - a 404/422/offline nudge must leave it alone — it is the only record of what
        #    was already ingested;
        #  - whisper-cursors.json is MULTI-SESSION (keyed by session_id/path), so
        #    unlinking the file would wipe cursors for sessions that have not migrated.
        _retire_legacy_cursor(session_id, transcript_path)
    sys.exit(0)
```

3. Add the outbox helpers next to the counter helpers:

Add `import contextlib, os, sys, time, uuid` at the top of `cli_adapter.py` if absent.

```python
try:
    import fcntl                      # POSIX only; see the declared limitation above
except ImportError:                   # pragma: no cover - Windows
    fcntl = None

_NUDGE_OUTBOX_FILE = _WHISPER_CACHE_DIR / "whisper-nudge-outbox.jsonl"
_NUDGE_OUTBOX_LOCK = _WHISPER_CACHE_DIR / "whisper-nudge-outbox.lock"
_OUTBOX_MAX_AGE_DAYS = 30
_OUTBOX_DRAIN_SECONDS = 5.0           # well under the 30s hook timeout
_OUTBOX_DRAIN_MAX = 20


@contextlib.contextmanager
def _outbox_lock():
    """Lock a STABLE file, never the outbox itself.

    flock locks an inode. The drain replaces the outbox path, so a locker holding the
    old inode would let an appender write into an unlinked file — losing the event.
    """
    _WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if fcntl is None:                 # Windows: degraded, documented, never fatal
        yield
        return
    with open(_NUDGE_OUTBOX_LOCK, "a+") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _nudge_client() -> httpx.Client:
    """Short-timeout client for the hook (council R10): the manifest allows 30s TOTAL,
    so a single request must never be able to consume the whole budget."""
    return httpx.Client(base_url=BASE, timeout=5.0)


def _queue_nudge(path: str) -> str:
    """Append a boundary event durably and return its record id.

    Called BEFORE any network work; the id is what an ack removes (council R10).
    """
    rec_id = uuid.uuid4().hex
    try:
        with _outbox_lock():
            with open(_NUDGE_OUTBOX_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"id": rec_id, "path": path, "at": time.time()}) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
    except OSError as e:
        # Degraded mode (council R9): the boundary event is lost if the server is also
        # down. Say so on stderr — silent loss is what we are trying to avoid — but
        # never block or fail the hook.
        print(f"ormah: could not queue nudge: {e}", file=sys.stderr)
    return rec_id


def _rewrite_outbox(records: list[dict]) -> None:
    """Atomic rewrite. Caller MUST hold _outbox_lock()."""
    tmp = _NUDGE_OUTBOX_FILE.with_suffix(f".jsonl.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _NUDGE_OUTBOX_FILE)


def _read_outbox() -> list[dict]:
    """Caller MUST hold _outbox_lock(). Skips torn lines instead of crashing."""
    out = []
    try:
        for line in _NUDGE_OUTBOX_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except (FileNotFoundError, OSError):
        pass
    return out


def _unqueue_nudge(rec_id: str) -> None:
    """Drop ONE record after its own 202 — never every record for that path."""
    try:
        with _outbox_lock():
            _rewrite_outbox([r for r in _read_outbox() if r.get("id") != rec_id])
    except OSError:
        pass


def _drain_nudge_outbox(c) -> None:
    """Retry older queued nudges, oldest first, within a strict budget.

    Budgeted because an unbounded backlog with a 30s-per-request client would outlive the
    hook itself (council R9). Whatever does not fit stays queued for the next fire.
    """
    deadline = time.monotonic() + _OUTBOX_DRAIN_SECONDS
    cutoff = time.time() - _OUTBOX_MAX_AGE_DAYS * 86400
    try:
        with _outbox_lock():                      # phase (a): read, then RELEASE
            records = _read_outbox()
    except OSError:
        return

    acked, sent, seen = set(), 0, set()
    for rec in records:                           # phase (b): network, NO lock held
        p, at, rid = rec.get("path"), rec.get("at", 0), rec.get("id")
        if not p or not rid:
            continue
        if at < cutoff or not Path(p).exists():
            acked.add(rid)                        # expired / transcript gone
            continue
        if p in seen:
            # council R11: only treat it as a duplicate when the earlier record for this
            # path actually got a 202. Marking it acked on a FAILED send would discard a
            # newer boundary that was never delivered.
            acked.add(rid)
            continue
        if sent >= _OUTBOX_DRAIN_MAX or time.monotonic() >= deadline:
            break                                 # out of budget: the rest stays queued
        sent += 1
        try:
            status = c.post("/ingest/nudge",
                            json={"path": p, "session_id": None}).status_code
            if status == 202:
                acked.add(rid)
                seen.add(p)                       # only NOW is a later record a duplicate
            elif status in (404, 422):
                # council R11: a permanently un-acceptable path must not occupy the drain
                # budget for 30 days and starve valid backlog behind it.
                acked.add(rid)
        except Exception:
            pass                                  # transient: keep it queued

    try:
        with _outbox_lock():                      # phase (c): re-read, drop only acked ids
            _rewrite_outbox([r for r in _read_outbox() if r.get("id") not in acked])
    except OSError:
        pass
```

(Every read, append, rewrite and replace happens under the STABLE lock file, so a
concurrent appender can never land in a replaced inode. A duplicate nudge is harmless —
the server treats a repeat as idempotent.)

4. Delete `_whisper_store_timeout` and `_whisper_store_client` (L387-401) and the
   `parse_transcript`/`should_rewind` import inside the old body. Then
   `grep -n "_whisper_store_client\|_whisper_store_timeout\|_load_cursors\|_save_cursors" src/ tests/`
   → must only hit the renamed counter helpers; fix any straggler.

- [ ] **Step 4: Implement — manifests**

`integrations/claude-plugin/hooks/hooks.json`: `"timeout": 300` → `"timeout": 30` on
`PreCompact` (L~17-31) and `SessionEnd` (L~32-42); keep `"async": true` on PreCompact as-is.
`src/ormah/setup.py` `configure_claude_hooks` L354-373: same values. Update the
corresponding assertions in `tests/test_setup.py` (search `300`) and `tests/test_setup_json.py`.
⚠️ `tests/test_setup*.py` can touch the REAL `~/.claude` — verify survival by parsing the
JSON files, never by `grep -i ormah`, and re-check `~/.claude/settings.json` afterwards.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_whisper/ tests/test_setup.py tests/test_setup_json.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/adapters/cli_adapter.py src/ormah/setup.py \
        integrations/claude-plugin/hooks/hooks.json tests/
git commit -m "feat(hook): whisper store becomes a pure /ingest/nudge trigger; client cursor deleted (ADR-0004)"
```

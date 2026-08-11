# Task 5: Hook becomes a pure nudge — client cursor machinery deleted

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
- Consumes: `POST /ingest/nudge` from Task 4.
- Produces: `cmd_whisper_store` that reads the hook JSON from stdin, resolves
  `transcript_path`, POSTs `{"path": ..., "session_id": ...}` to `/ingest/nudge` with the
  SHORT client (`_client()`, 30s — the generous-timeout coupling dies with the sync POST),
  and always exits 0. No parse, no min-turns, no space-detect, no cursor (ADR consequence:
  "the hook is a trigger"). Space + min-turns + safe-boundary logic already live
  server-side in `_ingest_session` — that is WHY they can be deleted here.

**Outbox (council R6 — a server outage must not lose the only SessionEnd nudge).** If the
POST fails (server down, non-202), the hook appends the transcript path to
`whisper-nudge-outbox.jsonl` in the cache dir and exits 0. Every subsequent hook fire first
drains that outbox (best-effort, oldest first, dropping paths whose file no longer exists)
before sending its own nudge. ⚠️ **Concurrency (council R7):** PreCompact is an `async`
hook and several sessions can fire at once, so an unlocked read-modify-write on one JSON
file loses entries. Use an **append-only JSONL** with `fcntl.flock` around every open: an
append needs no read, and the drain takes an exclusive lock, rewrites survivors to a temp
file, and `os.replace`s it. **Cap by age, not by count** (council R7 — truncating to the
last 50 would silently drop exactly the old SessionEnd events the outbox exists to keep):
drop entries older than ~30 days or whose transcript no longer exists. This keeps the hook dumb — no polling,
no blocking, no timers — while making the boundary event survive an outage longer than
`session_watcher_lookback_hours`, which server-side reconcile alone cannot recover.

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
    queued in the outbox (council R6: the boundary event must not be lost)."""
    # patch httpx to raise ConnectError; run cmd_whisper_store with a temp XDG_CACHE_HOME
    # assert SystemExit(0)
    # council R8 — the outbox is JSONL, one object per line:
    # recs = [json.loads(l) for l in outbox.read_text().splitlines() if l.strip()]
    # assert [r["path"] for r in recs] == [str(transcript)]


def test_outbox_is_drained_on_the_next_fire(monkeypatch, tmp_path):
    """A queued nudge is re-sent (and removed) the next time the hook runs with the
    server back up; a still-failing entry stays queued; a vanished file is dropped."""
    # seed the outbox with [gone.jsonl, old.jsonl]; delete gone.jsonl
    # mock httpx to 202 everything; run the hook for a new transcript
    # assert the POSTs include old.jsonl and the new path, never gone.jsonl
    # assert the outbox file no longer exists


def test_whisper_store_exits_zero_on_missing_transcript(monkeypatch):
    """No transcript_path and unresolvable session_id -> exit 0, no HTTP call."""


def test_legacy_cursor_removed_only_after_202(monkeypatch, tmp_path):
    """council R4: on 202 the legacy whisper-cursors.json is deleted (upgrade path);
    on 422/404 or with the server down it MUST survive, so nothing is lost when the
    server is not yet able to own this transcript."""
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
_LEGACY_CURSOR_FILE = _WHISPER_CACHE_DIR / "whisper-cursors.json"  # pre-ADR-0004; deleted on sight
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

    accepted = False
    try:
        with _client() as c:
            _drain_nudge_outbox(c)          # council R6: retry anything a past outage lost
            r = c.post("/ingest/nudge", json=body)
            accepted = r.status_code == 202
    except Exception:
        accepted = False                    # server down — fall through to the outbox
    if not accepted:
        _queue_nudge(transcript_path)       # durable client-side retry, drained next fire
    if accepted:
        # council R4: retire the legacy client cursor ONLY once the server has taken
        # ownership of this transcript. Deleting it on a 404/422/offline nudge would
        # discard the only record of what was already ingested.
        _LEGACY_CURSOR_FILE.unlink(missing_ok=True)
    sys.exit(0)
```

3. Add the outbox helpers next to the counter helpers:

```python
import fcntl

_NUDGE_OUTBOX_FILE = _WHISPER_CACHE_DIR / "whisper-nudge-outbox.jsonl"
_OUTBOX_MAX_AGE_DAYS = 30


def _queue_nudge(path: str) -> None:
    """Append a nudge the server could not accept. Append-only + flock: concurrent hooks
    can never lose each other's entries (council R7)."""
    try:
        _WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_NUDGE_OUTBOX_FILE, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps({"path": path, "at": time.time()}) + "\n")
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        pass  # best effort — never block the hook


def _drain_nudge_outbox(c) -> None:
    """Re-send queued nudges oldest-first under an exclusive lock; keep what still fails."""
    if not _NUDGE_OUTBOX_FILE.exists():
        return
    cutoff = time.time() - _OUTBOX_MAX_AGE_DAYS * 86400
    try:
        with open(_NUDGE_OUTBOX_FILE, "r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)          # blocks a concurrent drain, not appends
            seen, still = set(), []
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue                        # torn/partial line — skip, never crash
                p, at = rec.get("path"), rec.get("at", 0)
                if not p or p in seen or at < cutoff or not Path(p).exists():
                    continue
                seen.add(p)
                try:
                    ok = c.post("/ingest/nudge",
                                json={"path": p, "session_id": None}).status_code == 202
                except Exception:
                    ok = False
                if not ok:
                    still.append(rec)
            # council R8: rewrite ATOMICALLY. seek(0)+truncate() would lose the entire
            # outbox if the process died before the survivors were written back — exactly
            # the data this mechanism exists to protect.
            tmp = _NUDGE_OUTBOX_FILE.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(r) + "\n" for r in still), encoding="utf-8")
            os.replace(tmp, _NUDGE_OUTBOX_FILE)     # atomic; the lock is still held
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        pass
```

(`os.replace` swaps the inode while we still hold the lock on the old handle; a concurrent
`_queue_nudge` blocks on `flock` until we finish, so no append is lost. A same-path
duplicate is harmless — a repeat nudge is idempotent server-side.)

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

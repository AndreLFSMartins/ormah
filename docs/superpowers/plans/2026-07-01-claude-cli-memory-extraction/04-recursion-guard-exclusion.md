### Task 04: Recursion guard — exclude the extractor's own transcript (all paths)

The extractor's `claude -p` child writes a normal session transcript under
`~/.claude/projects/<encoded-workdir>/<uuid>.jsonl` (NOT under `subagents/`, so `_is_subagent_transcript`
does not cover it). Without exclusion, the watcher ingests it → runaway self-extraction. The
**primary live path is FSEvents** (`on_created`/`on_modified` → `_do_ingest` → `_ingest_session`),
not just the startup scan. Guard at the single chokepoint `_ingest_session` (covers scan, reconcile,
AND live) and also short-circuit in `on_created`/`on_modified` (avoids scheduling a wasted timer).

**Spike-confirmed (Task 01):** Claude Code encodes the transcript dir from the cwd's REAL path.
On macOS `/tmp` is a symlink to `/private/tmp`, so cwd `/tmp/ormah-extractor` yields
`~/.claude/projects/-private-tmp-ormah-extractor/`, NOT `-tmp-ormah-extractor`. The helper MUST
resolve the real path (`os.path.realpath`) before encoding, or the guard silently misses.

**Files:**
- Modify: `src/ormah/background/session_watcher.py` (helper near `_is_subagent_transcript` line 576;
  `_ingest_session` line ~720; `on_created`/`on_modified` line ~1123)
- Test: `tests/test_background/test_session_watcher_exclusion.py`

- [ ] **Step 1: Write the failing tests (helpers + FSEvents integration)**

```python
# tests/test_background/test_session_watcher_exclusion.py
from pathlib import Path
from unittest.mock import MagicMock
from ormah.background import session_watcher as sw
from ormah.background.session_watcher import _is_extractor_transcript, _encode_workdir


def test_encode_workdir_resolves_symlinks(monkeypatch):
    # /tmp -> /private/tmp on macOS; encoding must use the REAL path.
    monkeypatch.setattr("os.path.realpath", lambda p: "/private/tmp/ormah-extractor")
    assert _encode_workdir("/tmp/ormah-extractor") == "-private-tmp-ormah-extractor"


def test_extractor_transcript_is_excluded(monkeypatch):
    monkeypatch.setattr("os.path.realpath", lambda p: "/private/tmp/ormah-extractor")
    p = Path("/Users/x/.claude/projects/-private-tmp-ormah-extractor/abc.jsonl")
    assert _is_extractor_transcript(p, "/tmp/ormah-extractor") is True


def test_normal_transcript_is_not_excluded(monkeypatch):
    monkeypatch.setattr("os.path.realpath", lambda p: "/private/tmp/ormah-extractor")
    p = Path("/Users/x/.claude/projects/-Users-x-Projects-ormah/abc.jsonl")
    assert _is_extractor_transcript(p, "/tmp/ormah-extractor") is False


def test_ingest_session_skips_extractor_transcript(monkeypatch):
    # The chokepoint returns SKIPPED without parsing when the path is the extractor's own.
    engine = MagicMock()
    engine.settings.claude_cli_workdir = "/tmp/ormah-extractor"
    parsed = MagicMock()
    monkeypatch.setattr(sw, "parse_transcript", parsed)
    p = Path("/Users/x/.claude/projects/-tmp-ormah-extractor/abc.jsonl")
    result = sw._ingest_session(engine, p, {}, Path("/Users/x/.claude/projects"), min_turns=1)
    assert result == sw.IngestResult.NO_PROGRESS
    parsed.assert_not_called()  # never even parsed the extractor transcript


def test_fsevents_handler_ignores_extractor_transcript(monkeypatch):
    # on_created for an extractor transcript must NOT schedule an ingest (live path guard).
    engine = MagicMock()
    engine.settings.claude_cli_workdir = "/tmp/ormah-extractor"
    handler = sw.SessionHandler(engine, Path("/Users/x/.claude/projects"),
                                debounce_seconds=0.01, min_turns=1)
    scheduled = []
    monkeypatch.setattr(handler, "_schedule_ingest", lambda p: scheduled.append(p))
    ev = MagicMock(is_directory=False, src_path="/Users/x/.claude/projects/-tmp-ormah-extractor/a.jsonl")
    handler.on_created(ev)
    assert scheduled == []  # extractor transcript never scheduled
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_exclusion.py -v`
Expected: FAIL — helpers don't exist; `_ingest_session` still parses; handler still schedules.

- [ ] **Step 3: Add the helpers**

In `src/ormah/background/session_watcher.py`, right after `_is_subagent_transcript` (line 583):

```python
def _encode_workdir(workdir: str) -> str:
    """Encode a cwd the way Claude Code names its project transcript dir.

    Claude Code keys the dir off the cwd's REAL path, so resolve symlinks first
    (``/tmp`` -> ``/private/tmp`` on macOS) before replacing ``/`` with ``-``.
    """
    real = os.path.realpath(workdir)
    return "-" + real.strip("/").replace("/", "-")


def _is_extractor_transcript(path: Path, workdir: str) -> bool:
    """True for the claude_cli extractor's own transcript (recursion guard).

    The extractor runs `claude -p` with cwd=``workdir``; Claude Code writes its transcript under
    ``~/.claude/projects/<encoded-workdir>/``. Ingesting it would make the extractor extract its
    own output forever.
    """
    return _encode_workdir(workdir) in path.parts
```

- [ ] **Step 4: Guard the chokepoint `_ingest_session`**

At the top of `_ingest_session` (line ~720, before hashing/parsing), add:

```python
    if _is_subagent_transcript(path) or _is_extractor_transcript(
        path, engine.settings.claude_cli_workdir
    ):
        return IngestResult.NO_PROGRESS
```

This covers ALL callers: `_scan_sessions` (catch-up), `reconcile`, and the live `_do_ingest`.
(It also closes the pre-existing gap where `_scan_sessions` did not skip `subagents/`.)

- [ ] **Step 5: Short-circuit the FSEvents handlers**

In `on_created` and `on_modified` (line ~1123), extend the existing subagent check so an extractor
transcript is never even scheduled:

```python
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            path = Path(event.src_path)
            if _is_subagent_transcript(path) or _is_extractor_transcript(
                path, self.engine.settings.claude_cli_workdir
            ):
                return
            self._schedule_ingest(path)
```

Apply the identical change to `on_modified`.

- [ ] **Step 5b: Skip the extractor in the candidate loops (avoid wasted park attempts)**

The chokepoint returns `NO_PROGRESS`, but `reconcile` and `_scan_sessions` still *select* the
extractor's `.jsonl` as a candidate and burn park/retry cycles on it each extraction. Filter it at
selection, next to the existing `subagents` skip:

In `reconcile` (line ~1047), change:
```python
            if _is_subagent_transcript(jsonl_file):
                continue
```
to:
```python
            if _is_subagent_transcript(jsonl_file) or _is_extractor_transcript(
                jsonl_file, self.engine.settings.claude_cli_workdir
            ):
                continue
```

In `_scan_sessions` (line ~883, right after `rel = ...`), add the same guard:
```python
        if _is_subagent_transcript(jsonl_file) or _is_extractor_transcript(
            jsonl_file, engine.settings.claude_cli_workdir
        ):
            continue
```

- [ ] **Step 6: Run tests to verify they pass + no regression**

Run: `.venv/bin/python -m pytest tests/test_background/test_session_watcher_exclusion.py -v`
Expected: PASS (5 tests).
Run: `.venv/bin/python -m pytest tests/ -m 'not integration' -k session_watcher -q` — no regression.

- [ ] **Step 6b: Verify no other ingest path bypasses the chokepoint**

Grep for transcript-ingest callers that might NOT route through `_ingest_session` (e.g. a
`setup.py` backfill or a CLI import command): `grep -rn "ingest_conversation\|_ingest_session\|parse_transcript" src/ormah`. Any path that reads `~/.claude/projects` transcripts directly must
either call the guarded `_ingest_session` or apply `_is_extractor_transcript` itself. If a bypass
exists, add the guard there and note it in the commit; if none, record that in the commit message.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/session_watcher.py \
        tests/test_background/test_session_watcher_exclusion.py
git commit -m "fix(session-watcher): exclude claude_cli extractor transcript at chokepoint + FSEvents"
```

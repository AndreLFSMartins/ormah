# Task 5: Verification, Beta merge, upstream gap list

**Files:** none — runs the gates and integrates.

**Interfaces:**
- Consumes: Tasks 1-4, all committed on the worktree branch.
- Produces: green suite + lint, a verified-isolated smoke run, `local-main` carrying the
  slice, and the recorded upstream gap list for a future contribution plan.

- [ ] **Step 1: Full suite + lint (cite the output)**

```bash
python -m pytest tests/ -v
ruff check src/ tests/
```

Expected: 0 failures beyond the KNOWN environmental set (the global `~/.config/ormah/.env`
leaking `ORMAH_DELETION_ENABLED` into a bare `Settings()` — pre-existing). Paste the tail
(`N passed, M failed`) into the task report. Every failure is explained or fixed, never
waved off. Pay special attention to the two contract tests this slice rewrites
(`test_disabled_returns_empty` L1147, `test_nonexistent_watch_dir` L1181) and to
`tests/test_whisper/test_whisper_out.py`, which loses its client-cursor tests.

- [ ] **Step 2: End-to-end smoke — ISOLATION FIRST**

⚠️ `Settings` (config.py:20) sets `extra: "ignore"`, so a wrong env key is **silently
dropped**. The variable is `ORMAH_MEMORY_DIR` (config.py:29) — there is no
`ORMAH_DATA_DIR`. Using the wrong name points the smoke server at the **live Beta store**
and its background jobs then mutate production. Prove isolation BEFORE starting anything:

```bash
SMOKE=$(mktemp -d); WATCH="$SMOKE/projects"; mkdir -p "$WATCH/proj"
export ORMAH_MEMORY_DIR="$SMOKE/memory" ORMAH_SESSION_WATCHER_DIR="$WATCH" \
       ORMAH_SESSION_WATCHER_ENABLED=false ORMAH_PORT=8788 ORMAH_BACKUP_ENABLED=false
python - <<'PY'
import os
from ormah.config import Settings
s = Settings()
assert str(s.memory_dir) == os.environ["ORMAH_MEMORY_DIR"], f"NOT ISOLATED: {s.memory_dir}"
print("isolation OK:", s.memory_dir)
PY
```

(Verify `ORMAH_BACKUP_ENABLED` exists in `config.py` before relying on it. There is no
`scheduler_enabled` setting — do not invent one; the assert gate above is what makes this
safe.) Only then:

```bash
python -m ormah.main & SMOKE_PID=$!; trap 'kill $SMOKE_PID 2>/dev/null' EXIT
sleep 3
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8788/ingest/nudge \
  -H 'Content-Type: application/json' -d '{"path": "/nonexistent.jsonl"}'   # expect 422
cp <a small jsonl fixture from tests/test_background/> "$WATCH/proj/session.jsonl"
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8788/ingest/nudge \
  -H 'Content-Type: application/json' -d "{\"path\": \"$WATCH/proj/session.jsonl\"}"  # expect 202
```

A 422 alone is weak evidence — it also fires with an empty `session_watches`. So assert
the POSITIVE path too:

1. A job file appears under `$SMOKE/memory/ingest_queue/<root>/pending/` right after the
   202 and BEFORE extraction finishes — that is the durability claim, and the filename
   must carry the boundary. This is the single most important smoke assertion: it is the
   only one that proves the 202 was not a lie.
2. Poll `.session_watcher_state` (~60s) for `end_offset` > 0, and assert the spool's
   `pending/` **and** `running/` both drain to empty. A cursor that advances while a job
   file lingers means completion is not being acknowledged — the failure mode that would
   re-ingest the same slice on every restart.
3. Confirm the reconcile job is **not** registered with the watcher disabled — the spool,
   not a tree walk, is now the recovery path. Check the log for the absence of the
   registration line, and confirm no `rglob` warning fires.
4. Confirm the consent boundary: drop a SECOND transcript into `$WATCH/proj/` that nobody
   nudges, wait a minute, and assert it gets **no** state entry and no spool job.
5. Confirm crash recovery for real: kill the server with `SIGKILL` while a job sits in
   `running/`, restart, and assert the job is claimed and drained. This is the one
   property the unit tests can only simulate.

Kill the server via the trap. NEVER point this at the real `~/.claude/projects`.

- [ ] **Step 3: Merge into the Beta (`local-main`)**

This slice is Beta-only. No upstream branch, no cherry-picks. From the MAIN clone, at merge
time only:

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah status --porcelain
git -C /Users/andre/Documents/GitHub/Tools/ormah merge <worktree-branch>   # already on local-main; do NOT switch branches
launchctl kickstart -k gui/501/com.ormah.server.dev
curl -s http://localhost:8787/admin/health    # NOT /health — that hits the SPA catch-all
```

Then run the Beta Rollout steps in `00-overview.md`.

- [ ] **Step 4: Record the upstream gap list (input for a FUTURE, separate plan)**

Do not open an upstream PR from this work. Append the verified reasons + re-derivation
checklist to the ADR (Step 5) so the future contributor starts from facts:

```bash
git fetch upstream
echo "upstream session_watcher: $(git show upstream/main:src/ormah/background/session_watcher.py | wc -l) lines"
echo "local    session_watcher: $(wc -l < src/ormah/background/session_watcher.py) lines"
for sym in flush_bytes stop_event startup_thread cancel_pending_timers _drain_handlers; do
  git show upstream/main:src/ormah/background/session_watcher.py | grep -q "$sym" \
    && echo "PRESENT upstream: $sym" || echo "ABSENT upstream:  $sym"
done
```

Expected (verified 2026-07-21): all ABSENT; upstream still calls `_scan_sessions`
synchronously in `start_session_watcher` (upstream L1147). A future upstream PR must
re-derive the nudge endpoint + always-on worker + pure-nudge hook against those
primitives, NOT port these diffs.

- [ ] **Step 5: Review + close the loop**

- Run `/council-pr` on the worktree branch before merging.
- Update `docs/adr/0004-async-ingest-nudge-server-cursor.md`: record that the ADR is being
  delivered in three slices, that slice 1 is implemented, and the amendments that changed
  the ADR's own text — (i) the periodic reconcile runs for every install but is
  **recovery-only** when `session_watcher_enabled=False` (consent boundary); (ii) a nudge
  carries durable boundary semantics (a spool job whose filename holds the accepted byte
  offset) and bypasses the debounce;
  (iii) the hook keeps a client-side outbox, because "the client never waits" must not
  mean "the client silently drops the event"; (iv) upstream contribution is deferred, with
  the gap list from Step 4.
- Report: suite output, smoke evidence, and the one-delta re-ingest expectation on the
  first Beta run.
- **Then start slice 2** (`../2026-07-21-adr-0004-slice2-bounded-shutdown/`) — the
  always-on worker makes the unbounded shutdown wait everyone's problem, not just
  watcher-enabled installs.

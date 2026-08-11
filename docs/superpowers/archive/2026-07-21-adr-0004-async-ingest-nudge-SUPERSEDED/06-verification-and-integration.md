# Task 6: Verification, provenance split, branch/PR handoff

**Files:**
- No new source files. Runs the full gates and routes commits per provenance.

**Interfaces:**
- Consumes: everything from Tasks 1-5 (all committed on the working branch).
- Produces: green full suite + lint, a contribution branch on `fork` ready for
  `/council-pr`, and (if needed) a separate fork-only commit for `local-main`.

- [ ] **Step 1: Full suite + lint (cite output)**

```bash
python -m pytest tests/ -v
ruff check src/ tests/
```

Expected: 0 failures beyond the KNOWN environmental set (global `~/.config/ormah/.env`
leaking `ORMAH_DELETION_ENABLED` into bare `Settings()` — pre-existing, not this change).
Paste the tail (`N passed, M failed`) into the task report; every failure must be
explained or fixed, never waved off.

- [ ] **Step 2: End-to-end smoke — ISOLATION FIRST (codex R4: critical)**

⚠️ `Settings` (config.py:20) sets `extra: "ignore"`, so a wrong env key is **silently
dropped**. The variable is `ORMAH_MEMORY_DIR` (config.py:29) — there is no
`ORMAH_DATA_DIR`. Using the wrong name points the smoke server at
`~/.local/share/ormah/memory`, i.e. the **live Beta store**, and its background jobs then
mutate production. Prove isolation BEFORE starting anything:

```bash
SMOKE=$(mktemp -d); WATCH="$SMOKE/projects"; mkdir -p "$WATCH/proj"
export ORMAH_MEMORY_DIR="$SMOKE/memory" ORMAH_SESSION_WATCHER_DIR="$WATCH" \
       ORMAH_SESSION_WATCHER_ENABLED=false ORMAH_PORT=8788 \
       ORMAH_BACKUP_ENABLED=false
# GATE: refuse to launch unless the resolved settings really point at the temp dir
python - <<'PY'
import os, sys
from ormah.config import Settings
s = Settings()
assert str(s.memory_dir) == os.environ["ORMAH_MEMORY_DIR"], f"NOT ISOLATED: {s.memory_dir}"
print("isolation OK:", s.memory_dir)
PY
```

(council R5: there is no `scheduler_enabled` setting — an invented flag is silently
dropped by `extra: "ignore"`, so do not pretend it disables anything. Verify
`ORMAH_BACKUP_ENABLED` exists in `config.py` before relying on it; the assert gate above
is what actually makes this safe.) Only then:

```bash
python -m ormah.main & SMOKE_PID=$!; trap 'kill $SMOKE_PID 2>/dev/null' EXIT
sleep 3
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8788/ingest/nudge \
  -H 'Content-Type: application/json' -d '{"path": "/nonexistent.jsonl"}'   # expect 422
cp <a small jsonl fixture from tests/test_background/> "$WATCH/proj/session.jsonl"
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8788/ingest/nudge \
  -H 'Content-Type: application/json' -d "{\"path\": \"$WATCH/proj/session.jsonl\"}"  # expect 202
```

Also assert the periodic reconcile job REALLY registered with the watcher disabled
(council R6 — `register_session_reconcile_job` returns early on an empty watches list, and
only runs if the scheduler started):

```bash
curl -s http://127.0.0.1:8788/admin/health | python3 -m json.tool | grep -i reconcile || \
  grep -i "reconcile" <server log>   # must show the job registered, not the degraded warning
```

Then poll `$WATCH/.session_watcher_state` (~60s) for the entry's `end_offset` > 0 — the
POSITIVE proof (council R1: a 422 alone also fires with an empty `session_watches`). With
no provider configured, assert instead that the schedule/in-flight log line fired. Kill the
server via the trap. NEVER point this at the real `~/.claude/projects`.

- [ ] **Step 3: Merge into the Beta (`local-main`)**

This plan is Beta-only (see `00-overview.md` → Delivery). No upstream branch, no
cherry-picks. From the MAIN clone, at merge time only:

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah status --porcelain   # must be clean of surprises
git -C /Users/andre/Documents/GitHub/Tools/ormah checkout local-main  # already there; do NOT switch to any other branch
git -C /Users/andre/Documents/GitHub/Tools/ormah merge <worktree-branch>
launchctl kickstart -k gui/501/com.ormah.server.dev
curl -s http://localhost:8787/admin/health   # NOT /health — that hits the SPA catch-all
```

Then run the Beta Rollout steps in `00-overview.md` (timeout knob, `ormah setup`).

- [ ] **Step 4: Record the upstream gap list (input for a FUTURE, separate plan)**

Do not open an upstream PR from this work. Instead append to the ADR (Step 6) the verified
reasons and the re-derivation checklist, so the future contributor starts from facts:

```bash
git fetch upstream
echo "upstream session_watcher: $(git show upstream/main:src/ormah/background/session_watcher.py | wc -l) lines"
echo "local    session_watcher: $(wc -l < src/ormah/background/session_watcher.py) lines"
for sym in flush_bytes stop_event startup_thread cancel_pending_timers _drain_handlers \
           ingest_llm_generate _cached_ingest_adapter; do
  git show upstream/main:src/ormah/background/session_watcher.py 2>/dev/null | grep -q "$sym" \
    || git show upstream/main:src/ormah/background/llm_client.py 2>/dev/null | grep -q "$sym" \
    && echo "PRESENT upstream: $sym" || echo "ABSENT upstream:  $sym"
done
```

Expected (verified 2026-07-21): all of `flush_bytes`, `stop_event`, `startup_thread`,
`cancel_pending_timers`, `_drain_handlers`, `ingest_llm_generate`, `_cached_ingest_adapter`
ABSENT upstream; upstream still calls `_scan_sessions` synchronously in
`start_session_watcher` (upstream L1147). A future upstream PR must re-derive the
nudge endpoint + always-on worker + pure-nudge hook against those primitives, NOT port
these diffs.

- [ ] **Step 5: Review**

Run `/council-pr` on the worktree branch before merging (replaces requesting-code-review).

- [ ] **Step 6: Close the loop**

- Update `docs/adr/0004-async-ingest-nudge-server-cursor.md`: status → `implemented`, and
  record the council amendments that CHANGED the ADR's own text — (i) periodic reconcile
  runs for every install, not only with the watcher enabled; (ii) a timeout no longer
  quarantines on lateness alone (health gate + shrink-to-floor first); (iii) shutdown
  cancels in-flight extractions; (iv) the timeout classification is Beta-only until an
  ingest-provider seam exists upstream.
- Report: suite output, PR URL, and the one-delta re-ingest expectation on first Beta run.

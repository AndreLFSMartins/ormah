# Task 3: Verification and Beta merge

**Files:** none — runs the gates and integrates.

**Interfaces:**
- Consumes: Tasks 1-2, committed on the worktree branch.
- Produces: green suite + lint, **measured restart timing** (the acceptance evidence for
  this slice), and `local-main` carrying the change.

- [ ] **Step 1: Full suite + lint (cite the output)**

```bash
python -m pytest tests/ -v
ruff check src/ tests/
```

Expected: 0 failures beyond the KNOWN environmental set (global `~/.config/ormah/.env`
leaking into a bare `Settings()`). Paste the tail (`N passed, M failed`). Pay attention to
`tests/test_background/test_claude_cli_adapter.py`, whose every `subprocess.run` patch site
migrated to the fake `Popen` — a test that silently starts invoking the real `claude`
binary looks like a pass while costing quota and minutes.

- [ ] **Step 2: Measure the actual win (this is the acceptance criterion)**

A green suite does not prove the restart got faster. Measure it on an isolated server —
**never** the live Beta store (`Settings` uses `extra: "ignore"`, so a wrong env key is
dropped silently and the process opens the real store; the variable is `ORMAH_MEMORY_DIR`):

```bash
SMOKE=$(mktemp -d)
export ORMAH_MEMORY_DIR="$SMOKE/memory" ORMAH_PORT=8788 ORMAH_BACKUP_ENABLED=false
python -c "import os; from ormah.config import Settings; s=Settings(); assert str(s.memory_dir)==os.environ['ORMAH_MEMORY_DIR']; print('isolation OK')"
```

Start it, drive one long extraction (a fat transcript, or a stub provider that sleeps well
past the drain), then stop the process and time it:

```bash
time kill -TERM $SMOKE_PID   # or: time (launchctl kickstart -k gui/501/com.ormah.server.dev)
```

Expected: shutdown completes in **seconds**, not up to `claude_cli_timeout_seconds`. Record
the before/after numbers in the task report — if you cannot show the delta, this slice is
not verified, regardless of the suite.

Also confirm the two failure modes the review flagged:

1. **The rollback path is bounded AND owns every started root** (council HIGH-A/HIGH-B).
   Two checks: (a) a second watch root whose Observer fails while the FIRST root is
   mid-extraction must not wait out the budget; (b) the root whose OWN Observer fails, while
   ITS handler is mid-extraction on a recovered spool job, must still be cancelled + joined
   (the provisional-`SessionWatch`-before-`observer.start()` fix) — no engine access after
   rollback. And (c) after a rollback the process keeps serving, so a maintenance
   `llm_generate` must still succeed (adapters re-armed). Regressions:
   `test_startup_rollback_drains_failing_roots_own_inflight_extraction`,
   `test_startup_rollback_rearms_adapters_and_serves`.
2. **A second lifespan still works.** Consecutive `async with main.lifespan(app)` blocks —
   generation must succeed in the second one (regression:
   `test_second_lifespan_can_generate_after_a_cancelled_first`). This is the poisoned-cache
   failure: it looks fine at shutdown and breaks every later ingest.
3. **🔴 A cancel never burns the per-slice cap (merged-slice-1 hazard).** Confirm the
   Task-2 engine mapping: `MAX_EXTRACT_FAILURES + 1` cancellations at the same byte offset
   must leave the cursor un-advanced and `skipped_slices` empty — otherwise repeated
   restarts silently drop a healthy slice (regressions:
   `test_cancelled_extraction_maps_to_call_failed_not_slice_failure`,
   `test_repeated_cancellations_never_skip_a_slice`). Without this, the slice's own
   durability claim is false.

- [ ] **Step 3: Merge into the Beta (`local-main`)**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah status --porcelain
git -C /Users/andre/Documents/GitHub/Tools/ormah merge <worktree-branch>   # already on local-main; do NOT switch branches
launchctl kickstart -k gui/501/com.ormah.server.dev
curl -s http://localhost:8787/admin/health    # NOT /health — SPA catch-all returns HTML 200
```

Then restart the live Beta once while an extraction is running and confirm the same
seconds-not-minutes behaviour in production conditions.

- [ ] **Step 4: Review + close the loop**

- Run `/council-pr` on the worktree branch before merging.
- Update `docs/adr/0004-async-ingest-nudge-server-cursor.md`: record that shutdown now
  cancels in-flight extractions (a killed extraction never advances the cursor, so the
  startup drain re-ingests the slice — durability still comes from the cursor, not a job
  table), that cancellation is a distinct signal from a timeout, that a cancel is mapped to
  `EXTRACT_ERR_CALL_FAILED` so it can **never** be counted toward the per-slice failure cap
  slice 1 introduced (H1 — a cancel must not burn a healthy slice), and that a late-built
  adapter is closed **deterministically** by the `_stop_and_drain` cancel-and-join fence loop
  (council HIGH-C — no longer a documented residual). Record instead the accepted narrow
  bound: `_drain_forever` runs one job at a time per handler, so the fence terminates once
  each handler's single in-flight job is cancelled.
- Report: suite output, the measured restart timing, and the two regression results.
- **Then decide on slice 3** (`../2026-07-21-adr-0004-slice3-timeout-quarantine/`) — it
  needs its own ADR because it is the only part of ADR-0004 that can drop real data.

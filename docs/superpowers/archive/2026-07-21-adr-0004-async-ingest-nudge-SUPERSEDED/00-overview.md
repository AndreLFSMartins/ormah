# ADR-0004 Async Ingest (Nudge + Server Cursor) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Each task lives in its own file (`0N-*.md`); steps use checkbox syntax.

**Goal:** Implement ADR-0004 (`docs/adr/0004-async-ingest-nudge-server-cursor.md`): the hook
becomes a pure nudge (`POST /ingest/nudge` → 202), the server owns the single ingest cursor
(the watcher's `.session_watcher_state`) and advances it on job completion; the watcher's
handler becomes an always-on Ingest worker; an extraction timeout stops re-burning quota
without ever quarantining data a provider outage merely delayed.

**Architecture:** Bottom-up: (1) timeout signal at the adapter boundary, (2) its
classification in engine + watcher cap, (3) always-on worker extraction, (4) nudge endpoint
on top of the worker, (5) hook rewrite to nudge + manifest simplification, (7) bounded
shutdown, (6) verification + integration routing. Chains 1-2 and 3-5 are independent.

**Tech Stack:** Python 3.11, FastAPI, pytest (`asyncio_mode=auto`), httpx, watchdog.

## Delivery: **Beta-first**, upstream contribution deferred (council R5, decisive)

Two independently verified facts kill the "branch from `upstream/main` and cherry-pick"
recipe for this change:

1. **No ingest-provider seam upstream.** `llm_client.py` there exposes only `llm_generate`
   (upstream L76) and `memory_engine._extract_memories_llm` calls it directly (upstream
   L2316-2320) — no `ingest_llm_generate`, no ingest adapter cache, no `claude_cli`
   adapter. The timeout classification would ship as inert code.
2. **The watcher upstream is ~222 lines behind** (1203 vs 1425 local). It still runs
   `_scan_sessions` synchronously at bind (upstream L1147) and has **none** of the
   primitives Tasks 3/7 build on: `flush_bytes`, `stop_event`, `startup_thread`,
   `cancel_pending_timers`, `_drain_handlers`, async startup reconcile.

So every task in this plan targets the **Beta (`local-main`)**, implemented in a worktree
cut from `local-main` and merged back per FORK-WORKFLOW Recipe B's spirit. **Nothing here
is cherry-picked upstream.**

**Upstream contribution is deliberately OUT OF SCOPE of this plan.** After this lands and
runs on the Beta, open a *separate* effort that re-derives the provider-agnostic parts
(nudge endpoint, always-on worker, pure-nudge hook, stop ordering) directly against a
pinned `upstream/main` SHA — writing the code for the primitives that exist THERE, not
porting these diffs. Task 6 records the exact gap list for that future plan. Attempting it
inside this plan would mean either shipping broken cherry-picks or porting 222 lines of
unrelated watcher history.

## Global Constraints

- **Never checkout a branch in `Tools/ormah`** — it is the live Beta (whisper hooks break).
  All work in a git worktree; run tests with that worktree's venv (`python -m pytest`).
- **FORK-WORKFLOW.md** still governs any FUTURE upstream contribution (branch from
  `upstream/main`, push to `fork`, never `upstream`) — but this plan makes no such branch.
  Work happens in a worktree cut from `local-main`; review via `/council-pr` against it.
- **Sequencing:** PR #153 (`fix/leading-orphan-progress-guard`) edits `cmd_whisper_store`,
  which Task 5 largely deletes. Since this plan targets the Beta and #153's content is
  already merged into `local-main` (66405d9), just be aware that a later upstream sync may
  conflict there — resolve by taking the maintainer's version (Recipe C).
- **Out of scope:** worker concurrency (issue #150 — worker stays serial); durable job
  table (rejected in the ADR); any whisper-inject behavior.
- **Test env caveats:** default pytest run excludes `integration` marker. `tests/test_setup*.py`
  can touch the real `~/.claude` — verify survival by parsing JSON, never `grep -i ormah`.
  `~/.config/ormah/.env` leaks into bare `Settings()` (known, environmental — not a regression).
- **⚠️ Any throwaway server MUST set `ORMAH_MEMORY_DIR`** — `Settings` (config.py:20) uses
  `extra: "ignore"`, so a wrong key like `ORMAH_DATA_DIR` is silently dropped and the
  process opens the **live** store (`~/.local/share/ormah/memory`). Always assert the
  resolved `Settings().memory_dir` equals the temp dir before starting anything.
- **Timeout knob:** the extraction budget is the existing `claude_cli_timeout_seconds`
  (`src/ormah/config.py:66`, `.env`-overridable). Code default unchanged.
- Lint: `ruff check src/ tests/` (line-length 100, py311). Commit style: `feat(scope): ...`.

## Council amendments (R1-R5, 2026-07-21) — all findings accepted

- **(a) Error seam** `src/ormah/background/llm_errors.py` holds `LlmTimeoutError` and
  `LlmCancelledError`; its only raiser is the fork-only `claude_cli` adapter.
- **(b) Timeout never quarantines on lateness alone.** A timeout counts toward the
  per-slice cap only when BOTH hold: provider-health evidence (another slice succeeded
  since this slice's previous timeout) AND the slice has already been **shrunk to the
  floor** (`max_bytes` halved down to the floor, `min(MIN_SLICE_BYTES, flush_bytes)` — a
  configured `flush_bytes` smaller than the constant is never raised past it). A big-but-valid slice gets
  smaller until it fits instead of being dropped; an outage never consumes the cap.
- **(c) Cancellation is not a timeout.** Shutdown cancel raises `LlmCancelledError` →
  `EXTRACT_ERR_CALL_FAILED` → uncapped TRANSIENT, so restarts can never quarantine a
  healthy slice. The engine catches it BEFORE any broad handler.
- **(d) Periodic reconcile runs for EVERY install, but its SCOPE depends on the flag**
  (council R7 — this is a consent boundary, not a detail). Today
  `session_watcher_enabled=False` means "do not auto-ingest my transcripts". A reconcile
  that scans for *never-seen* files would silently start ingesting them on upgrade — and
  ship them to a remote provider — for users who opted out. So:
  - flag ON  → reconcile behaves as today: discovers never-seen files within the lookback
    AND resumes any cursor not at EOF.
  - flag OFF → reconcile is **recovery-only**: it processes ONLY transcripts that already
    have a state entry (a cursor behind EOF, or a `boundary_pending` nudge the user's own
    hook sent). It never discovers a file nobody asked for.
  Either way the nudge path works, because a nudge creates the entry. Known degraded mode:
  the job rides the APScheduler — if it fails to start (`main.py:210-211`) periodic
  recovery waits for a restart; Task 3 logs a loud WARNING. ADR amendment at close (Task 6).
- **(e) Configured-but-absent watch dirs still produce a handler** (Task 3), and the hook
  keeps its legacy cursor until it sees a `202` (Task 5) — otherwise a first-run nudge is
  lost forever.
- **(g) A nudge carries session-boundary semantics** (council R5): the endpoint persists a
  pending marker BEFORE answering 202 (so a crash is recoverable even outside the reconcile
  lookback) and forces a flush past the idle/min-turn gates — otherwise a small SessionEnd
  delta waits up to `idle_threshold` (600s), defeating the ADR's purpose.
- **(f) Declared limitations:**
  - only the `claude_cli` adapter raises the timeout/cancel signals; ollama/litellm keep
    `None` → `EXTRACT_ERR_CALL_FAILED` → TRANSIENT, and their shutdown is bounded only by
    their own (short) HTTP timeouts;
  - **shrink cannot rescue a single oversized turn** (council R7): the parser deliberately
    commits a first turn that exceeds `max_bytes`, because there is no safe conversational
    boundary inside it. So a huge paste in ONE turn does not get smaller by halving, and
    if it keeps timing out while other slices succeed it is still quarantined (recorded
    replayably in `skipped_slices` with an ERROR log). Task 2 must detect this — when a
    shrink level produces the SAME `payload_offset`, stop shrinking and say so in the log
    instead of burning levels that cannot help.

## Task Map (execution order 1 → 2 → 3 → 4 → 5 → 7 → 6)

All tasks land on `local-main` (Beta) — there is no upstream/fork commit split in this plan.

| # | File | Delivers | Depends on |
|---|------|----------|------------|
| 1 | `01-timeout-signal.md` | `LlmTimeoutError` / `LlmCancelledError` seam; claude_cli raises on timeout | — |
| 2 | `02-timeout-classification.md` | `EXTRACT_ERR_TIMEOUT`; shrink-then-cap with health gate | 1 |
| 3 | `03-always-on-worker.md` | Handler + startup drain always on; Observer optional; one `app.state` attribute | — |
| 4 | `04-nudge-endpoint.md` | `POST /ingest/nudge {path}` → 202 with a durable pending marker + boundary flush | 3 |
| 5 | `05-hook-pure-nudge.md` | `cmd_whisper_store` = nudge only; client cursor retired safely | 4 |
| 7 | `07-shutdown-cancellation.md` | Bounded shutdown: cancel live extractions before every join | 1, 3 |
| 6 | `06-verification-and-integration.md` | Suite green, isolated smoke, Beta merge, upstream gap list | all |

## Key Anchors (verified 2026-07-21 on local-main @ 66405d9)

- Hook handler: `src/ormah/adapters/cli_adapter.py` — `cmd_whisper_store` L423-519, cursor
  machinery L404-420, store client/timeout L387-401, nudge counters ~L298-301.
- Endpoint: `src/ormah/api/routes_ingest.py` (only `/conversation` L19, `/file` L52 exist).
- Worker: `src/ormah/background/session_watcher.py` — `_ingest_session` L728-995 (parse with
  `max_bytes=flush_bytes` L776), classification L942-954, `_record_extract_failure` L856-910
  (writes replayable `skipped_slices` start/end/hash L871-877), `SessionHandler` L1051
  (guard `_ingesting` L1076, `_schedule_ingest` L1084), `reconcile` L1161, `SessionWatch`
  L1279, `_run_startup_reconcile` L1287, `start_session_watcher` L1299 (enabled-gate L1308,
  missing-dir `return []` L1311-1314), `stop_session_watcher` L1374 (⚠️ joins
  `startup_thread` L1388-1390 BEFORE `_drain_handlers` L1391), `run_session_reconcile` L1398.
- Adapter (fork-only): `src/ormah/background/llm/claude_cli_adapter.py` L104-172.
- LLM boundary (Beta): `llm_client.py` — `ingest_llm_generate` L101 (sole caller
  `memory_engine._extract_memories_llm` L2842, None-branch L2868-2886), `llm_generate` L119.
  **Upstream differs**: only `llm_generate` (L76), engine calls it directly (L2316-2320).
- Lifespan: `src/ormah/main.py` L186; watcher start L244-246, reconcile job L248-253,
  shutdown L282-283 (reads `app.state.session_watcher_observers` today).
- Config: `src/ormah/config.py` L20 (`extra: "ignore"`), L29 (`memory_dir`), L66
  (`claude_cli_timeout_seconds`), L92-103 (`session_watcher_*`).

## Beta Rollout (after merge to local-main — operator steps, not code)

1. Size `ORMAH_CLAUDE_CLI_TIMEOUT_SECONDS` in `~/.config/ormah/.env` to the measured worst
   case (~2400s; observed max 33.6 min). `.env` changes need
   `launchctl kickstart -k gui/501/com.ormah.server.dev`.
2. `ormah setup` (or plugin update) to rewrite hook manifests.
3. First run after upgrade: the server cursor may sit behind the retired client cursor →
   one delta re-ingests once; dedup heals (ADR consequence, expected).

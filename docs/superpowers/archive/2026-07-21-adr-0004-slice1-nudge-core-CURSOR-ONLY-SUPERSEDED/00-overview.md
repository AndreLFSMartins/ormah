# ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the cursor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans. Each task is its own file; steps use checkboxes.

**Goal:** Deliver what ADR-0004 actually asks for: the hook becomes a pure nudge
(`POST /ingest/nudge` → 202), the server owns the single ingest cursor
(`.session_watcher_state`) and advances it on job completion. This kills the
freeze-and-re-post engine (the "same 1.14M-char payload posted 5×") and the two-cursor
overlap, without touching extraction-failure policy.

**Architecture:** (1) the watcher's handler becomes an always-on Ingest worker with the
Observer as an optional producer; (2) a nudge endpoint feeds that worker with durable,
session-boundary semantics; (3) the hook is reduced to a trigger with a client-side outbox.

**Tech Stack:** Python 3.11, FastAPI, pytest (`asyncio_mode=auto`), httpx, watchdog.

## Slicing (decided 2026-07-21 after 8 council rounds)

ADR-0004 was split into three independently shippable plans because the review kept
finding defects in the failure-policy half while the core stayed stable:

| Slice | Delivers | Status |
|-------|----------|--------|
| **1 (this plan)** | Nudge core: always-on worker, `/ingest/nudge`, pure-nudge hook | ready |
| 2 — `../2026-07-21-adr-0004-slice2-bounded-shutdown/` | Cancel in-flight extractions on shutdown | ships right after slice 1 |
| 3 — `../2026-07-21-adr-0004-slice3-timeout-quarantine/` | Timeout → health-gated, shrink-first quarantine | needs its own ADR first |

**Ordering matters.** Slice 1 makes the ingest worker always-on, which extends an existing
risk: shutdown waits (uncapped, by design — abandoning an in-flight ingest re-opens a
use-after-close window) for a running extraction that can last as long as
`claude_cli_timeout_seconds`. Today that only bites installs with the watcher enabled;
after slice 1 it bites every install. **Known risk, accepted for slice 1, closed by slice 2**
— do not let slice 2 drift. Operational mitigation while it is open: keep
`ORMAH_CLAUDE_CLI_TIMEOUT_SECONDS` at a value you are willing to wait out on restart.

## Global Constraints

- **Never checkout a branch in `Tools/ormah`** — it is the live Beta (whisper hooks break).
  Work in a git worktree cut from `local-main`; run tests with that worktree's venv.
- **Beta-only.** Verified 2026-07-21: `upstream/main`'s `session_watcher.py` is ~222 lines
  behind (1203 vs 1425), still calls `_scan_sessions` synchronously at bind (upstream
  L1147), and has none of `flush_bytes`, `stop_event`, `startup_thread`,
  `cancel_pending_timers`, `_drain_handlers`. These diffs cannot be cherry-picked upstream.
  A future upstream contribution must be re-derived against a pinned upstream SHA — out of
  scope here; the gap list is recorded in Task 4.
- **⚠️ Any throwaway server MUST set `ORMAH_MEMORY_DIR`** — `Settings` (config.py:20) uses
  `extra: "ignore"`, so a wrong key (e.g. `ORMAH_DATA_DIR`) is silently dropped and the
  process opens the **live** store. Assert the resolved `Settings().memory_dir` before start.
- **Out of scope:** worker concurrency (issue #150 — worker stays serial); durable job
  table (rejected in the ADR); extraction-failure/quarantine policy (slice 3); shutdown
  cancellation (slice 2); any whisper-inject behavior.
- **Test env caveats:** default pytest run excludes `integration`. `tests/test_setup*.py`
  can touch the real `~/.claude` — verify survival by parsing JSON, never `grep -i ormah`.
  `~/.config/ormah/.env` leaks into bare `Settings()` (known, environmental).
- Lint: `ruff check src/ tests/` (line-length 100, py311). Commits: `feat(scope): ...`.

## Council amendments carried into this slice (R1-R9, all findings accepted)

- **Consent boundary (R7/R8/R9).** `session_watcher_enabled=False` means "do not
  auto-ingest my transcripts". The periodic reconcile runs for every install, but its SCOPE
  follows the flag: ON → discovers never-seen files within the lookback; OFF →
  **intent-only**, processing exclusively entries whose cursor is still short of an explicit
  `boundary_target` (a nudge the user's own hook sent). "Any transcript with a state entry" is NOT enough
  (council R9): once a file has been nudged once — or was tracked before the flag was
  turned off — every later append leaves its cursor behind EOF, so reconcile would keep
  ingesting un-nudged growth and shipping it to a remote extractor. When disabled the sweep
  also stops walking the tree (`rglob`, L1188) and iterates `state.keys()` instead, which
  makes its cost proportional to pending work rather than to the size of the projects dir.
  Wire the scope on all three reconcile call sites — a `discover=True` default re-opens the
  hole on the path that runs first.
- **One `app.state` attribute (R1).** Startup and shutdown must both use
  `app.state.session_watches`; today shutdown reads `session_watcher_observers`
  (`main.py:282-283`), so leaving it would mean `stop_session_watcher` never runs →
  use-after-close on the DB.
- **Configured-but-absent watch roots still get a handler (R4/R5)** — `_session_watch_dirs`
  filters on `exists()` (L679), so an absent `~/.claude/projects` would strand every nudge
  behind a permanent 422.
- **The nudge is durable and immediate (R5/R6/R9).** The endpoint persists
  `boundary_target` (the EOF at acceptance) into the state entry *before* answering 202 (never overwriting a real
  cursor), and schedules with zero debounce — the default 60s debounce exists for files
  still being written, which an ended session is not. `force_flush` is re-derived from that
  durable flag on every attempt. The flag is a **target, not a one-shot**: clearing it on
  the first successful advance would drop `force_flush` mid-drain and leave the final
  sub-cap tail waiting out the 600s idle gate, so it survives capped batches and is cleared
  only on a return that proves nothing closed remains. Because that promise is only as
  good as the file it lives in, this slice also makes `_save_state` (L700-703) atomic — a
  torn `write_text` currently discards every cursor in the watch dir.
- **The hook keeps an outbox (R6/R7/R8/R9).** Without it, a server outage longer than the
  reconcile lookback loses the only SessionEnd signal forever. Four rules, each from a
  real failure the review found: (1) **queue first, then send** — network work before the
  event is durable can burn the hook budget and lose the boundary that just happened;
  (2) **budget the drain** by wall clock and request count, well under the 30s hook
  timeout; (3) remove an entry only on **its own** 202, never batch-wide; (4) take every
  lock on a **stable lock file**, never on the outbox inode — `flock` locks inodes, so a
  drain that `os.replace`s the outbox would let a blocked appender write into an unlinked
  file. Capped by age (~30 days), not by count. Declared limitation: `fcntl` is POSIX-only;
  on Windows the locking no-ops (documented, never fatal).
- **The legacy client cursor is retired only after a 202** — deleting it on a 404/422 or
  while offline would discard the only record of what was already ingested.

## Task Map

| # | File | Delivers | Depends on |
|---|------|----------|------------|
| 1 | `01-always-on-worker.md` | Handler + startup drain always on; Observer optional; consent-scoped reconcile; one `app.state` attribute | — |
| 2 | `02-nudge-endpoint.md` | `POST /ingest/nudge` → 202 with durable `boundary_target` + zero-debounce boundary flush | 1 |
| 3 | `03-hook-pure-nudge.md` | `cmd_whisper_store` = trigger only; client cursor retired safely; outbox | 2 |
| 4 | `04-verification.md` | Suite green, isolated smoke, Beta merge, upstream gap list | 1-3 |

## Key Anchors (verified 2026-07-21 on local-main @ 66405d9)

- Worker: `src/ormah/background/session_watcher.py` — `_ingest_session` L728-995 (parse with
  `max_bytes=flush_bytes` L776; already-consumed early return L770-771; success entry
  rebuild L970-981), `_session_watch_dirs` L669-681 (⚠️ `exists()` filter L679),
  `_commit_state` L706-714, `SessionHandler` L1051 (guard `_ingesting` L1076,
  `_schedule_ingest` L1084, `_do_ingest` L1115-1147), `reconcile` L1161 (never-seen branch
  ~L1042 mirror of `_scan_sessions`), `SessionWatch` L1279, `_run_startup_reconcile` L1287,
  `start_session_watcher` L1299 (enabled-gate L1308, missing-dir `return []` L1311-1314,
  rollback L1339-1354), `stop_session_watcher` L1374, `run_session_reconcile` L1398.
- Endpoint: `src/ormah/api/routes_ingest.py` (only `/conversation` L19, `/file` L52 exist).
- Hook: `src/ormah/adapters/cli_adapter.py` — `cmd_whisper_store` L423-519, cursor machinery
  L404-420, store client/timeout L387-401, nudge counters ~L298-301.
- Lifespan: `src/ormah/main.py` L186; watcher start L244-246, reconcile job L248-253,
  shutdown L282-283 (reads `app.state.session_watcher_observers` today).
- Config: `src/ormah/config.py` L20 (`extra: "ignore"`), L29 (`memory_dir`), L92-103
  (`session_watcher_*`, incl. `_debounce_seconds=60`, `_reconcile_max_per_tick=50`).
- Tests: `tests/test_background/test_session_watcher.py` — fixtures `_make_jsonl` L51,
  `_mark_idle` L68, `_LLM_PATCH` L31, `_LLM_RESPONSE` L41; contract tests that MUST be
  rewritten: `test_disabled_returns_empty` L1147, `test_nonexistent_watch_dir` L1181.
  Lifespan: `tests/test_main_lifespan_shutdown.py` (fake-module fixture ~L265-290,
  double-lifespan pattern ~L292).

## Beta Rollout (operator steps, after merge to local-main)

1. `ormah setup` (or plugin update) to rewrite the hook manifests (timeout 300 → 30).
2. `launchctl kickstart -k gui/501/com.ormah.server.dev`; health is `GET /admin/health`
   (NOT `/health` — that hits the SPA catch-all and returns HTML with 200).
3. First run after upgrade: the server cursor may sit behind the retired client cursor →
   one delta re-ingests once; dedup heals it (ADR consequence, expected).

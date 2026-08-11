# ADR-0004 Slice 1 — Nudge core: the client stops waiting, the server owns the queue

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans. Each task is its own file; steps use checkboxes.

**Goal:** Deliver what ADR-0004 asks for: the hook becomes a pure nudge
(`POST /ingest/nudge` → 202), the server owns ingestion and advances the cursor on job
completion. This kills the freeze-and-re-post engine (the "same 1.14M-char payload posted
5×") and the two-cursor overlap, without touching extraction-failure policy.

**Architecture:** (1) a **durable file spool** is the queue; (2) the watcher's handler
becomes an always-on Ingest worker draining that spool, with the Observer as an optional
producer; (3) the endpoint enqueues and returns; (4) the hook is reduced to a trigger with
a client-side outbox.

**Tech Stack:** Python 3.11, FastAPI, pytest (`asyncio_mode=auto`), httpx, watchdog.

## ⚠️ Rewritten 2026-07-22 — read the ADR amendment first

This plan previously stored boundary + consent + acknowledgement semantics **inside the
Cursor state file**, because ADR-0004 rejected a durable job table. Eight council rounds
found a race per added field. A prototype then measured the alternatives and the ADR was
amended: **`docs/adr/0004-async-ingest-nudge-server-cursor.md` → "Amendment 2026-07-22 —
the durable queue is a directory spool"**. Read it before implementing; it carries the
numbers this plan cites.

The superseded cursor-only version is preserved verbatim at
`../../archive/2026-07-21-adr-0004-slice1-nudge-core-CURSOR-ONLY-SUPERSEDED/` — consult it
only to understand *why* a rule exists, never to reintroduce one.

**The one-line summary of the change:** the boundary is no longer a field to keep alive and
clear correctly; it is a file whose existence *is* the pending work and whose deletion *is*
the acknowledgement.

## Slicing (decided 2026-07-21 after 8 council rounds)

| Slice | Delivers | Status |
|-------|----------|--------|
| **1 (this plan)** | Spool, always-on worker, `/ingest/nudge`, pure-nudge hook | ready |
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
  scope here; the gap list is recorded in Task 5.
- **⚠️ Any throwaway server MUST set `ORMAH_MEMORY_DIR`** — `Settings` (config.py:20) uses
  `extra: "ignore"`, so a wrong key (e.g. `ORMAH_DATA_DIR`) is silently dropped and the
  process opens the **live** store. Assert the resolved `Settings().memory_dir` before start.
- **The spool lives under `memory_dir`, never `/tmp`** — `os.rename` is atomic per
  filesystem, and the staging dir must share it.
- **Out of scope:** worker concurrency (issue #150 — worker stays serial, and Task 1
  documents exactly what must change first); extraction-failure/quarantine policy
  (slice 3); shutdown cancellation (slice 2); any whisper-inject behavior.
- **Test env caveats:** default pytest run excludes `integration`. `tests/test_setup*.py`
  can touch the real `~/.claude` — verify survival by parsing JSON, never `grep -i ormah`.
  `~/.config/ormah/.env` leaks into bare `Settings()` (known, environmental).
- Lint: `ruff check src/ tests/` (line-length 100, py311). Commits: `feat(scope): ...`.

## The rules that carry measurements — do not relax them

Each was produced by a prototype run, and each protects against a failure that was actually
observed rather than imagined.

| Rule | Evidence |
|------|----------|
| Boundary in the spool **filename**, never one file overwritten per path | overwrite lost the higher boundary in **135/300 races** (45%) |
| Every file write is `tmp` + `os.replace` — including `_save_state` | direct write: **7081 torn reads** vs 664 clean in 1.5 s; via replace: **0** torn |
| The claim is the `os.rename`; the loser's error is the mechanism | 40 rounds × 8 **processes**, always exactly 1 winner |
| The hook's outbox locks a **stable lock file**, never the outbox inode | locking the inode: **1140 mutual-exclusion violations** in 2 s; stable lock file: **0** |
| Worker stays serial until a path-level claim exists | overlapping ingests of one transcript: 0 at 1 worker, **14 at 2**, **21 at 4** |
| **One ingestion path**: Observer and reconcile ENQUEUE, they never ingest | same measurement, same failure — two producers on one transcript is the overlap, whether they are two workers or an Observer racing the drain |
| No fsync by default; power-loss durability is a named, priced option | `F_FULLFSYNC` p50 **6.9 ms** vs 0.13 ms unsynced (and plain `os.fsync` does not reach media on APFS) |

## Council round on the rewrite (2026-07-22, R12) — all 11 findings accepted

Cursor and Codex reviewed the spool design independently and converged on one architectural
defect plus six policy ones. Nothing was rejected. The three most consequential:

- **One ingestion path.** The first spool draft had the drain calling `_ingest_session`
  directly while the Observer kept its own route through `_do_ingest` — two producers on one
  transcript whenever the watcher is enabled. Fixed by making the Observer and the reconcile
  sweep **producers that enqueue**, with a single serial consumer owning `_ingesting` and
  `state_lock`. This is simpler than what it replaced.
- **`max_bytes` is not a ceiling.** The boundary cap was built on `max_bytes`, but
  `parse_transcript` commits an oversized single turn anyway (its own docstring,
  parser.py:222-223). A `stop_offset` primitive is now required — and it is the only part of
  this slice that touches the parser, so it carries its own risk note.
- **An attempt cap turns an outage into data loss.** The bounded-requeue guard added to stop
  a hot loop would dead-letter work during a provider outage — the exact H1 rule ADR-0004
  protects. Retry policy now keys on failure CLASS, with persisted backoff and no cap for
  external transients.

Full record: `$COUNCIL_HOME/council-result.md` (run 819fd547-66405d98-d6caaf40).

## Council amendments that survive the rewrite

- **Consent is now structural, not a rule.** `session_watcher_enabled=False` means "do not
  auto-ingest my transcripts". With the spool, a disabled install's worker drains the queue
  and nothing else — an entry exists only because the user's own hook created it. This
  retires the intent-only reconcile *scope rule* and the `rglob` cost on disabled installs.
  ⚠️ It does NOT retire `discover` itself: council R12 restored it as a **per-watch
  property** gating both the Observer and the sweep, because a custom `session_watcher_dir`
  still needs acceptance-only roots that are never swept. **The hard ceiling stays** (Task 3):
  ingestion never reads past the accepted boundary, because PreCompact nudges a live
  session that keeps growing.
- **One `app.state` attribute (R1).** Startup and shutdown must both use
  `app.state.session_watches`; today shutdown reads `session_watcher_observers`
  (`main.py:282-283`), so leaving it would mean `stop_session_watcher` never runs →
  use-after-close on the DB.
- **Configured-but-absent watch roots still get a handler (R4/R5)** — `_session_watch_dirs`
  filters on `exists()` (L679), so an absent `~/.claude/projects` would strand every nudge
  behind a permanent 422.
- **Discovery roots ≠ acceptance roots (R10/R11).** A custom `session_watcher_dir` replaces
  the discovery defaults on purpose, but a nudge is an explicit user request: acceptance
  must still cover the standard Claude and Codex roots, deduplicated, with ancestor/
  descendant overlaps collapsed so one transcript can never get two cursors.
- **`_save_state` must be atomic** — independent of the spool. A torn `write_text` discards
  every cursor in the watch dir, and `_load_state` treats corrupt JSON as "start fresh".
- **The hook keeps an outbox (R6-R9).** Neither spool nor table protects against the server
  being unreachable. Four rules: queue first then send; budget the drain by wall clock and
  request count; remove an entry only on **its own** 202; lock a stable lock file.
- **The legacy client cursor is retired only after a 202** — deleting it on a 404/422 or
  while offline would discard the only record of what was already ingested.

## Task Map

| # | File | Delivers | Depends on |
|---|------|----------|------------|
| 1 | `01-spool.md` | `IngestSpool`: durable file queue, claim-by-rename, crash recovery | — |
| 2 | `02-always-on-worker.md` | Handler + drain loop always on; Observer optional; one `app.state` attribute | 1 |
| 3 | `03-nudge-endpoint.md` | `POST /ingest/nudge` → enqueue + 202; boundary ceiling in `_ingest_session` | 1, 2 |
| 4 | `04-hook-pure-nudge.md` | `cmd_whisper_store` = trigger only; client cursor retired safely; outbox | 3 |
| 5 | `05-verification.md` | Suite green, isolated smoke, Beta merge, upstream gap list | 1-4 |

## Key Anchors (verified 2026-07-21 on local-main @ 66405d9)

- Worker: `src/ormah/background/session_watcher.py` — `_ingest_session` L728-995 (parse with
  `max_bytes=flush_bytes` L776; already-consumed early return L770-771; empty-delta return
  L829-835; success entry rebuild L970-981), `_session_watch_dirs` L669-681 (⚠️ `exists()`
  filter L679), `_save_state` L700-703 (⚠️ non-atomic), `_commit_state` L706-714,
  `SessionHandler` L1051 (guard `_ingesting` L1076, `_schedule_ingest` L1084, `_do_ingest`
  L1115-1147), `reconcile` L1161 (`rglob` L1188), `SessionWatch` L1279,
  `_run_startup_reconcile` L1287, `start_session_watcher` L1299 (enabled-gate L1308,
  missing-dir `return []` L1311-1314, rollback L1339-1354), `stop_session_watcher` L1374,
  `run_session_reconcile` L1398.
- Endpoint: `src/ormah/api/routes_ingest.py` (only `/conversation` L19, `/file` L52 exist).
- Hook: `src/ormah/adapters/cli_adapter.py` — `cmd_whisper_store` L423-519, cursor machinery
  L404-420, store client/timeout L387-401. Note: it opens **no** DB — a pure HTTP client.
- Lifespan: `src/ormah/main.py` L186; watcher start L244-246, reconcile job L248-253,
  shutdown L282-283 (reads `app.state.session_watcher_observers` today).
- Config: `src/ormah/config.py` L20 (`extra: "ignore"`), L29 (`memory_dir`), L92-103
  (`session_watcher_*`, incl. `_debounce_seconds=60`, `_reconcile_max_per_tick=50`).
- Store DB (why not a job table): `src/ormah/index/db.py` L37-40 — WAL,
  `synchronous=NORMAL`, `busy_timeout=5000`, serialized writes.
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
4. `ls ~/.local/share/ormah/memory/ingest_queue/pending/` is now a real operational view —
   a growing pending count means the worker is stuck, not that nudges are lost.

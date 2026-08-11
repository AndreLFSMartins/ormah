# ⛔ SUPERSEDED — this plan was split into three slices (2026-07-21)

**Do not execute the task files in this directory.** They are kept only as the historical
record of the consolidated plan that went through eight council review rounds.

The work now lives in three independently shippable plans:

| Order | Plan | Delivers | Status |
|-------|------|----------|--------|
| 1 | `../2026-07-21-adr-0004-slice1-nudge-core/` | Nudge core: always-on worker, `POST /ingest/nudge`, pure-nudge hook | ready to execute |
| 2 | `../2026-07-21-adr-0004-slice2-bounded-shutdown/` | Cancel in-flight extractions so shutdown stays bounded | ready; ships right after slice 1 |
| 3 | `../2026-07-21-adr-0004-slice3-timeout-quarantine/` | Timeout → health-gated, shrink-first quarantine | **BLOCKED** — needs its own ADR first |

## Why it was split

The consolidated plan bundled three independent changes. Across eight review rounds the
defects clustered almost entirely in the failure-policy half (timeout classification,
quarantine, cancellation) while the nudge core stayed stable — so bundling them meant the
core could not ship until the riskiest part was settled.

Slice 3 is blocked deliberately: it is the only part of ADR-0004 that can permanently drop
real user conversation, and that decision was never ratified in an ADR of its own.

## What survived the review (carried into the slices)

- The upstream cherry-pick strategy was **refuted by evidence**: `upstream/main`'s
  `session_watcher.py` is ~222 lines behind (1203 vs 1425), still calls `_scan_sessions`
  synchronously at bind, and lacks `flush_bytes`, `stop_event`, `startup_thread`,
  `cancel_pending_timers`, `_drain_handlers`; its `llm_client.py` has no ingest-provider
  seam. All slices are Beta-only; upstream contribution is a separate future effort.
- The smoke test would have mutated the **live memory store** (`ORMAH_DATA_DIR` is not a
  setting; `Settings` uses `extra: "ignore"`). Every slice now gates on an asserted
  `ORMAH_MEMORY_DIR`.
- Making the reconcile always-on turned `session_watcher_enabled=False` from "do not
  auto-ingest my transcripts" into "only the Observer is off" — a **consent change**. The
  sweep is now recovery-only when the flag is off.

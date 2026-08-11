# ADR-0004 Slice 3 — Extraction timeout: health-gated, shrink-first quarantine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans. Each task is its own file; steps use checkboxes.

**Goal:** Stop a slow slice from re-burning quota forever, without ever discarding
conversation a provider merely delayed. Today a `claude -p` timeout returns `None` →
classified provider-wide `EXTRACT_ERR_CALL_FAILED` → `TRANSIENT` with no per-slice
increment, so the same slice re-extracts every tick indefinitely.

## ⛔ BLOCKED: this slice needs its own ADR first

**Do not implement this plan until an ADR is written and accepted.** This is the only part
of ADR-0004 that can **permanently drop real user conversation**, and the council review
kept finding failure modes in it — the design here is the survivor of eight rounds, but the
decision it encodes was never ratified in an ADR of its own.

What that ADR must decide, explicitly:

1. **Is dropping data ever acceptable to unstick a lane?** The alternative is parking the
   slice forever (data preserved, that transcript's ingestion permanently stalled, quota no
   longer burned because of the backoff). This plan chooses bounded dropping with a
   replayable record; that is a product call, not an implementation detail.
2. **What "toxic" means.** Lateness is not toxicity. A large-but-valid slice times out
   while smaller ones succeed. This plan therefore requires BOTH provider-health evidence
   AND an exhausted shrink budget before a single failure counts — see below.
3. **The single-oversized-turn hole.** The parser deliberately commits a first turn that
   exceeds `max_bytes` (no safe conversational boundary exists inside it), so shrinking
   cannot rescue a huge paste in one turn. Under this design such a turn is still
   eventually quarantined. The ADR must accept that explicitly or specify another route
   (e.g. hand the oversized turn to a summarisation path, or park it and alert).

`docs/adr/0004-async-ingest-nudge-server-cursor.md` already states that a timeout "counts
toward the per-slice cap and quarantines after N". The review showed that rule, as written,
loses data during a provider outage. Amending it is exactly the work above.

## Prerequisites

- **Slice 1** (`../2026-07-21-adr-0004-slice1-nudge-core/`) merged.
- **Slice 2** (`../2026-07-21-adr-0004-slice2-bounded-shutdown/`) merged: it creates
  `src/ormah/background/llm_errors.py` (with `LlmTimeoutError` already defined but never
  raised) and converts the adapter to a tracked `Popen`. Task 1 here only adds the raise
  site. If slice 2 was skipped, Task 1 must create the module and do the `Popen` migration
  itself — check before starting.

## Design (survivor of council rounds R1-R8 — all findings accepted)

- **Health gate.** A timeout counts toward `MAX_EXTRACT_FAILURES` only when another slice
  extracted successfully since THIS slice's previous timeout. That brackets the failure as
  slice-specific. Without the bracket it is indistinguishable from an outage → uncapped
  `TRANSIENT`. Mechanism: a monotonic module marker `_LAST_EXTRACT_OK` plus a persisted
  per-slice `extract_fail_at`.
- **Atomicity.** The bracket decision and the state write happen in ONE locked mutation, so
  a single success can authorise at most ONE counted timeout. Two commits would let a
  stale snapshot restore the old timestamp and turn one success into unlimited counts.
- **Shrink before cap.** A bracketed timeout first HALVES the slice
  (`max_bytes = max(floor, flush_bytes >> level)`, `floor = min(MIN_SLICE_BYTES,
  flush_bytes)` — never RAISE a configured `flush_bytes`). Only at the floor does a further
  bracketed timeout count. If a shrink level fails to move `payload_offset`, shrinking is a
  no-op (single oversized turn) — stop burning levels and say so in the log.
- **Cancellation is not a timeout.** `LlmCancelledError` (slice 2) maps to
  `EXTRACT_ERR_CALL_FAILED` → uncapped `TRANSIENT`, caught BEFORE any broad handler, so
  restarts can never spend a healthy slice's budget.
- **Quarantine stays observable.** `_record_extract_failure` already writes a replayable
  `skipped_slices` entry (start/end/source_hash/reason, L871-877) and logs
  `observable data loss` at ERROR. That record is what makes bounded dropping defensible —
  do not weaken it.
- **Declared limitation.** Only the `claude_cli` adapter raises the signal; ollama/litellm
  keep `None` → `EXTRACT_ERR_CALL_FAILED` → TRANSIENT (today's behaviour).

## Global Constraints

- **Never checkout a branch in `Tools/ormah`** — it is the live Beta. Work in a worktree
  cut from `local-main`; run tests with that worktree's venv.
- **Beta-only.** `upstream/main` has no ingest-provider seam (its `llm_client.py` exposes
  only `llm_generate`; `memory_engine` calls it directly at upstream L2316-2320) and no
  `claude_cli` adapter — this classification would ship as inert code upstream.
- **Out of scope:** nudge/worker (slice 1), shutdown cancellation (slice 2), worker
  concurrency (#150).
- Lint: `ruff check src/ tests/` (line-length 100, py311).

## Task Map

| # | File | Delivers | Depends on |
|---|------|----------|------------|
| 1 | `01-timeout-signal.md` | claude_cli raises `LlmTimeoutError` on `TimeoutExpired` | slice 2 |
| 2 | `02-timeout-classification.md` | `EXTRACT_ERR_TIMEOUT`; health gate + shrink-then-cap | 1 |
| 3 | `03-verification.md` | Suite green, quarantine audit, Beta merge | 1-2 |

## Key Anchors (verified 2026-07-21 on local-main @ 66405d9)

- Adapter: `src/ormah/background/llm/claude_cli_adapter.py` — `generate()` L104-172,
  `except subprocess.TimeoutExpired` L141-143 (slice 2 leaves it returning `None`).
- Engine: `src/ormah/engine/memory_engine.py` — `EXTRACT_ERR_*` constants L54-61,
  `_extract_memories_llm` L2842, `ingest_llm_generate` call L2861-2867, None-branch
  L2868-2886.
- Watcher: `src/ormah/background/session_watcher.py` — `_ingest_session` L728-995 (parse
  with `max_bytes=flush_bytes` L776; `existing` loaded L765), classification L942-954,
  `_record_extract_failure` L856-910 (cap L868, quarantine entry L871-877, counter persist
  L901-910), `_commit_state` L706-714, success entry rebuild L970-983.
- Tests: `tests/test_background/test_session_watcher.py` — `_LLM_PATCH` L31,
  `_UNPARSEABLE` L36, `_LLM_RESPONSE` L41, `_make_jsonl` L51, `_mark_idle` L68, and the
  reference cases `test_toxic_slice_skipped_after_max_extract_failures` L204,
  `test_provider_wide_call_failure_never_skips_slice` L408.

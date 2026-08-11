# Whisper-health metric — design

**Date:** 2026-06-24
**Status:** approved, ready for implementation plan
**Motivates:** follow-up to #21 / PR #40 review (r-spade asked for a surfaced coverage/precision number)

## Problem

The whisper feedback loop's *collection* side was closed in #21: every injected
memory is logged to `whisper_log`, and feedback signals land in `affinity` keyed
per-turn by `whisper_log_id`. But nothing *reads back* that data. Whisper
effectiveness is still unmeasurable — we can't verify the loop moved from the
original ~0.7% coverage to anything healthy on a real instance. The loop is
closed but blind.

This spec adds the read/aggregate side only. No change to collection, the miner,
or `session_watcher`.

## Approach

One pure function plus a single line in `engine.stats()`. Chosen because
`stats()` already powers `GET /stats` and `ormah stats`, so the CLI and the
upcoming Ormah App both inherit the metric with zero extra surface.

## Components

### `compute_whisper_health(conn, now) -> dict` (new)

- **File:** `src/ormah/engine/whisper_health.py` (new, isolated, unit-testable
  without the engine).
- **Inputs:** a sqlite connection and an injected `now` (`datetime`, tz-aware) —
  `now` is a parameter, never `datetime.now()` inside the query, so tests are
  deterministic.
- **Output:** a dict with two recuts, `all_time` and `last_7d`, each containing:

  ```
  injected       int    COUNT(*) FROM whisper_log WHERE was_injected = 1
  feedback_rows  int    COUNT(DISTINCT whisper_log_id) FROM affinity
                          WHERE whisper_log_id IS NOT NULL
  coverage       float  feedback_rows / injected   (None when injected = 0)
  positive       int    COUNT(*) FROM affinity WHERE signal = +1
  negative       int    COUNT(*) FROM affinity WHERE signal = -1
  precision      float  positive / (positive + negative)  (None when sum = 0)
  ```

  Raw counts (`injected`, `feedback_rows`, `positive`, `negative`) are exposed
  alongside the ratios so a tiny denominator is never hidden (the "1/1 = 100%"
  trap). `coverage` and `precision` are `None` — never a fake `0.0` — when their
  denominator is zero.

### `engine.stats()` (edit)

Add one key: `"whisper_health": compute_whisper_health(self.db.conn,
datetime.now(timezone.utc))`. No signature, route, or CLI change.

## Key design decision — coverage uses `DISTINCT whisper_log_id`

A single injected memory can accumulate several `affinity` rows across a turn
(that was the point of the #3 fix — keying affinity by `whisper_log_id` so
per-turn signal accumulates instead of being dropped). Coverage answers "how
many *injections* received any feedback", so the numerator counts distinct
injections with feedback, not raw affinity rows. Counting raw rows could push
coverage above 100%. This is the one subtle point in the whole change.

## Time windows

- `all_time`: no date filter.
- `last_7d`: `logged_at >= now - 7d` for the `whisper_log` side (denominator);
  `confirmed_at >= now - 7d` for the `affinity` side (numerator and precision).
- The 7-day threshold is computed from the injected `now`, not inside SQL.

Timestamps are ISO-8601 TEXT columns; string comparison on ISO-8601 is
chronological, so `WHERE logged_at >= ?` with an ISO threshold is correct
without parsing.

## Testing (TDD)

New suite `tests/test_whisper_health.py`, fixtures inserting rows directly into
`whisper_log` / `affinity`:

1. **Empty store** — both ratios `None`, no ZeroDivisionError.
2. **Injection, no feedback** — `coverage == 0.0`, `precision is None`.
3. **Mixed +1/-1** — `precision` correct (e.g. 3 pos / 1 neg → 0.75).
4. **Multiple affinity rows on one `whisper_log_id`** — `coverage <= 1.0`
   (guards the DISTINCT decision).
5. **7-day cutoff** — a row older than 7d counts in `all_time` but is excluded
   from `last_7d` (drives the injected-`now` threshold).

## Out of scope

- Configurable window (fixed all_time + 7d).
- Explicit/implicit precision breakdown.
- Any change to the miner / `session_watcher` (the #34 transcript-state concern
  is about the writer; this is a read-only query).
- Ormah App UI (r-spade owns that; this just feeds it).

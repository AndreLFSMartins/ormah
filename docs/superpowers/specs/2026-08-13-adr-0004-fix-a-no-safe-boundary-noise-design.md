# Design: ADR-0004 Fix A — stop dead-lettering `no_safe_boundary`

Status: approved (brainstorming) — 2026-08-13

## Context

ADR-0004's "Still open" list (2026-08-13 amendment) names Fix A: eliminate the noise from
the `no_safe_boundary` dead-letter. Measured 2026-07-27: 96% of `failed/` entries under
`ingest_queue/` are the normal end-of-session path (a transcript idles with its last JSONL
line still open) recorded as a deterministic failure — not a real loss. The 2026-08-13
amendment ("Fix B") already replaced the cursor-advancing suppression
(`_mark_frozen_prefix_consumed`) with a suppression *fact* (`frozen_until` + file identity,
written by `_mark_frozen_prefix_parked`), and both producers (`reconcile`, `_enqueue_path`)
already re-select a parked file the moment it changes (`_frozen_unchanged`). That part is
shipped, tested, and verified in production.

What Fix B did not touch: the call site still classifies every park as a **failure** —
`self.spool.requeue(job, failure_class="no_safe_boundary")` — which `IngestSpool.requeue`
dead-letters immediately (any non-`"external"` class is treated as deterministic and
written to `failed/`). Every idle tick that finds an unclosed tail writes a fresh dead-letter
entry, even though the frozen-until fact already prevents the hot re-enqueue loop and
already ensures reprocessing on growth. The dead-letter has become pure noise: something is
recorded as failed that isn't actually stuck, and the record duplicates information the
state file (`frozen_until`) already holds structurally.

## Decision

Stop treating a park as a spool-level failure. When `_mark_frozen_prefix_parked` has
already written the suppression fact, the job has nothing further to do — `spool.complete()`
it instead of `spool.requeue(..., failure_class="no_safe_boundary")`.

```python
# src/ormah/background/session_watcher.py, inside _ingest_session's NO_PROGRESS branch
examined = self._idle_with_unsafe_tail(path, rel, job.boundary)
if examined is not None:
    self._mark_frozen_prefix_parked(path, rel, job.boundary, examined=examined)
    logger.debug("Parked %s at frozen_until=%s (no safe boundary yet)", rel, job.boundary)
    self.spool.complete(job)
    return
```

Add a `logger.debug` (or `info`) at the park call site as the replacement for the
`.error` sidecar's grep-able text — the previous operational signal
(`grep no_safe_boundary failed/*.error`) disappears with the dead-letter, and a log line is
a cheap substitute for live observability. The state file's `frozen_until` remains the
durable record; the log is not relied on for correctness.

## What does not change

- `IngestSpool.requeue`'s generic dead-letter mechanism (any non-`"external"` class →
  `failed/`) is untouched — it still serves `transcript_deleted` and any future
  deterministic class. This change only removes one caller's use of it, not the mechanism.
- The Fix B suppression fact (`frozen_until`, `_frozen_unchanged`, both producers'
  re-selection-on-change) is untouched.
- Recovery of the 14 transcripts / 5.92 MB / 23 closed turns already measured as lost
  (ADR-0004 "Still open" item 2) is out of scope — separate spec, separate risk (writes to
  production state).
- The `no_safe_boundary` string itself is retired as a `failure_class` value passed into
  `IngestSpool.requeue` (grep confirms `session_watcher.py:1559` is the only production call
  site). `IngestSpool` itself needs no code change — only its one caller stops using that
  class.

## Test changes

Existing tests assert dead-lettering for this path; they must be updated to assert the new
behavior instead of being deleted, since they cover a real scenario (idle file, unclosed
tail) that must still park correctly — only the disposition changes.

1. `tests/test_background/test_session_watcher.py::test_idle_file_with_no_safe_boundary_is_dead_lettered`
   (line ~2967) — rename to reflect "completed without a dead-letter"; replace the
   `failed/*.json` / `*.error` assertions with: `spool.pending_count() == 0`, `running/`
   empty, `failed/` **empty**, and `handler._state[rel]["frozen_until"] == jsonl.stat().st_size`.
2. `tests/test_background/test_session_watcher.py::test_abandonment_with_unclosed_tail_composes_with_frozen_prefix`
   (line ~4411) — drop the two `failed/` assertions (~4446-4449); keep the `frozen_until`
   and `end_offset` assertions, which describe the cursor/park behavior this change does not
   touch.
3. New test: parking the same unchanged file across two consecutive idle ticks (no growth
   between them) must not write anything to `failed/` at all — the direct regression test
   for the noise this fix removes. (Today this is only implied by `_frozen_unchanged`
   short-circuiting the second tick before it ever reaches the park call; worth asserting
   directly since it's the exact behavior Fix A exists to guarantee.)

No changes needed to `test_shrunk_file_with_no_safe_boundary_is_not_stranded` — it does not
assert on `failed/`.

## Risks / non-goals

- **Assumed:** no other caller depends on `IngestSpool.requeue(..., failure_class="no_safe_boundary")`
  landing in `failed/` (verified by grep — single production call site, three test
  references, all listed above).
- **Not addressed:** the already-lost content (ADR-0004 Still-open item 2) and the parser
  coverage gap (item 3) are separate, out of scope here.
- **Out of scope:** `AndreLFSMartins/ormah#2` (cursor-above-EOF class, 83-byte overshoot) —
  unrelated mechanism, not touched by this change.

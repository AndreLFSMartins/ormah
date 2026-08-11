# Never advance the cursor without ingesting — design

**Date:** 2026-08-09 · **Status:** approved, not yet implemented
**Defect:** silent, permanent transcript loss via `_mark_frozen_prefix_consumed`
**Scope:** stop the bleeding only. Repairing already-orphaned state entries is separate work.

## The defect

`SessionHandler._run_job` advances the durable byte cursor over transcript bytes that were
never ingested. The prompt that lives in those bytes is lost permanently: when the response
that follows it finally closes, its user turn is already behind the cursor and is never
paired.

Verified chain:

1. A session dominated by long `tool_use` chains goes idle with the cursor mid-turn. The
   parser only closes on a terminal `end_turn` or on a following user turn, so hundreds of
   KB can pass with no close point. Measured on `2d7289f8`: **211 `tool_use` records to 10
   `end_turn`**.
2. `should_rewind` fires and re-parses from 0 with `stop_offset=boundary`
   (`session_watcher.py:1002`).
3. The boundary cuts *before* the first `end_turn`, so `safe_end_offset <= original_offset`
   and `_ingest_session` returns `NO_PROGRESS`.
4. `_run_job` calls `_idle_with_unsafe_tail`, which repeats the same parse, concludes the
   prefix is frozen, and calls `_mark_frozen_prefix_consumed` — which advances the cursor
   **past the prompt**.
5. With no prior state entry, `entry = dict(self._state.get(rel, {}))` starts empty and the
   commit produces exactly `{"end_offset": N}`.

`{"end_offset": N}` alone is the durable signature of this defect. Verified by exhaustive
reading of every commit site in `_ingest_session` (lines 940, 957, 967, 1069, 1170, 1196,
1271): none of them can produce it. Five write `hash` alongside `end_offset`. The
`shrink_pending` site (940) writes no `end_offset` at all when there is no prior entry, and
the marker-clearing site (967) only runs when a prior entry already carried other keys.
`_mark_frozen_prefix_consumed` is the sole remaining origin.

### Measured evidence

Distance between the recorded cursor and the first offset at which the parser closes
anything, over the affected files:

| file | cursor written | first close | short by |
|---|---|---|---|
| `8e1c4e8d` | 195,524 | 197,025 | **1,501 B** |
| `23fd6619` | 41,183 | 42,778 | **1,595 B** |
| `045afa87` | 980,228 | 987,803 | 7,575 B |
| `2d7289f8` | 323,695 | 331,780 | 8,085 B |

The cursor stops 0.8%–2.5% short of the close. This is not random: it is the nudge boundary
landing inside a tool-call chain.

Confirmation from production: after the unrelated ingest-provider outage was fixed on
2026-08-09, `2d7289f8` drained and recorded `user_turns=7`. A whole-file parse yields **8**.
The skipped prompt is gone, and the resulting memories carry no marker that anything is
missing.

### Aggravating factor: the loss is unlogged

`_mark_frozen_prefix_consumed` emits no log line at all. Its sibling paths
(`ABANDONING`, `SKIPPING`) both log `observable data loss` explicitly. This is why the
defect went unnoticed while the affected set grew.

## The policy the code already declares

`_ingest_session` states the correct rule in its own docstring (lines 1080–1083):

> *"A trailing block with no completion signal yet is genuinely in-flight and is held back;
> once it completes the file changes and the next parse picks it up. (A response left forever
> in-flight — a process killed mid-turn — is intentionally never ingested.)"*

`_run_job` violates that policy 400 lines below by moving the cursor. **The fix is to make
the code obey what it already says.**

## Design

### Change

In `_run_job`, the `NO_PROGRESS` branch:

```python
if self._idle_with_unsafe_tail(path, rel, job.boundary):
    self._mark_frozen_prefix_consumed(path, rel, job.boundary)   # delete
    self.spool.requeue(job, failure_class="no_safe_boundary")    # -> "external"
    return
```

becomes:

```python
if self._idle_with_unsafe_tail(path, rel, job.boundary):
    # Bytes past the cursor that close nothing YET. "Not yet" is not "never": hand the job
    # back to the spool's persisted backoff instead of moving the cursor over a prompt.
    # Suppressing re-selection is never expressed by advancing the cursor (ADR-0004,
    # amendment 2026-07-28 — the one rule of that amendment that survives).
    self.spool.requeue(job, failure_class="external")
    return
```

`_mark_frozen_prefix_consumed` is deleted in full (~22 lines). Net: **−25 lines, no new
persisted field, no new policy surface.**

### Why `requeue(external)` and not `complete()`

`complete()` relies on `reconcile` to re-select the file. But acceptance-only roots
(`discover=False`) are **never swept** by reconcile (`session_watcher.py:1571`), so
completing there would genuinely strand the bytes. The code's fear was legitimate; only its
remedy was wrong.

`failure_class="external"` retries forever with exponential backoff persisted in the job
payload (2s base, 300s ceiling), independent of reconcile. **This is the same remedy the file
already applies to the sibling problem** three lines below (lines 1491–1497): the
`shrink_pending` gate faced the identical acceptance-only dilemma and resolved it exactly
this way, with the reasoning written out. Applying it here is consistency with the existing
design, not invention.

### Why the predicate stays

`_idle_with_unsafe_tail` is **not** removed. Its detection was correct; only the action was
wrong. Without it every `NO_PROGRESS` would become an infinite retry, including the benign
majority (file already fully consumed). The predicate is what separates *"there is nothing
here"* from *"it has not closed yet"*.

Its docstring must be updated: the sentence describing the dead-letter outcome no longer
holds.

## Tests

Written first, each confirmed failing against current `local-main` before the fix.

| id | asserts | fails today |
|---|---|---|
| T1 | idle file, `[cursor, boundary)` closes nothing, whole file closes → cursor **unchanged**, job back in `pending` | yes — cursor jumps to the boundary |
| T2 | same file after growing past the first `end_turn` → ingests **including the leading user turn** | yes — that turn is the one lost |
| T3 | no state entry may hold only `end_offset` after any `_run_job` sequence | yes — this is the production signature |
| T4 | a fully consumed file still `complete`s, does **not** requeue | no — anti-regression guard on cost |

T4 is load-bearing: without it the fix could turn every benign `NO_PROGRESS` into an
infinite retry loop.

### Existing tests to rewrite

| test | line | action |
|---|---|---|
| `test_idle_file_with_no_safe_boundary_is_dead_lettered` | 2666 | invert — expect `pending` with backoff, not `failed` |
| `test_frozen_prefix_advance_never_passes_the_accepted_boundary` | 2692 | delete — mechanism no longer exists |
| monotonic guard on `_mark_frozen_prefix_consumed` | ~2830 | delete |
| `test_abandonment_with_unclosed_tail_composes_with_frozen_prefix` | 3850 | `end_offset` now stops at `skipped[0]["end"]`, not `size` |
| `test_shrunk_file_with_no_safe_boundary_is_not_stranded` | 4038 | **no change** — verified: it calls `_ingest_session` directly, never `_run_job` or the spool |

The change at line 3850 is a **substantive improvement**, not an accommodation: that case
currently suffers two compounded losses — one recorded in `skipped_slices` and a second,
silent one layered on top. Only the recorded one remains.

`failure_class="no_safe_boundary"` disappears from the codebase entirely.

## Branch placement

`upstream/main` does **not** contain this code — verified, 0 occurrences of
`_mark_frozen_prefix_consumed`, `_idle_with_unsafe_tail`, and `no_safe_boundary`. The defect
entered via `adbec81` (ADR-0004 slice 1), which was **never submitted upstream** (verified
via `gh pr list`: no PR exists for that branch).

Therefore this is not an upstream contribution. The fix lives in `local-main` and travels
with slice 1 whenever that is submitted.

This requires a **documented deviation from FORK-WORKFLOW Recipe A**: the worktree is cut
from `local-main`, not from `upstream/main`, because the code being fixed does not exist
upstream. Golden rule 1 still holds — the running Beta's working tree is never checked out
or switched; work happens in the worktree and reaches `local-main` by merge only after the
suite is green.

## Accepted risk

A session killed mid-response is now retried **forever**, one parse per ≤5 minutes. Measured
against current production state (~20 files in that condition) this is ≤4 parses/minute —
negligible against the cost of permanent loss, and it is precisely the behaviour
`_ingest_session` already promises.

## Out of scope

- Repairing the 24 already-orphaned state entries. Writing to `.session_watcher_state` is
  production state and needs its own session, its own backup, and explicit approval.
- The Codex parser defect (4 rollouts, 1.62 MB, `safe_end_offset=0` on whole files).
- The missing log line in the freeze path. Worth adding, but the fix removes the path that
  would have needed it.

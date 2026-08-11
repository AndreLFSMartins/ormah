# Design: Session Watcher Cursor Safety

**Date:** 2026-06-24  
**PR:** #34  
**Bugs addressed:** mid-turn race (r-spade comment #4791448793, point 1) + session tail loss (point 2)

## Problem

PR #34 added an incremental byte cursor (`end_offset`) to avoid re-parsing entire transcripts. Two edge cases remain unfixed:

### Bug 1 — Mid-turn race

The watcher can advance the cursor past a `User:` entry before the corresponding `Assistant:` response is written. On the next tick, the parser starts after the user turn, sees only the assistant message, finds zero user-turns, and the slice is discarded. The user+assistant pair is never ingested together.

### Bug 2 — Session tail loss

`min_turns` is applied to the appended slice. If a session ends with fewer new turns than `min_turns` (e.g., 3 turns with `min_turns=5`), the threshold is never reached and those final turns are permanently skipped.

## Design

### Fix 1 — `safe_end_offset` in `parse_transcript`

**File:** `src/ormah/transcript/parser.py`

Replace the `for line in f` loop with a `readline()` loop that tracks the byte offset after each complete `assistant` turn.

`TranscriptResult` gains one new field:

```python
safe_end_offset: int  # offset after last complete user+assistant pair
                      # equals start_offset if no complete pair was seen
```

Rule: `safe_end_offset` advances only when an `assistant` turn is appended to `turns`. If the last turn in the parsed slice is `user` (no trailing assistant), `safe_end_offset` stays at the previous value — the dangling user turn will be included in the next slice. When `safe_end_offset == prev_offset` (no new complete pair), `_ingest_session` must not ingest and must not advance the cursor, even if `user_turn_count >= min_turns`.

`_ingest_session` saves `safe_end_offset` as the cursor (replaces `end_offset` in the state dict). `end_offset` is kept in `TranscriptResult` for diagnostics but not written to state.

### Fix 2 — Idle/mtime flush in `_ingest_session`

**File:** `src/ormah/background/session_watcher.py`

`_ingest_session` receives a new parameter:

```python
idle_threshold: int = 60  # seconds
```

After the `user_turn_count < min_turns` check, add:

```python
idle = (time.time() - path.stat().st_mtime) > idle_threshold
if not idle:
    return False
```

If the file has not been modified for `idle_threshold` seconds, ingest regardless of `min_turns`. This covers sessions that ended with a short tail.

The `idle_threshold` default (60 s) is conservative: it's longer than the typical assistant response latency but short enough to capture end-of-session turns within the same watcher cycle.

## Affected files

| File | Change |
| --- | --- |
| `src/ormah/transcript/parser.py` | `readline()` loop; add `safe_end_offset` to `TranscriptResult` |
| `src/ormah/background/session_watcher.py` | use `safe_end_offset` as cursor; add idle check with `idle_threshold` param |
| `tests/test_background/test_session_watcher.py` | 3 new tests (see below) |

## New tests

1. **`test_mid_turn_race`** — write a file up to a `User:` entry only (no trailing assistant). Verify `_ingest_session` does not advance the cursor and returns `False`. Then append the `Assistant:` entry and verify the pair is ingested on the next call with the cursor advanced.

2. **`test_session_tail_idle_ingested`** — ingest 6 turns, then append 2 more and set mtime to `now - 120s`. Verify `_ingest_session` ingests the 2-turn tail despite `min_turns=5`.

3. **`test_session_tail_active_deferred`** — same setup but mtime is recent (`now - 10s`). Verify `_ingest_session` returns `False` (session still active).

## Out of scope

- Feedback-mining integration (mentioned by r-spade as a downstream concern — addressed once cursor safety is merged).
- Rebase onto current `main` (separate step before merge).

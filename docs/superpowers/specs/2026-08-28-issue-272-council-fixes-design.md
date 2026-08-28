# Issue #272 council fixes — truthful backfill clock, load inside the transaction

**Date:** 2026-08-28 · **Branch:** `fix/272-heuristic-confirmed-use` (island `../ormah-wt-272` @ `e975a90`)
**Source:** `/council-pr` run 40d8ff05 — `MERGE=blocked`, two accepted findings (Codex, both `high`;
finding 2 downgraded to `medium` by Cursor round 3). Result: `~/.council/state/r-spade-ormah-683b05e/council-result.md`.

Two fixes, two separate commits, finding 1 first (it fires alone on every upgrade boot). TDD, RED first.

## Fix 1 — boot backfill stamps the real event time

### Problem (verified by reading + live-store measurement)

`_claim_confirmed_use` (`memory_engine.py:3017`) stamps `claimed_at = datetime('now')`
unconditionally. The boot backfill (`:324-370`) therefore records historical uses as occurring at
startup. `_record_confirmed_use` (`:2357`) uses `claimed_at` as the clock for `last_accessed`,
`last_review` and FSRS — and the final-review I1 clamp (`max(now, last_accessed)`, `:2395`)
*preserves* the forward jump. Measured on the production store (read-only): 42 eligible signals,
`logged_at` 2.20–13.23 days old, median 9.84 — unearned recency pushed straight into the decay anchor.

### Mechanism (approach A — chosen over parameter plumbing)

The claim INSERT already selects `FROM whisper_log wl WHERE wl.id = ?` — the truthful timestamp is
in the very row the claim's FK references. Add `historical: bool = False` to `_claim_confirmed_use`
and make the timestamp expression conditional:

```sql
CASE WHEN ? THEN COALESCE(datetime(wl.logged_at), datetime('now'))
     ELSE datetime('now') END
```

The backfill passes `historical=True`; every live caller is untouched (default `False`). Rejected
alternatives: (B) projecting `wl.logged_at` in the backfill SELECT and plumbing it through Python —
works, but opens a path for a future caller to pass a mismatched timestamp; (C) post-insert UPDATE —
two writes and a window between them.

### Format normalization (measured, not assumed)

`whisper_log.logged_at` is Python isoformat — `'2026-08-28T17:36:44.454369+00:00'`, 75,836/75,836
rows with `T` — while `datetime('now')` produces `'2026-08-28 17:36:44'`. The Python consumer
(`fromisoformat`, `:2357`) accepts both; what breaks on mixed formats is the sweeper's
**lexicographic SQL** (`reinforcement_retry.py:52-54`: `claimed_at < datetime('now', '-5 minutes')`,
`ORDER BY COALESCE(last_attempt_at, claimed_at)`, and the `db.py:226` index), where `'T'` (0x54)
sorts above `' '` (0x20). SQLite's `datetime()` normalizes the isoformat value — offsets included
(`-03:00` shifts to UTC; verified by execution) — to exactly the `datetime('now')` shape, so every
`claimed_at` stays space-format UTC.

Malformed `logged_at` → `datetime()` returns NULL → `COALESCE` falls back to `datetime('now')`:
the row keeps today's behavior instead of aborting the whole backfill transaction (`claimed_at` is
NOT NULL) or orphaning the signal forever (the cutoff advances regardless). Dead case in production;
decided with André 2026-08-28.

### Scope decision

Backfill only (decided with André 2026-08-28). Live claims keep `datetime('now')`: their skew is
minutes (session-local feedback), below FSRS-cooldown noise, and changing their clock would touch
the semantics of every source (explicit/implicit/judge) — new scope with no finding behind it.

### Hostile cases — already guarded, verified by reading

- Historical `now` earlier than the node's `last_review` → `reinforcement_due` returns `False`
  (negative delta < cooldown); stability untouched, `last_review` never moves backwards.
- `days_since` is clamped `max(…, 0.0)` (`:2380`).
- The I1 clamp keeps `last_accessed` from walking backwards on out-of-order sweeps.

### Tests (walked through; each RED asserted against the target bug)

1. **The council-demanded test:** node with `last_accessed` between the signal's `logged_at` and
   boot time → backfill must NOT advance `last_accessed` to boot time. RED today: the claim stamps
   `now` > `last_accessed`, and I1 preserves the jump.
2. Backfilled claim carries `claimed_at` equal to `logged_at` normalized — space-format UTC, no
   `'T'` — pinning the sweeper's lexicographic contract. RED today (stamps boot time, and would
   stamp `T`-format if copied raw).
3. Malformed `logged_at` → the claim is still created, stamped `now`. Honest note: GREEN before the
   fix (the bug never reads `logged_at`); it pins the COALESCE against future regression — without
   it the INSERT raises `IntegrityError`.
4. Live claim still stamps `now` (default-path guard; GREEN before and after).

## Fix 2 — load the node inside the write transaction

### Problem (verified by diff reading)

`node = self.file_store.load(node_id)` sits at `:2295`, before `with self.db.transaction()` at
`:2309`. `BEGIN IMMEDIATE` can block up to `busy_timeout=5000` ms (`index/db.py:38`) between load
and save — a window this diff widened (load and save were contiguous before it), not inherited.

### Mechanism

Move the `load` inside the transaction, immediately after the at-most-once latch
(`SELECT changes() == 1`, `:2317`). The orphan check (`node is None`, `:2335`) already lives inside
and keeps working. The docstring's justification for file I/O inside the transaction (`:2297-2301`)
already covers it — the `save` is already there; adjust the comment to match the new position.

### What this delivers — stated honestly in the commit

Restores the pre-diff contiguity. It does NOT fix the pre-existing dual-writer race: load and save
remain non-atomic across processes (FOLLOW-UPS "assumed rather than measured" already tracks the
two-binary story).

### Test

Claim already `'applied'` (latch fails) → `file_store.load` must NOT be called. RED today: the load
runs unconditionally before the transaction. This is the observable behavior pinning the load's
position; it also removes a wasted file read on every latch miss.

## Out of scope

- The dual-writer cross-process race (pre-existing; tracked in FOLLOW-UPS).
- Live-claim clock semantics.
- The 11 deferred findings in `docs/superpowers/plans/2026-08-27-issue-272-heuristic-confirmed-use/FOLLOW-UPS.md`
  (M7 is adjacent to fix 2 but does not conflict).
- No repair migration: `confirmed_use_claims` does not exist in production yet (branch unmerged);
  the 42 signals are still unclaimed.

## Verification

- Full suite + ruff after each commit, run the island way
  (`HOME=$(mktemp -d …) .venv/bin/python -m pytest tests/ -q`); allowed baseline: only the
  environmental trio `tests/test_setup.py::TestConfigureCodexMcp::*` (3 failed / 2050 passed today).
- After both commits: `/council-pr --skip-preflight-tests` with `DIFF_BASE=40d8ff0`
  (stacked branch — default diff-base resolution would drag the 8 commits of #218).

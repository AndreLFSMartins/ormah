# Admit `auto_heuristic` to Confirmed Use, Above an Evidence Floor — Design

**Issue:** [#272](https://github.com/r-spade/ormah/issues/272) · **Depends on:** [#218](https://github.com/r-spade/ormah/issues/218) (PR [#273](https://github.com/r-spade/ormah/pull/273), still open)
**Date:** 2026-08-27

> **Every address in this document was read from `fix/218-signal-strength-ladder` (`40d8ff0`), not
> from `local-main`.** This is not a formality — it repeats the correction the #220 spec had to make
> after its first attempt failed for exactly this reason. Measured: `local-main` is 841 commits ahead
> of `upstream/main`, and against the branch this work builds on, `session_watcher.py` differs by
> **1581 lines** and `memory_engine.py` by **1557 lines**. Every `local-main` line number is wrong
> here by construction. `src/ormah/signal_strength.py` is byte-identical between the two and needs no
> such care.

---

## 1. Problem

`_record_whisper_usage_signals` writes a positive signal and an affinity row for a heuristic hit and
stops. Only the LLM-judge block takes the confirmed-use claim
(`session_watcher.py:603`). Because a heuristic hit also *suppresses* the judge
(`session_watcher.py:505`), the most confident detector is the only one whose positive verdict cannot
advance a memory's lifecycle — and it blocks the one path that would.

Measured on a live store: **0 of 1,629** positive heuristic pairs took a claim. The heuristic carries
81% of all positive volume.

`_record_confirmed_use` is the only `archival → working` transition in the codebase, so this is the
difference between a memory being reinforced and being buried.

## 2. Why the issue's own "minimal fix" does not work

The issue proposes calling `_claim_confirmed_use` in the heuristic block. That call returns `False`
in silence: `_CONFIRMED_USE_SOURCES` (`memory_engine.py:57`) omits `auto_heuristic`, and the gate at
`memory_engine.py:2764` is fail-closed on source.

The omission is **deliberate**, not an oversight. The #220 design states it in terms of its own
successor: *"`auto_heuristic` stays excluded until #218 provides signal calibration."* Its contract 12
pins the exclusion (`test_session_watcher.py:2405-2441`).

Issue #218 has now delivered that calibration. `signal_strength.py` gives each heuristic match kind a
disjoint band: `node_id` 0.98, `title` 0.94, `sentence` 0.92, `token_overlap` 0.40–0.78 (asymptotic,
supremum unreachable in practice). The precondition is met, so the exclusion can be lifted — but on
the terms #218 established, not unconditionally.

**This design does not land before #273 does.** The island is cut from
`fix/218-signal-strength-ladder`; see §7.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Admit `auto_heuristic`, gated on `strength >= 0.80` | 0.80 is the `implicit` rung. It admits the three verbatim match kinds and excludes `token_overlap` *by construction* — that band's supremum is 0.78 — so no second, categorical allowlist is needed. The ordinal ladder #218 built is reused as the gate rather than duplicated. |
| D2 | The floor lives inside `_claim_confirmed_use`, not in its callers | The function's own docstring states the principle: enforced centrally *"so a future fourth caller cannot reopen the hole."* |
| D3 | The judge is suppressed only when the event is (or is about to be) confirmed | A weak `token_overlap` hit is `referenced = True` but confirms nothing. Today it is *also* denied the judge — leaving it with no confirmation route at all. That is the 1,587-row majority of the defect. |
| D4 | Backfill historical rows | The defect already ran in production. Code alone fixes only future whispers; the exact-match rows already written would stay unclaimed forever, because the gate runs at write time. |

### 3.1 Why `submit_feedback` needs no special case

`submit_feedback(+1, auto_heuristic)` computes its strength through
`signal_strength.feedback_strength("auto_heuristic", 1)`, and `_FEEDBACK_LADDER` maps that source to
`UNKNOWN` (0.40) — below the floor, always. Contract 9
(`test_confirmed_use_contract.py:247`) therefore keeps passing unchanged; only its docstring, which
says "excluded pending #218", needs correcting. This is a property of the ladder, not a coincidence:
a `submit_feedback` call carries no evidence of a verbatim match, so it cannot earn a verbatim rung.

## 4. Changes

### 4.1 `memory_engine.py`

- `:57` — `_CONFIRMED_USE_SOURCES` gains `"auto_heuristic"`.
- New module constant `HEURISTIC_CONFIRM_FLOOR = signal_strength.IMPLICIT` (0.80). Defined by
  reference to the ladder, so the two cannot drift apart silently.
- `:2722` — `_claim_confirmed_use` gains a keyword-only `strength: float` parameter. The fail-closed
  guard at `:2764` gains one clause, applied to `auto_heuristic` only:

  ```python
  if whisper_log_id is None or signal != 1 or source not in _CONFIRMED_USE_SOURCES:
      return False
  if source == "auto_heuristic" and strength < HEURISTIC_CONFIRM_FLOOR:
      return False
  ```

  The source is a literal here, matching `_CONFIRMED_USE_SOURCES` two lines above it.
  `_HEURISTIC_AFFINITY_SOURCE` is `session_watcher`'s constant (`:43`) and `memory_engine` does not
  import it; reaching for it would invert the dependency — the engine does not know about the watcher.

  Scoped to one source deliberately: `explicit` (1.00) and `implicit` (0.80) clear the floor anyway,
  but `auto_llm_judge`'s band floor is 0.82 and an unqualified judge row is polarity 0 — already
  rejected by `signal != 1`. Applying the floor to every source would add a second gate on paths that
  do not need one, and would couple the judge's band to a constant it does not own.
- `:2812` — `_submit_feedback_locked` passes the strength it already computes at `:2895` to the
  claim. The only change is hoisting that call above the claim; the value is identical.
- `:2121` — `_record_confirmed_use` is **untouched**.

### 4.2 `session_watcher.py`

- `:439-457` — the row query gains an `EXISTS` subquery, `already_confirmed`, over
  `confirmed_use_claims` for the `(whisper_log_id, node_id)` pair.
- `:486-506` — the loop tracks whether this event confirms:

  ```python
  if not has_heuristic:
      referenced, strength, evidence = _node_usage_evidence(row, response)
      ...
      confirms = referenced and strength >= HEURISTIC_CONFIRM_FLOOR
  else:
      confirms = False
  if llm_judge_enabled and not has_llm_judge and not (confirms or row["already_confirmed"]):
      llm_groups.setdefault((prompt_text, response), []).append(row)
  ```

  `already_confirmed` is what makes the re-ingest path correct: on a second pass `has_heuristic` is
  true, the local strength is not in scope, and the claim table is the only authority on whether the
  event already confirmed. It also closes the cross-caller case `has_llm_judge` is structurally blind
  to — a positive `submit_feedback` through MCP — which is the same blindness #220's contract 13a
  documents.

- `:508-529` — inside the existing transaction, a positive heuristic record takes the claim after
  `_insert_affinity`, collecting confirmed node ids:

  ```python
  if record["polarity"] == 1:
      _insert_affinity(conn, row, signal=1, source=_HEURISTIC_AFFINITY_SOURCE, confirmed_at=now_iso)
      if engine._claim_confirmed_use(
          conn, row["id"], row["node_id"],
          signal=1, source=_HEURISTIC_AFFINITY_SOURCE, strength=record["strength"],
      ):
          heuristic_confirmed_ids.append(row["node_id"])
  ```

  Ordering is load-bearing and already documented at `:598-602`: `_insert_affinity` must precede the
  claim, because the claim helper reads `changes()` and nothing may sit between its INSERT and that
  read.

- A reinforcement loop for `heuristic_confirmed_ids` runs **after** that transaction closes and
  **before** the `if not llm_groups: return recorded` early return at `:531`. It must be its own loop,
  not the judge's at `:623`: that early return means the judge's loop never runs when there is nothing
  to judge — which, after D3, is the common case for a confirming heuristic hit. Per-node
  `try/except`, logged and never raised, matching `:623-627`.

### 4.3 Backfill — `_migrate_heuristic_confirmed_use`

Called from `_open_or_create` immediately after `_migrate_signal_strength()`
(`memory_engine.py:167`), whose incremental-cutoff pattern it copies: a `meta` version key plus a
`signals.id` cutoff, rescanning on every boot rather than stamping once. The #218 migration documents
why — an old binary (a rollback, or the second unmanaged process of #238) can write pre-fix rows
*after* a one-time stamp is set, and those rows would stay unclaimed forever on a table the stamp
calls migrated.

**Ordering is a correctness requirement, not tidiness:** this migration reads `signals.strength`, and
`_migrate_signal_strength` is what normalises that column onto the ladder. Running before it would
read pre-ladder values against a ladder-derived floor.

Selection: `signals` rows where `source = 'transcript_watcher_heuristic'`, `polarity = 1`,
`strength >= HEURISTIC_CONFIRM_FLOOR`, `id > cutoff`, joined to `whisper_log` on `was_injected = 1`,
with no existing claim.

Structure mirrors §4.2: claims inside one transaction, reinforcement in a per-node `try/except` loop
after it commits. The lock-ordering rule from #220 §4.3 applies unchanged — `_record_confirmed_use`
does file I/O and must never run inside an open transaction.

Expected volume on the measured store: **42 pairs** (29 `node_id`, 13 `sentence`, 0 `title`) out of
1,629. The 1,587 `token_overlap` rows are correctly left alone by D1.

## 5. Verification

Every test below is written before its implementation and must fail first.

| # | Case | Expected |
|---|---|---|
| 1 | Watcher, heuristic `node_id` match, judge disabled | claims; lifecycle advances. **This is the issue's acceptance criterion and fails on a clean base.** |
| 2 | Watcher, heuristic `title` / `sentence` match | claims (parametrized with 1) |
| 3 | Watcher, heuristic `token_overlap` match | does **not** claim, **and is queued for the judge** |
| 4 | Watcher, heuristic exact match, judge enabled | claims, and the event is **not** queued for the judge |
| 5 | Floor boundary: `strength` exactly 0.80 vs 0.79 | claims / does not |
| 6 | `token_overlap_strength(r)` across the observed range and beyond | always `< 0.80` — pins D1's by-construction property. Computed: r=7.583 (the observed max) → 0.779681; r=37 (where float64 reaches the supremum) → 0.780000. No reachable ratio clears the floor. |
| 7 | Same transcript ingested twice | claims **once** (`already_confirmed` suppresses the second) |
| 8 | Prior `submit_feedback(+1, implicit)`, then heuristic exact match on that event | claims once; the judge is not queued |
| 9 | Contract 9 (`submit_feedback(+1, auto_heuristic)`) | unchanged — still does not confirm (§3.1) |
| 10 | Contract 12 (`test_session_watcher.py:2405`) | **rewritten, not deleted**: exact match now confirms; `token_overlap` does not |
| 11 | Watcher batch where node 1's mutator raises `ZeroDivisionError` | node 2 still reinforced; `recorded` unaffected |
| 12 | Backfill: run twice | second run claims nothing, reinforces nothing |
| 13 | Backfill: cutoff advances to highest processed id, not `MAX(id)` | pinned as in #218 |
| 14 | Backfill: one node's mutator raises | remaining nodes still reinforced |
| 15 | Backfill: `strength` below floor / `was_injected = 0` / claim exists | skipped in each case |
| 16 | Backfill: signal whose `node_id` differs from its event's `node_id` | no claim, no reinforcement |
| 17 | Backfill: ineligible trailing rows (polarity 0, non-injected) | cutoff still clears them |
| 18 | Backfill reached through `startup()`, ladder-first | a stale `DEFAULT 1.0` `token_overlap` row does **not** claim; a stale 0.50 `node_id` row does |

Cases 16–18 came from the Dev Council (2026-08-27) and each pins a defect the first draft had:

- **16** — `_claim_confirmed_use` inserts the node id it is *handed*, verifying only `was_injected`;
  it never asserts the node belongs to the event. The live path is safe because its query reads both
  ids from one `whisper_log` row, but the backfill reads them from different tables.
- **17** — any eligibility predicate left in the `WHERE` hides those rows' ids from the loop, so the
  cutoff stalls behind them and every boot rescans a growing tail.
- **18** — the sharpest one: `signals.strength` is `REAL NOT NULL DEFAULT 1.0` (`schema.sql:174`), so
  every pre-ladder row sits **above** the 0.80 floor. Ordering this migration after
  `_migrate_signal_strength` is therefore a safety requirement — running it first would confirm every
  stale positive heuristic row in the store, and the claim is a monotonic latch with no undo.

Gate: the failing-test baseline is measured **once in the worktree at the start** and is shared input
to every task. "Tests pass" means no test ID outside that list fails. `make lint` before each commit.

## 6. Out of scope

The affinity boost's unweighted mean (#246) · the `submit_feedback` fallback window (#242) · the
reinforcement formula (#221) · any change to the ladder's bands or to `_record_confirmed_use`'s body ·
promoting `token_overlap` to a confirming channel by any other route.

## 7. Where the work happens

Per `FORK-WORKFLOW.md`:

- Worktree at `../ormah-wt-272` on `fix/272-heuristic-confirmed-use`, cut from
  **`fix/218-signal-strength-ladder`** — *not* `upstream/main`, which lacks `signal_strength.py`
  entirely (verified: `git cat-file -e upstream/main:src/ormah/signal_strength.py` fails).
- Never `git checkout` a contribution branch inside `Tools/ormah` — launchd `com.ormah.server.dev`
  serves that directory.
- Push to `fork`, never `upstream`.
- **The PR declares its dependency on #273 in the body.** While #273 is open, this PR's diff carries
  #218's commits; once #273 merges, rebase the island onto `upstream/main` so the diff reduces to this
  change alone.

### 7.1 A merge-down risk that does not exist in this PR

Council round 1 raised archival resurrection and, on round 2, withdrew it for this base — correctly.
On `fix/218-signal-strength-ladder`, `_record_confirmed_use` (`:2121`) mutates only `stability`,
`last_review`, `last_accessed` and `access_count`; there is no `TierManager.promote`, no `tier`
assignment, and `archived_at` does not exist upstream at all.

**On `local-main` it is a different function.** At `:2884` it promotes `archival → working` through
`TierManager.promote` and clears `archived_at` — the code's own comment says "local-main only (#28)".
So when this work merges down into the branch the Beta actually runs, the boot backfill will
**resurrect archived nodes in bulk on the next restart**, stamping decades-old use as `now`.

That is out of scope for this PR and must not be designed around here. It is recorded so the
merge-down is a decision rather than a surprise: before merging into `local-main`, decide whether the
backfill should skip `tier = archival`, and remember that the daemon restarts under launchd
`KeepAlive`, so the migration runs the moment the branch goes live.

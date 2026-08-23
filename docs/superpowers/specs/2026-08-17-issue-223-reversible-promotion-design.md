# Design — Issue #223: reversible promotion and the seven-day initial lease

**Issue:** [r-spade/ormah#223](https://github.com/r-spade/ormah/issues/223)
**Landing order:** #220 (PR #234) → #222 (PR #235) → #221 (PR #239) → **#223**
**Decision source:** #191 (closed design decision), transcribed in
`docs/lifecycle/2026-08-14-issue-dossier.md` §4 (#223 section, lines 172-201).
**Depends on:** #220 (confirmed-use semantics) and #221 (bounded reinforcement) — both still
open upstream at the time of writing. **Amendment 2026-08-23:** all three have landed
(issues #220 via PR #234, #222 via PR #235, #221 via PR #239); `upstream/main` at `90c431e` carries every symbol this spec names
(`_record_confirmed_use`, `_CONFIRMED_USE_SOURCES`, `LIFECYCLE_MODEL_VERSION`, `lifecycle.py`) and
none of #223's (`superseded_by`, `promotion_floor` — verified by `git grep` on `upstream/main`).

## Problem

Archival is one-way. `TierManager.promote()` exists in `src/ormah/engine/tier_manager.py` but has
no production caller — `enforce_core_cap` is the engine's only `TierManager` call site. A node
deliberately recalled from archival cannot return to the whisper-eligible working tier.

New nodes also ignore the configured initial stability. `fsrs_initial_stability` is validated by
`_fsrs_finite` and `_fsrs_positive`, but `remember()` never passes it, so the node takes
`MemoryNode.stability`'s `Field(default=1.0)`. At the default `fsrs_decay_threshold = 0.3`,
`S = 1` reaches `R < 0.3` after `1.2039728` days ≈ **28.9 hours** — a new memory becomes a decay
candidate on its second day.

Finally, the originally proposed blanket exclusion of every `derived_from` target is too broad.
`derived_from` is a general relationship; only the consolidation sources the consolidator demotes
were actually superseded.

## Decision (from #191)

- Default initial stability `-7 / ln(0.3) = 5.814085` → rounded default **`5.814`**, giving a
  mathematical seven-day unused working window.
- Use `fsrs_initial_stability` at node creation **and** as the promotion floor.
- Promote `archival → working` on confirmed use from `recall_node` or source-qualified positive
  feedback.
- Compute bounded reinforcement from the **old** stability first, then apply the floor:
  `1 → 2` (bounded), then `2 → 5.814` (floor).
- Confirmed use + reinforcement/floor + promotion = **one atomic lifecycle operation**.
- Do **not** rescale existing stability values just because the default is now wired.
- Record explicit consolidation/supersession provenance; block automatic promotion only for
  those sources.

## Branch strategy

> **Superseded 2026-08-23.** Both dependencies landed upstream before any #223 commit existed, so
> the island `feat/223-reversible-promotion` (worktree `../ormah-wt-223`) was reset with
> `git reset --hard upstream/main` to `90c431e` — a plain Recipe A island, no dependency merges,
> no rebase. `git log --oneline upstream/main..HEAD` is empty at the start of implementation. The
> subsection below is kept as history of the conflict resolution; its instructions no longer apply.
> One behavioural delta from the landed #221 matters to this spec: `_record_confirmed_use` now
> anchors the spacing factor on `last_accessed or last_review` (commit `e13d733`), while the
> cooldown gate still reads `last_review`. The worked examples in the test table were updated
> accordingly.

Issue #223 needs #220 and #221 code, and neither has landed upstream. The island is cut from
`upstream/main` and takes both dependencies as explicit merges, so the dependency boundary is one
identifiable commit:

```bash
git fetch upstream
git worktree add -b feat/223-reversible-promotion ../ormah-wt-223 upstream/main
cd ../ormah-wt-223
git merge --no-ff fix/220-confirmed-use          # dep 1
git merge --no-ff fix/221-bounded-reinforcement  # dep 2 → record this SHA
# #223 commits stay linear above it
# once PRs #234 and #239 land:  git rebase --onto upstream/main <dep-SHA>
```

**Verified:** `upstream/main` is an ancestor of both dependency branches (merge-base `a28837b`),
every commit on them is authored by `andrema2`, and neither carries `docs/lifecycle/`,
`docs/superpowers/`, or `.council/`. The island therefore inherits nothing local-only, and
`git log --oneline upstream/main..HEAD` shows only our own commits.

**Known hazard:** `docs/lifecycle/` is tracked on `local-main`, absent from `upstream/main`, and
**not** matched by the `PROTECTED` allowlist in `.git/hooks/pre-push` (tested against the regex).
The hook will not stop that directory from shipping. Do not edit the dossier inside the #223
worktree.

### What the dependency merge required

`fix/220-confirmed-use` merged clean. `fix/221-bounded-reinforcement` conflicted in
`memory_engine.py`, semantically rather than textually: #220 renamed `_touch_access` to
`_record_confirmed_use` and put it behind the at-most-once claim, while #221 was cut from
`upstream/main`, where the method still carries the old name, and replaced the unbounded formula
with the bounded one. Three hunks, resolved as follows.

- Two module constants, `_CONFIRMED_USE_SOURCES` (#220) and `LIFECYCLE_MODEL_VERSION` (#221) —
  independent, both kept.
- The definition takes #220's name with a docstring covering both concerns. The callers are cited
  **by name**, not by line, and #221's lock-order list was corrected: it named
  `_ensure_self_node`, which calls `file_store.save` *before and outside* its `db.transaction()`,
  so it does not belong. Verified on the island that only `_seed_stability_from_access_count` and
  `_migrate_identity_tiers` call `file_store` inside a transaction.
- The body takes #221's bounded update, with the zero-stability rationale folded into its comment
  because `lifecycle.reinforced_stability` now owns that case.

Two follow-on fixes the conflict did not surface: `tests/test_engine/test_reinforcement_cooldown.py`
called `engine._touch_access` in ten places, and its concurrency-test docstring asserted a fact
about the callers. Verified before rewriting it that none of `recall_node`, `submit_feedback`, or
the session watcher's `_record_whisper_usage_signals` carries
`@_serialized_memory_operation` — so the claim still holds, and the added clause is that #220's
latch is per whisper event, not per node, which is why two events for one node still race.

### Reference style

Code references in this document name **symbols**, not line numbers. `local-main` and the island
diverge by hundreds of commits, so a line number read off one is wrong in the other — and edits
made while implementing invalidate them again. Symbol names survive both.

## Changes

### 1. `src/ormah/config.py`

`fsrs_initial_stability: 1.0 → 5.814`, with `-7 / ln(0.3)` recorded in the line comment. It stays
a directly configured knob rather than one derived from `fsrs_decay_threshold`: the acceptance
criterion asserts the seven-day lease at *the default* threshold, and calls the value *the
configured* initial stability. Existing validators (`_fsrs_finite`, `_fsrs_positive`) already
cover it.

### 2. `src/ormah/lifecycle.py`

One new pure function, matching the module's contract (no I/O, no settings, no database):

```python
def promotion_floor(stability: float, initial_stability: float) -> float:
    """``max(S, initial)`` — the lease a promoted node restarts from."""
```

`max`, never a sum. That is what makes "the post-update floor does not amplify the same event
into a longer-than-initial lease" structural rather than incidental, and makes repeated
promotions idempotent.

### 3. `src/ormah/models/node.py`

`superseded_by: str | None = None` — the id of the consolidation node that replaced this one.
Deliberately **not** exposed in `UpdateNodeRequest`: this is policy state, and no agent writes it.

### 4. `src/ormah/store/markdown.py`

Serialize only when not `None`, following the existing optional-field pattern; parse via
`meta.get("superseded_by")`.

### 5. `src/ormah/index/schema.sql` and `src/ormah/index/db.py`

`superseded_by TEXT` on `nodes`, plus one entry in the `_migrate` pair list in `db.py` —
`PRAGMA table_info`-guarded, so it is idempotent and existing rows stay `NULL`.

### 5b. `src/ormah/index/builder.py` — amendment, 2026-08-18

**Added after approval.** The original list of seven files missed this one, and without it the
column added in §5 is written and immediately erased.

`IndexBuilder._index_file_nodes_only` runs `INSERT OR REPLACE INTO nodes` with an explicit column
list. In SQLite `REPLACE` is DELETE + INSERT, so a column absent from that list is recreated at its
`DEFAULT` — `NULL`. The consolidator (§7) marks a source and then calls
`update_node(tier=archival)` on the next line, which calls `builder.index_single`: the marker is
wiped from the index inside the same loop iteration that wrote it.

`superseded_by` must therefore join the column list, the `?` placeholders, and the value tuple.

Severity, stated honestly: this does **not** break the promotion gate. That gate reads the Markdown
via `file_store.load`, and the file keeps the marker, so a superseded node stays blocked either way.
What breaks is the index column: permanently `NULL`, which is a lie told to the SQL consumer this
spec names in §5 (#209).

### 6. `src/ormah/engine/memory_engine.py`

The promotion lives inside `_record_confirmed_use`, after the #221 cooldown block and before the
`# Standard access tracking` lines:

```python
if node.tier is Tier.archival and node.superseded_by is None:
    node.stability = lifecycle.promotion_floor(
        node.stability, self.settings.fsrs_initial_stability
    )
    self.tier_manager.promote(node, Tier.working)
```

Three sub-decisions:

**The floor runs even when the cooldown blocked the numeric update.** Otherwise a second
confirmed use on the same day promotes with the old `S = 1`, buying a ~29-hour lease, and the
next decay run demotes the node straight back. The floor is `max` against a constant, so running
it on every promotion cannot push stability past one initial lease.

**The tier flip goes through `TierManager.promote()`** rather than assigning `node.tier`. This
gives #223's root cause its first production caller and brings the tier-ordering guard along.
Visible, deliberate consequence: `promote()` calls `touch_updated()`, so `updated` advances. That
is correct — the tier genuinely changed, and `updated` feeds LWW sync (see the no-op guard comment in `update_node`);
not advancing it would let a stale remote copy win and silently re-archive the node. `updated`
therefore joins the UPDATE.

**No `archived_at` handling — the field does not exist upstream.** Verified on the island:
`archived_at` appears nowhere in `src/` or `tests/`, is absent from `schema.sql` and from the
`_migrate` pair list, `update_node`'s tier block is a bare `node.tier = req.tier`, and
`background/forgetting_manager.py` does not exist. All of that is #28, which is local-only work on
`local-main` and not in `upstream/main`. There is therefore nothing to extract into a shared
helper, no column to write, and no purge queue for a promoted node to leave.

The existing targeted UPDATE gains two columns, with no branching — on the non-promoting path
both values are the ones already on disk:

```sql
UPDATE nodes SET access_count=?, last_accessed=?, stability=?, last_review=?,
                 tier=?, updated=? WHERE id=?
```

No `builder.index_single`, no `_index_embedding`: content did not change and the UPDATE already
carries every column that moved. When — and only when — a promotion happened, one
`_write_audit_log(operation="promote", ...)` runs after the transaction closes, in the same
position `update_node` places its own (`_write_audit_log` opens its own transaction, so it cannot
sit inside).

Also here: `_mark_superseded(source_id, consolidation_id)`, a serialized operation that sets the
field on the loaded node, saves the markdown, and writes the `superseded_by` column in one
transaction — needed because the field deliberately does not travel through `update_node`. And a
comment in `_lifecycle_model_version` recording why #223 does not bump the version.

### 7. `src/ormah/background/consolidator.py`

Mark `superseded_by` **before** demoting, in the `derived_from` + demote loop that closes `_apply_consolidation`. The order is the fail-safe:
crashing between the two leaves the node `working` + marked, which is harmless because the marker
only blocks *automatic* promotion. The reverse order would leave it `archival` + unmarked —
exactly the promotable node we do not want. `derived_from` is untouched, which is what gives
"a generic `derived_from` target can promote" for free.

## What deliberately does not change

Three independent `1.0` defaults stay: `MemoryNode.stability`'s `Field(default=1.0)`, `parse_node`'s
`meta.get("stability", 1.0)` fallback, and `stability REAL DEFAULT 1.0` in `schema.sql`. Changing any of
them would retroactively rescale nodes that never carried the field, which #191 forbids. Only
`remember()` gains `stability=self.settings.fsrs_initial_stability`.

The `Self` node built by `_ensure_self_node` keeps `1.0` and is unaffected: it is `core`, and
`run_decay` queries `tier = 'working'` and additionally skips `user_node_id`.

`lifecycle_model_version` stays at `2`. Nothing reads it on the promotion path and no existing
data is rewritten — the `PRAGMA`-guarded `ALTER` is self-describing and idempotent. The version
records *which reinforcement model wrote this store*, and #223 does not change the reinforcement
model; it changes a creation default and adds a column. It would not help even hypothetically:
it is a store-level flag, and a real store spans both eras of nodes. Recorded as a decision, not
an omission, with a test pinning the value.

## Concurrency and failure

`run_decay` holds `_memory_operation_lock` for its whole run (`serialized_memory_job` →
`engine.memory_operation()`), and `_record_confirmed_use` takes the same `RLock`
(`_memory_operation_lock`, created in `MemoryEngine.__init__`). **Verified:** decay and promotion cannot interleave in-process, in
either direction — decay takes its `tier='working'` snapshot under the lock, so it cannot see a
node promoted after it; and a node promoted before the snapshot appears in it with
`last_accessed = now`, so `R ≈ 1` and decay skips it.

**That guarantee is inherited, not built here — and it is under review.** #223 adds no exclusion
of its own. It relies entirely on a lock that
[#240](https://github.com/r-spade/ormah/issues/240) documents as a starvation defect, and whose
proposed fix is precisely to stop background jobs from excluding the foreground. Recorded as a
dependency rather than as a settled property, so the coupling is visible to whoever lands either
change:

- **What breaks if the lock stops excluding.** `run_decay` reads its snapshot outside any
  transaction (`decay_manager.py:28-31`) and demotes row by row afterwards
  (`decay_manager.py:76`). A node whose confirmed use lands between the snapshot and its own
  demotion would be archived on stale data — losing the seven-day lease #223 exists to grant, one
  instant after the use that earned it. Today the lock makes that interleaving impossible.
- **What #223 would then need, and why it is not sketched here.** The fix shape is a revalidation
  inside the demoting write: demote only if the node's `last_accessed` still matches the snapshot.
  But `update_node` takes no guard parameter, and the guarded-mutator precedent
  (`delete_node_guarded`) is **local-only (#28) and absent from this island** — verified, 0
  occurrences in `memory_engine.py` on `feat/223-reversible-promotion`. So this is not a small
  edit; it is its own design question, left open deliberately rather than answered with an
  unreviewed sketch. It becomes required work only if #240 lands a fix that removes whole-run
  exclusion.

The issue's acceptance criterion — *"concurrent promotion/decay cannot leave markdown and index
lifecycle state inconsistent"* — is met today by the lock. This section exists so that it is not
met *accidentally*.

Two further limitations, stated rather than hidden:

**No cross-process exclusion.** A CLI running alongside the server does not share the `RLock`.
This is a pre-existing property of `_memory_operation_lock`, not something #223 introduces. The
guarantee holds inside the server process, where both paths live (scheduler thread + request
thread).

**A window between file and index.** If `file_store.save` succeeds and the UPDATE fails, markdown
says `working` while the index says `archival`. Markdown is the source of truth and the
`index_updater` job reconciles by `file_hash` every **1 minute** (the `index_updater` job in
`scheduler.py`, running `builder.incremental_update`); in that window the node is merely not whisper-eligible. This is the existing
behaviour of every field the method already writes.

All three callers already wrap `_record_confirmed_use` in `try/except` and never propagate
(at-most-once, logged miss). A lost promotion stays a logged miss: the claim remains taken and
will not retry. Same contract #220 established; no new failure mode.

## Acceptance criteria → tests

Qualification needs no new logic. `_claim_confirmed_use` already
fail-closes on `signal == 1`, `source ∈ _CONFIRMED_USE_SOURCES` = `{explicit, implicit, auto_llm_judge}`,
`was_injected == 1`, and at-most-once — and all three callers pass through it. Promotion placed
inside `_record_confirmed_use` inherits "unqualified sources do not promote" for free. The tests
below exist to stop a future fourth caller from reopening the hole.

Each entry names the concrete worked example, and ⚠️ marks assertions that would *not* catch the
target bug.

The #223-specific behaviour tests live in a new `tests/test_engine/test_reversible_promotion.py`.
Everything else extends the file that already owns the concern.

| Criterion | Test | Worked example |
| --- | --- | --- |
| Seven-day lease | `tests/test_lifecycle.py` | `retrievability(6.5, 5.814) > 0.3`, `retrievability(7.5, 5.814) < 0.3`. With the rounded default the real crossing is at **6.99990 days** (`5.814 × 1.2039728`), ~8.8 s before the 7-day mark, so `retrievability(7.0, 5.814) = 0.29999` is **below** threshold. ⚠️ An assertion of `> 0.3` at `t = 7.0` would fail; asserting `settings.fsrs_initial_stability == 5.814` alone asserts nothing about the lease. |
| Promotion never reduces stability | `tests/test_lifecycle.py` | `promotion_floor(50.0, 5.814) == 50.0`. ⚠️ Equality at `50.0`, not `>= 5.814` — with `>=`, a `min`/`max` swap passes. |
| Creation uses the knob | `tests/test_engine/test_memory_engine.py` | Set `fsrs_initial_stability = 9.0` (a **non-default** value) → `remember()` → `node.stability == 9.0`. ⚠️ Testing with `5.814` would pass by accident if someone also changed the model default. |
| Before scheduler cadence | `tests/test_background/test_decay_manager.py` | `S = 5.814`, `last_accessed = now − 6.5d` → `run_decay` leaves it `working`; at `− 7.5d` it demotes. Drives the real job, not the formula. |
| Bounded update precedes the floor | `tests/test_engine/test_reinforcement_cooldown.py` | Archival, `S = 1`, `last_accessed = last_review = now − 30d` (the spacing anchor is `last_accessed` since `e13d733`; `last_review` only opens the cooldown gate) → `stability == 5.814`. The bounded update gives `1 → 2.0` (spacing saturates at cap `2.0`); the floor lifts `2 → 5.814`. Inverted order would instead give ≈ **8.23** (`5.814 × (1 + 0.5 × 5.814**-0.5 × 2)`), so equality at `5.814` catches the inversion. |
| Floor applies under cooldown | `tests/test_engine/test_reinforcement_cooldown.py` | Archival, `S = 1`, `last_review = now` (cooldown closed, so `reinforced_stability` is skipped) → `tier == working` **and** `stability == 5.814`. ⚠️ Asserting only `tier == working` passes with the bug, and the node would re-archive in ~29 h. |
| Floor does not stack | `tests/test_engine/test_reinforcement_cooldown.py` | Two confirmed uses in one day on an archival `S = 1` node → `5.814`, not `11.628` and not `6.814`. |
| `recall_node` promotes exactly the requested node | `tests/test_engine/test_reversible_promotion.py` | Archival A with archival neighbour B. `recall_node(A)` → A becomes `working`, **B stays `archival`**. ⚠️ Without the neighbour, an implementation promoting every id in `whisper_log_ids` passes — and `recall_node` does create `whisper_log` rows for neighbours, in `_log_feedback_candidates`. |
| Qualified positives only | `tests/test_engine/test_confirmed_use_contract.py` (where #220's matrix lives) | Parametrised: `(1,"explicit",injected=1)` promotes · `(1,"auto_heuristic",1)` does not · `(-1,"explicit",1)` does not · `(1,"explicit",injected=0)` does not. |
| Generic `derived_from` vs superseded | `tests/test_engine/test_reversible_promotion.py` | Two archival nodes, both `derived_from` targets, only one with `superseded_by` → the plain one promotes, the marked one does not. ⚠️ Testing only the marked node misses the block-everything bug the issue explicitly names. |
| Consolidation provenance | `tests/test_background/test_consolidator.py` | Source ends `archival` + `superseded_by == new_id`; plus an ordering test that injects a demotion failure and asserts the node ended `working` + marked, not `archival` + unmarked. |
| Serialization | `tests/test_store/test_markdown.py` | `superseded_by` survives the roundtrip, and is **absent** from frontmatter when `None`. ⚠️ Without the second assertion, writing `superseded_by: null` would pollute every node file. |
| Migration | `tests/test_index/` (pattern of `test_migration_seq.py`) | DB without the column → `_migrate()` adds it, existing rows are `NULL`, running twice is idempotent. |
| No retroactive rescale | `tests/test_store/test_markdown.py` | A file with `stability: 1.0` stays `1.0`; a file with **no** `stability` key parses to `1.0`, not `5.814`. |
| Concurrency | `tests/test_engine/test_recall_concurrency.py` | Thread A runs `run_decay` while thread B promotes; afterwards `tier` in the file equals `tier` in the index. ⚠️ "Did not raise" does not catch divergence — the assertion compares disk against index. |
| `promote()` guard | `tests/test_engine/test_tier_manager.py` | `promote(archival → working)` returns `True`; `promote(working → working)` returns `False` (the guard this design relies on). |
| Audit trail | `tests/test_engine/test_audit_log.py` | Promotion writes one `operation="promote"` entry. |
| Version unchanged | `tests/test_engine/test_lifecycle_model_version.py` | A store written under #223 still reports `2`. |

## Documentation

The PR carries documentation that lives **in the code**: the `superseded_by` field description,
the `promotion_floor` docstring, the promotion paragraph in `_record_confirmed_use`, the
derivation comment on `fsrs_initial_stability`, and the `_lifecycle_model_version` note — plus
the PR body.

Product docs (`docs/01 - Data Model.md`, `docs/05 - Background Jobs.md`,
`docs/12 - Configuration Reference.md`) and `.env.example` are **not** part of this PR. Standing
rule for this repo: docs that are not part of the code do not go upstream; precedent is commit
`f8cb685` on the #220 island ("chore(docs): keep product docs out of the upstream PR"), which
reverted `docs/01`, `docs/04` and `docs/05` to the upstream text. **Verified:** `.env.example` is
referenced by nothing in `install.sh`, `scripts/`, `Makefile`, or `src/`, and lists no `fsrs_*`
knob today — it is a human-readable template, not a consumed artifact.

Consequence, stated once: the issue's acceptance criterion asks that "docs cover the new
provenance/state". In the PR that is satisfied by in-code documentation and the PR body. If the
maintainer asks for the product docs during review, it is a three-file edit added then.

Product docs are updated separately on `local-main`, after the PR — and **by cherry-pick, not
merge**: an ormah memory records that merging a contribution branch into `local-main` can wipe
`docs/superpowers`. That memory's full content could not be loaded (two `recall_node` timeouts),
so it is **an unverified whisper title** — re-confirm before executing.

### Landmine when this reaches `local-main`

`local-main` **does** have `archived_at` and `forgetting_manager` (#28); the island does not. So the
promotion written for upstream is incomplete there: a node promoted out of archival on `local-main`
keeps its `archived_at` timestamp, which leaves a stale graveyard clock on an active node and,
depending on how `forgetting_manager` gates purge eligibility, may leave it purgeable while it sits
in `working`. When cherry-picking #223 onto `local-main`, the promotion must additionally clear
`archived_at` on the node and in the index UPDATE. This is deliberately **not** in the PR — the
column does not exist upstream — and it must not be forgotten locally.

## Out of scope

**#209** (unbounded merge-proposal queue) is *unblocked* by #223 and needs nothing extra from it:
the dossier (§266-268) restricts duplicate candidates to active memories "provided promoted
memories become eligible again", and the tier flip in the index is what #209 will query.

**`start_watcher`** (`src/ormah/store/watcher.py`) has no production caller, and that is already
documented as deliberate in `docs/02 - Storage Layer.md:118-133`. Not touched.

**#218** (strength calibration) is unchanged by #223, which consumes the interim source-qualified
rule.

### Two consequences #223 creates

These did not exist before this change and are recorded here rather than fixed:

1. **#218's interim rule becomes costlier.** Excluding `auto_heuristic` wholesale used to cost
   only *lost reinforcement*. Under #223 a verbatim `node_id`/`title`/`sentence` match on an
   archival node also becomes a *lost promotion* — the node does not come back. The dossier
   records 45 such matches (§226-227); that number is **a dossier record, not a measurement
   taken in this session**, and must be re-measured before it is used as evidence.

2. **#192 plus supersession is a permanent burial.** Today a badly-truncated consolidation
   demotes its sources and they never return, because `promote()` has no caller. After #223
   archival nodes return on confirmed use — except those marked `superseded_by`, which are
   exactly the sources #192 says were harmed. #223 does not regress #192, but it withholds from
   those nodes the escape it grants everything else. The only way out is a manual
   `update_node(tier=working)`. This is accepted under the #191 ruling (supersession blocks
   *automatic* promotion), not a bug to fix here.

Both should be posted as comments on #218 and #192 — GitHub is the durable destination.

## Verification

`make test` green, `make lint` clean, and the concurrency test run repeatedly (it is the one test
whose failure mode is timing-dependent).

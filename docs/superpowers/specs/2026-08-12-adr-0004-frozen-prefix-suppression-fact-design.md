# Suppressing selection with a fact, not with the cursor (ADR-0004)

**Date:** 2026-08-12 · **Status:** approved, not implemented · **ADR:** 0004
**Revised 2026-08-12** after Dev Council rounds 1-3 (cursor + codex). The first draft of this
spec suppressed on a size ceiling (`frozen_until >= size`); the council killed that design and
it is recorded below under *Considered and rejected*. What follows is the identity-based design
the plan implements.

Stop the ingest lane from losing transcript content. Selection suppression moves out of
`end_offset` and into its own state field, so the cursor never claims bytes that were never
ingested.

Out of scope, each its own spec: recovering the content already lost, draining the
dead-letter noise (ADR "Fix A", re-admit-on-growth), the 54 transcripts the parser
cannot close even unwindowed, and the pre-existing identity blind spot in `reconcile`
described under *Residual risks* below.

## The problem, measured 2026-08-12

The spool root is `~/.local/share/ormah/memory/ingest_queue/{66b287858fdea3e3,91da4ace50312981}/`.

> **Provenance correction, 2026-08-13.** The two spool rows below were inherited from a session
> handoff and written here as measurement without an independent route. They can no longer be
> checked: `failed/` was destroyed externally some time between 2026-08-12 and 2026-08-13 08:50
> (nothing in `ingest_spool.py` ever removes a file from `failed/`, and `backup.py` does not cover
> the spool), and it now holds 2 jobs, both created 2026-08-13. Treat those two rows as
> **unverifiable**, not as measurement. The claim they carried — that they superseded the ADR's own
> 2026-08-12 amendment, which "cited two jobs that do not exist in the spool" — is **withdrawn**:
> it can be neither substantiated nor refuted, so the ADR's amendment stands as written.
>
> The state rows are unaffected and one is confirmed: the `end_offset`-only count was re-measured
> on 2026-08-13 by an independent route and is still exactly **75**, against 1815 entries.

| quantity | value |
|---|---|
| dead-lettered jobs / distinct transcripts | ⚠️ unverifiable — inherited as 3806 / 1619, payloads from 2026-07-24 |
| dead-lettered transcripts with cursor already at EOF | ⚠️ unverifiable — inherited as **98%** (median 0 B, p90 0 B) |
| state entries holding only `end_offset` (cursor advanced, nothing ingested) | **75 of 1791** — was 48 of 1485 on 2026-08-09; still 75 of 1815 on 2026-08-13 |
| of those, transcript still on disk | 68, totalling 8,029,774 B |

Parsing each of those 68 transcripts whole, unwindowed, with the project's own
`parse_transcript` splits them cleanly:

- **14 files / 5,923,567 B / 23 closed user turns** — the parser closes content that the
  cursor skipped. This is the defect.
- 54 files / 2,106,207 B — the parser closes nothing even without a window (Codex rollouts
  with no `task_complete`, single-turn sessions). A parser-coverage problem, not this one.

### The mechanism is a ratchet

Read from the boundaries recorded on the dead-lettered jobs themselves:

```text
ab16af53-….jsonl — 24 dead-letters, boundary climbing without pause:
  98,985 → 125,943 → 222,943 → 257,727 → 384,984 → 437,294 → 500,884
       → 676,978 → 694,301 → 877,060 → 971,222 → 1,017,779 → … → 1,435,339
```

⚠️ The step *sequence* above came from the dead-lettered jobs and shares their fate — it cannot be
re-derived now, and neither can the companion counts for `e238fed7` (5 jobs), `d66c054f` (4) and
`ebf4a5ff` (3). **The damage it illustrates is independently verified**, re-measured 2026-08-13
from the transcript and the state file, which are both still present:

| | |
|---|---|
| transcript on disk | `-Users-andre-Documents-GitHub-davos-deck/ab16af53-….jsonl`, **1,435,339 B** |
| whole-file `parse_transcript` | closes **1,434,322 B** in **66** turns |
| its state entry | keys are `['end_offset']` and nothing else — `end_offset = 1,435,339` |

The cursor sits at EOF, no `node_ids` were ever written, and a whole-file parse closes all but
1,017 bytes. That is the defect, end to end, in one entry: `_mark_frozen_prefix_consumed` advanced
the cursor to its own boundary until the file was "consumed" without a single turn reaching the
store.

The trigger varies — the windowed-parse artefact the ADR identified on 2026-08-10, or a
genuinely idle session with an unterminated tail. **The damage does not: every path loses
content at the same step, moving the cursor.** With the cursor held still, all 24 ratchet steps
lose nothing.

## Decision

`_mark_frozen_prefix_consumed` stops writing `end_offset` and writes a suppression fact
instead. Renamed `_mark_frozen_prefix_parked` — the current name asserts the very thing that
causes the loss.

The fact is **three** keys, not one — a ceiling and the identity of the file that was examined:

```python
# session_watcher.py, ~L1553 -- abbreviated; the full body is in the plan, Task 1
def _mark_frozen_prefix_parked(self, path, rel, boundary=None, *, examined: os.stat_result):
    st = path.stat()
    if (st.st_ino, st.st_mtime_ns, st.st_size) != (
        examined.st_ino, examined.st_mtime_ns, examined.st_size
    ):
        return                        # changed under the examination -- never park it
    target = min(boundary, st.st_size) if boundary is not None else st.st_size
    entry = dict(self._state.get(rel, {}))
    same_file = (entry.get("frozen_ino") == st.st_ino
                 and entry.get("frozen_mtime_ns") == st.st_mtime_ns)
    entry["frozen_until"] = max(target, entry.get("frozen_until") or 0) if same_file else target
    entry["frozen_ino"] = st.st_ino
    entry["frozen_mtime_ns"] = st.st_mtime_ns
    _commit_state(...)                # end_offset preserved, untouched
```

`frozen_until` means: *the last examination of this file, up to byte N, closed nothing; do not
re-select it while the file is still exactly the one examined.* It is not a progress offset.

**Identity is what suppresses; the ceiling only bounds it.** A ceiling alone cannot express
"unchanged" (council round 1, both peers, critical/high, verified independently): a rotation to
a size at or below the ceiling, or a replacement at exactly the same byte count, would be
suppressed forever. `st_ino` and `st_mtime_ns` come from the **same** `stat()` that computes
`target`, never a second one.

**The park refuses a file that changed under the examination** (council round 2, codex, high).
`examined` is the stat `_idle_with_unsafe_tail` actually parsed — so that method now returns
`os.stat_result | None` instead of `bool`. A rotation landing between the examination and the
park would otherwise record the *replacement's* identity, and both producers would then classify
a file nobody has ever parsed as frozen-and-unchanged. Writing no fact is always safe: the file
is simply re-selected.

**Monotonicity applies to the ceiling only, and only within one identity.** Two separate council
findings converge here. Identity must always be written, even when the ceiling does not rise
(round 2, cursor, high): after a same-size replacement the producers correctly re-open, the drain
freezes again at the same `target`, and an early return would leave the stale identity in place
forever — every sweep re-selecting and re-dead-lettering. And a ceiling belonging to a *different*
file is not a ratchet guard but a lie (round 3, both peers, the single finding of that round):
file A frozen at 1000, replaced by an unparseable B of size 500, would keep 1000 and could never
re-arm. Guarding on identity also makes `ceiling <= st.st_size` provable rather than defensive.

**Named `frozen_until`, not `parked_until`.** `parked_until` belongs to the force-close design
retracted on 2026-08-09, and two live state entries still carry `parked_*` residue from the
branch that once ran; reusing the name would make this design unreadable against that history.

**Precedent:** `skipped_slices` (`session_watcher.py:1069-1085`) already records a suppression
fact inside the state entry, in the same `os.replace` as the cursor — atomic by construction,
no parallel ledger. The frozen fact follows it — three plain scalars in the same entry, no new
file, no migration.

### Considered and rejected

- **A size-only ceiling** — `frozen_until >= st.st_size` as the whole gate, with no identity
  keys. This was the first draft of this spec. Rejected by council round 1 (cursor + codex, both
  `needs-attention`, verified against the code before being accepted): it is not "re-open on
  growth", it also skips a file that **shrank**, so a rotated transcript would be suppressed
  forever and the shrink reset unreachable through either producer. The Observer lane is what
  catches rotation today precisely because it consults no state, so a size-only gate there was a
  straight regression. The cost of the repair is two extra keys per frozen entry.
- **Fix the predicate only** — have the parser signal "refused by the ceiling" at the three
  `_exceeds_ceiling` breaks (`parser.py:350`, `:381`, `:406`, which today set no flag at all —
  `capped` covers budgets only), so `_idle_with_unsafe_tail` stops misclassifying. Smaller, and
  it addresses the cause the ADR named on 2026-08-10. Rejected as insufficient: it lowers the
  trigger rate and leaves the loss mechanism intact for the genuinely idle tail — which is what
  all six of today's dead-letters are (`boundary == size` on each, so no window was in play).
- **Both** — full coverage of the 2026-08-10 cause. Rejected for now: two coupled mechanisms in
  one spec is the bundling that produced the 56-round cascade behind the retracted force-close.
  The predicate fix stays available as its own spec, on its own evidence.

## Selection suppression

The cursor does two jobs today: record progress, and drop the file from the sweep
(`(entry["end_offset"] or 0) >= st.st_size → continue`, `reconcile` at `session_watcher.py:1622`).
Taking the second job away from it means giving it to **both** producers, not one.

The predicate lives in **one** module-level function, next to `_commit_state`, and both producers
call it. There is deliberately no second copy: a divergent one is how the two lanes drift apart.

```python
def _frozen_unchanged(entry: dict, st: os.stat_result) -> bool:
    """True when this file is still EXACTLY the one the freeze examined, so re-selecting it
    would reproduce the same dead-letter and nothing else."""
    if entry.get("shrink_pending"):
        return False                        # the two-tick shrink gate is mid-confirmation
    if (entry.get("end_offset") or 0) > st.st_size:
        return False                        # cursor above EOF -> the file shrank
    return (
        (entry.get("frozen_until") or 0) == st.st_size
        and entry.get("frozen_ino") == st.st_ino
        and entry.get("frozen_mtime_ns") == st.st_mtime_ns
    )
```

**`reconcile`** gains a second cheap-skip arm; its first arm is left exactly as it is:

```python
elif (entry.get("end_offset") or 0) >= st.st_size and not entry.get("shrink_pending"):
    continue
elif _frozen_unchanged(entry, st):
    continue          # frozen, and byte-for-byte the file that was examined
```

A separate `elif` rather than an `or` on the first: that arm carries the `shrink_pending`
exception, and folding an independent gate into the same expression ties them together.

**The `>=` stays, and that is a change of decision.** Council round 2 (codex, high) asked for
`==`, on correct reasoning: a cursor *above* EOF means the file shrank, which is not "fully
consumed", and while the arm skips on `>=` the shrink gate is armable only through the Observer —
in the one component that exists to recover dropped FSEvents. The final whole-branch review then
measured what `==` would do against the live store, and the change was pulled back out:

- Upstream has used `==` since `4d8de6d` (2026-07-17) and never had `>=`, so the `>=` here is
  Beta-local drift. But upstream pairs `==` with an in-memory retry park (`_reconcile_attempts`,
  keyed on `(size, mtime_ns)`, bounded by `MAX_RECONCILE_RETRIES`) that this codebase does not
  have — 0 occurrences. Nothing here bounds a cursor-above-EOF file whose content is unchanged.
- Measured 2026-08-12 on the live Beta: 16 entries hold a cursor above EOF. Three of them have an
  unchanged hash and would re-enqueue forever (`_ingest_session`'s guard returns `NO_PROGRESS`
  before the shrink branch when the hash matches), re-reading and hashing 5.8 MB every sweep. The
  other 13 would reset to offset 0 and re-ingest 59.0 MB, the largest file being 40 MB.
- Seven of those 13 sit at exactly **83 bytes** above EOF, across files from 392 KB to 40 MB. A
  constant offset across unrelated files is not a shrink; it is an unexplained cursor overshoot,
  and re-ingesting 40 MB over it would be acting on a symptom nobody has diagnosed.

So the repair is real but needs a bound this design does not provide, and it is tracked on its own
evidence rather than carried here. The cost of leaving it: `_frozen_unchanged`'s cursor-above-EOF
escape stays unreachable — which it already was, by the ceiling conjunct, so nothing is lost.

**`_enqueue_path`** (`session_watcher.py:1361`) consults no state at all today — every FSEvent
becomes an `enqueue`. It gains the same call. Gating only the sweep does not fix the defect, it
relocates it: the ADR already recorded this lesson in another form — *"the suppression is applied
in both producer lanes, because gating only the sweep would trade a full `failed/` for a hot
enqueue loop on the Observer lane."*

### Invariants

1. **Any change re-opens.** Growth, shrink, or replacement at the same byte count — all three
   break identity and return the file to selection, and the parse resumes from the **untouched**
   cursor, not from where the ratchet would have left it. This is what collapses `ab16af53`'s 24
   dead-letters into a single ingestion. Suppression is never expressed by a size comparison
   alone (council round 1).
2. **Suppression re-arms.** After a change re-opens the file and the drain freezes it again, the
   park writes the new identity even when the ceiling does not move. Without this the file
   re-selects and re-dead-letters on every tick — an unbounded `failed/`, the failure mode the
   fact exists to prevent (council round 2).
3. **Never lowers, within one identity.** `max()` on write guards against an out-of-order job
   with a smaller boundary re-opening the ratchet. Across identities the new `target` simply
   replaces the old ceiling, or a large frozen file replaced by a smaller unparseable one could
   never re-arm (council round 3).
4. **Never past the accepted boundary.** `target = min(boundary, size)`. Bytes above the
   boundary were never accepted by a nudge, so a later, higher nudge must still be able to
   examine them (council-pr F1, carried over). A consequence: while `frozen_until < size` the
   predicate is false and the file stays selectable — suppression arms only when the whole file
   was examined.
5. **`end_offset` leaves the write.** The committed entry preserves the current cursor by
   construction. `_commit_state`'s monotonic clamp (`:800-808`) stays as the backstop, but must
   not be what enforces this — it clamps `end_offset` only, and this design does not touch that
   field.
6. **A never-seen file stays eligible.** A new entry may be born with the three frozen keys and
   no `end_offset`. `reconcile` evaluates `(entry.get("end_offset") or 0) >= size` → `0 >= size`
   is false for any non-empty file → it falls through to the new gate and is judged there. Legacy
   entries lack the fields, so `_frozen_unchanged` returns false, behaviour unchanged. No
   migration.
7. **A confirmed shrink clears it.** The shrink reset (`session_watcher.py:962-966`) copies
   `dict(existing or {})` and updates only `hash`/`end_offset`. A frozen fact surviving that
   reset describes the file that was rotated away, and both producer gates would act on it. The
   reset must `pop` all three keys.
8. **A successful ingest clears it.** The happy-path commit (`:1284`) carries the whole existing
   entry forward via `dict(existing) if carry else {}`. The fact described a parse that closed
   nothing; this one closed something. A stale ceiling on a healthy entry can only mislead a
   later comparison (council round 1, cursor, medium).

Deliberately unchanged: `spool.requeue(job, failure_class="no_safe_boundary")`. The file still
dead-letters on every freeze and the noise volume stays where it is (~110 jobs/day). That is
Fix A, a separate spec.

## Tests

Test-first. The reproducing test is `ab16af53`'s ratchet in miniature: a transcript whose turn
terminator lands past the job's `boundary`; job 1 freezes; job 2 arrives with a higher boundary.
Today the cursor jumps twice and nothing is ingested. After the change the cursor holds,
`frozen_until` rises, and **job 2 ingests the whole content**. It fails against today's code —
that is the done criterion.

Then one test per invariant above, and — critically — **every re-open and re-arm case is proved
through a producer**, `reconcile` and `_enqueue_path` alike. Council round 1 rejected a version
of the shrink test that called `spool.enqueue` directly: that bypasses the very gate the defect
lives in. The same round found the shrink test could never reach tick 2 at all, because tick 1
requeues the job with a persisted backoff, a second `enqueue` is a no-op on the same
`(path, boundary)` key, and `_drain_all` stops at the first job that is not due — so the test
advances the spool's clock instead.

New tests, by the finding each one nets:

| test | guards |
|---|---|
| `test_frozen_prefix_does_not_consume_bytes_the_next_job_can_ingest` | the reproducing test: the ratchet in miniature |
| `test_park_refuses_a_file_that_changed_under_the_examination` | round 2, codex — the park's own TOCTOU |
| `test_park_converges_identity_when_the_ceiling_does_not_rise` | round 2, cursor — suppression re-arms |
| `test_park_ceiling_is_monotonic_only_within_one_identity` | round 3, both peers |
| `test_reconcile_skips_a_frozen_file_until_it_changes` | growth re-opens, through the sweep |
| `test_reconcile_reopens_a_frozen_file_that_was_rotated_smaller` | round 1 — shrink re-opens |
| `test_reconcile_reopens_a_frozen_file_replaced_at_the_same_size` | same-size replacement, then re-arm |
| `test_reconcile_still_selects_a_never_seen_file_with_only_a_frozen_fact` | invariant 6 |
| `test_enqueue_path_skips_a_frozen_file_until_it_changes` | the Observer lane carries the gate |
| `test_enqueue_path_reopens_a_frozen_file_that_was_rotated_smaller` | round 1 — the lane that catches rotation today |
| `test_enqueue_path_re_arms_suppression_after_a_same_size_replacement` | no hot enqueue loop |
| `test_confirmed_shrink_clears_the_frozen_fact_through_the_producer` | invariant 7, via a producer |
| `test_successful_ingest_clears_the_frozen_fact` | invariant 8 |

Three existing tests assert the old behaviour and are **rewritten, not deleted**: the invariant
each one guards still holds, only the field carrying it changes.

| test | asserts today | asserts after |
|---|---|---|
| `test_frozen_prefix_advance_never_passes_the_accepted_boundary` (`:2692`) | cursor stops at B, never raw EOF | `frozen_until == B`, cursor untouched, and a second nudge at S is still claimable |
| `test_frozen_prefix_advance_never_moves_the_cursor_backward` (`:2830`) | a lower boundary never rewinds the cursor | renamed `test_frozen_prefix_park_is_monotonic`: a lower boundary never lowers `frozen_until`, on disk as well as in memory |
| `test_abandonment_with_unclosed_tail_composes_with_frozen_prefix` (`:3850`) | `end_offset == size` | cursor at the abandoned range's end; `frozen_until == size` |

Two of those three go **vacuous** rather than red the moment the cursor stops moving — their
assertions become trivially true. They are rewritten in the same task that makes them vacuous,
never left green and meaningless.

`test_idle_file_with_no_safe_boundary_is_dead_lettered` (`:2666`) passes unchanged — the
dead-letter behaviour is untouched.

## Verification in production

Beyond the suite: 75 state entries hold only `end_offset` today (48 on 2026-08-09). After the
merge that count stops rising, and entries carrying `frozen_until` with an intact cursor start
appearing. Measurable with the same read-only census used to write this spec.

## Residual risks

1. **A frozen file that never changes again is never ingested.** The deliberate trade: today it
   is marked consumed and its content is *lost*; after the change it stays out of memory but
   **recoverable**. The worst failure mode improves; it does not disappear. This is the one item
   here that exchanges one behaviour for another rather than only fixing, and the first thing to
   revisit if something looks wrong later.
2. **The 75 already-damaged entries are untouched.** Recovery is a separate spec — the ADR's own
   rule is cause before repair.
3. **The dead-letter keeps growing** at roughly 110 jobs/day. Fix A, separate spec.
4. **Cross-process writers stay uncovered.** `threading.Lock` is per-process; the pre-existing
   #150-class limitation is unchanged here.
5. **`reconcile` still has no identity model for an *ingested* file.** A same-size replacement of
   a file whose cursor already sits at EOF is skipped by the first cheap-skip arm
   (`end_offset == size`) exactly as it is today. Raised in council round 2 and **rejected as out
   of scope on verified grounds**: it is a real defect, it is pre-existing, and it is unchanged
   by this design. Folding it in here is the bundling that produced the 56-round cascade behind
   the retracted force-close. It needs its own issue and spec — currently unfiled.

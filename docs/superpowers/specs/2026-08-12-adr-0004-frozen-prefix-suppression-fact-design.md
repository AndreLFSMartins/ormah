# Suppressing selection with a fact, not with the cursor (ADR-0004)

**Date:** 2026-08-12 · **Status:** approved, not implemented · **ADR:** 0004

Stop the ingest lane from losing transcript content. Selection suppression moves out of
`end_offset` and into its own state field, so the cursor never claims bytes that were never
ingested.

Out of scope, each its own spec: recovering the content already lost, draining the
dead-letter noise (ADR "Fix A", re-admit-on-growth), and the 54 transcripts the parser
cannot close even unwindowed.

## The problem, measured 2026-08-12

The spool root is `~/.local/share/ormah/memory/ingest_queue/{66b287858fdea3e3,91da4ace50312981}/`.
All figures below were taken read-only from the live Beta on 2026-08-12; they supersede the
counts in the ADR's own 2026-08-12 amendment, which named two dead-letters and cited two jobs
that do not exist in the spool.

| quantity | value |
|---|---|
| dead-lettered jobs / distinct transcripts | 3806 / 1619, payloads from 2026-07-24 to today |
| dead-lettered transcripts with cursor already at EOF | **98%** (median 0 B, p90 0 B) — the dead-letter is noise |
| state entries holding only `end_offset` (cursor advanced, nothing ingested) | **75 of 1791** — was 48 of 1485 on 2026-08-09 |
| of those, transcript still on disk | 68, totalling 8,029,774 B |

Parsing each of those 68 transcripts whole, unwindowed, with the project's own
`parse_transcript` splits them cleanly:

- **14 files / 5,923,567 B / 23 closed user turns** — the parser closes content that the
  cursor skipped. This is the defect.
- 54 files / 2,106,207 B — the parser closes nothing even without a window (Codex rollouts
  with no `task_complete`, single-turn sessions). A parser-coverage problem, not this one.

### The mechanism is a ratchet

Read from the boundaries recorded on the dead-lettered jobs themselves:

```
ab16af53-….jsonl — 24 dead-letters, boundary climbing without pause:
  98,985 → 125,943 → 222,943 → 257,727 → 384,984 → 437,294 → 500,884
       → 676,978 → 694,301 → 877,060 → 971,222 → 1,017,779 → … → 1,435,339
```

Each job runs `_mark_frozen_prefix_consumed`, which advances the cursor to its own boundary.
A 1.43 MB session was pushed to EOF one slice at a time and never ingested, while a whole-file
parse closes 1,434,322 of its 1,435,339 bytes. The same shape appears in `e238fed7` (5 jobs),
`d66c054f` (4), `ebf4a5ff` (3).

The trigger varies — the windowed-parse artefact the ADR identified on 2026-08-10, or a
genuinely idle session with an unterminated tail. **The damage does not: every path loses
content at the same step, moving the cursor.** With the cursor held still, all 24 ratchet steps
lose nothing.

## Decision

`_mark_frozen_prefix_consumed` stops writing `end_offset` and writes a suppression fact
instead. Renamed `_mark_frozen_prefix_parked` — the current name asserts the very thing that
causes the loss.

```python
# session_watcher.py, ~L1552
entry["frozen_until"] = max(entry.get("frozen_until") or 0, target)   # target = min(boundary, size)
_commit_state(...)          # end_offset preserved, untouched
```

`frozen_until` means: *the last examination of this file, up to byte N, closed nothing; do not
re-select it until it grows past N.* It is not a progress offset.

**Named `frozen_until`, not `parked_until`.** `parked_until` belongs to the force-close design
retracted on 2026-08-09, and two live state entries still carry `parked_*` residue from the
branch that once ran; reusing the name would make this design unreadable against that history.

**Precedent:** `skipped_slices` (`session_watcher.py:1069-1085`) already records a suppression
fact inside the state entry, in the same `os.replace` as the cursor — atomic by construction,
no parallel ledger. `frozen_until` follows it, a scalar because only the ceiling matters.

### Considered and rejected

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

**`reconcile`** gains a second cheap-skip arm:

```python
elif (entry.get("end_offset") or 0) >= st.st_size and not entry.get("shrink_pending"):
    continue
elif (entry.get("frozen_until") or 0) >= st.st_size:
    continue          # frozen, and not grown since the examination
```

A separate `elif` rather than an `or` on the first: that arm carries the `shrink_pending`
exception, and folding an independent gate into the same expression ties them together.

**`_enqueue_path`** (`session_watcher.py:1361`) consults no state at all today — every FSEvent
becomes an `enqueue`. It gains the same gate. Gating only the sweep does not fix the defect, it
relocates it: the ADR already recorded this lesson in another form — *"the suppression is applied
in both producer lanes, because gating only the sweep would trade a full `failed/` for a hot
enqueue loop on the Observer lane."*

### Invariants

1. **Growth always re-opens.** `size > frozen_until` returns the file to selection, and the
   parse resumes from the **untouched** cursor — not from where the ratchet would have left it.
   This is what collapses `ab16af53`'s 24 dead-letters into a single ingestion.
2. **Never lowers.** `max()` on write: an out-of-order job with a smaller boundary cannot
   lower the ceiling and re-open the ratchet.
3. **`end_offset` leaves the write.** The committed entry preserves the current cursor by
   construction. `_commit_state`'s monotonic clamp (`:800-808`) stays as the backstop, but must
   not be what enforces this — it clamps `end_offset` only, and this design does not touch that
   field.
4. **A never-seen file stays eligible.** A new entry may be born as `{frozen_until: N}` with no
   `end_offset`. `reconcile` evaluates `(entry.get("end_offset") or 0) >= size` → `0 >= size` is
   false → it falls through to the new gate. Legacy entries lack the field, default 0, behaviour
   unchanged. No migration.
5. **A confirmed shrink clears it.** The shrink reset (`session_watcher.py:955`) copies
   `dict(existing or {})` and updates only `hash`/`end_offset`. A `frozen_until` surviving that
   reset would sit above the rotated file's size and suppress its fresh content — the same defect
   with the sign flipped. The reset must `pop` the field.

Deliberately unchanged: `spool.requeue(job, failure_class="no_safe_boundary")`. The file still
dead-letters on every freeze and the noise volume stays where it is (~110 jobs/day). That is
Fix A, a separate spec.

## Tests

Test-first. The reproducing test is `ab16af53`'s ratchet in miniature: a transcript whose turn
terminator lands past the job's `boundary`; job 1 freezes; job 2 arrives with a higher boundary.
Today the cursor jumps twice and nothing is ingested. After the change the cursor holds,
`frozen_until` rises, and **job 2 ingests the whole content**. It fails against today's code —
that is the done criterion.

Then one test per invariant above (growth re-opens; a lower boundary never lowers the ceiling;
`end_offset` is not written; a never-seen file stays eligible; a confirmed shrink clears the
field), and one suppression test per producer — `reconcile` and `_enqueue_path` — because gating
one lane is the recorded failure mode.

Three existing tests assert the old behaviour and are **rewritten, not deleted**: the invariant
each one guards still holds, only the field carrying it changes.

| test | asserts today | asserts after |
|---|---|---|
| `test_frozen_prefix_advance_never_passes_the_accepted_boundary` (`:2692`) | cursor stops at B, never raw EOF | `frozen_until == B`, cursor untouched |
| `test_frozen_prefix_advance_never_moves_the_cursor_backward` (`:2830`) | a lower boundary never rewinds the cursor | a lower boundary never lowers `frozen_until` |
| `test_abandonment_with_unclosed_tail_composes_with_frozen_prefix` (`:3850`) | `end_offset == size` | cursor at the abandoned range's end; `frozen_until == size` |

`test_idle_file_with_no_safe_boundary_is_dead_lettered` (`:2666`) passes unchanged — the
dead-letter behaviour is untouched.

## Verification in production

Beyond the suite: 75 state entries hold only `end_offset` today (48 on 2026-08-09). After the
merge that count stops rising, and entries carrying `frozen_until` with an intact cursor start
appearing. Measurable with the same read-only census used to write this spec.

## Residual risks

1. **A frozen file that never grows again is never ingested.** The deliberate trade: today it is
   marked consumed and its content is *lost*; after the change it stays out of memory but
   **recoverable**. The worst failure mode improves; it does not disappear. This is the one item
   here that exchanges one behaviour for another rather than only fixing, and the first thing to
   revisit if something looks wrong later.
2. **The 75 already-damaged entries are untouched.** Recovery is a separate spec — the ADR's own
   rule is cause before repair.
3. **The dead-letter keeps growing** at roughly 110 jobs/day. Fix A, separate spec.
4. **Cross-process writers stay uncovered.** `threading.Lock` is per-process; the pre-existing
   #150-class limitation is unchanged here.

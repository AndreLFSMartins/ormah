---
status: superseded
superseded-by: 0006
---

> **Superseded 2026-09-02 by [ADR-0006](0006-merge-is-autonomous-or-does-not-happen.md).**
> Both load-bearing arguments below were falsified by measurement: `duplicate_checked` holds
> **0 rows** (the 100-rejection ledger is gone) and `proposals` has **0 resolved rows in the
> store's entire history** against 354 pending — the queue shrank and curation stayed at zero.
> The human in the loop then stated he will not work it. Merge is now autonomous above the
> threshold or does not happen. This ADR stays readable as correct reasoning for August's facts.

# Merge stays human-curated: bound the review queue and honor rejections, not autonomous merge

The **Duplicate merger** auto-merges a pair when its composite score ≥ `auto_merge_threshold` (0.85) and
otherwise files a pending **Merge proposal** for human review (`duplicate_merger.py`). Nothing bounds that
queue — only `decay` proposals are pruned (`decay_manager.py`), so merge proposals accumulate with no cap
and no TTL: the live Beta holds **3,160 pending** and growing. The queue is fed at ingestion's rate, which
manufactures near-duplicates industrially (chunk-blind extraction, the recovery loop, doc-dumps), so it is
gigantic for the same reason everything downstream is — the volume the **P1 gate**
([ADR-0002](0002-relevance-gate-provenance.md)) exists to cut.

At that size no human curates it, and an un-curated queue is behaviorally a **no-op**: a sub-threshold pair
stays unmerged whether or not it is queued (leaving uncertain pairs separate is already the safe default).
The queue's only live effects are 3,160 stored rows and a **reject** button (`ui/src/components/ReviewQueue.tsx`)
that lies — it records the rejection into `duplicate_checked` (`routes_agent.py:409`) and toasts
"Proposal rejected", but the #81 seq-watermark rewrite of candidate generation dropped the *read*, so nothing
consults it and the same merge can be re-proposed. The write survived; its reader did not. The five
node-mutation invalidation `DELETE`s on `duplicate_checked` are dormant for the same reason — they only mean
something once the table is read.

Decision: **keep the human in the merge loop, but make the loop usable rather than remove it.** Three moves,
in order:

1. **Bound the queue** — a cap and/or TTL on pending merge proposals so it cannot grow to 3,160 again. This
   is an **independent** defect: the queue grows unbounded regardless of the merge model, so it is fixed now,
   gated on nothing.
2. **Restore the `duplicate_checked` read** so a human rejection sticks — skip any pair recorded
   `not_duplicate` when generating candidates, mirroring the existing `auto_link_checked` skip
   (`duplicate_merger.py:264-269`). This re-activates the dormant machinery already present (the reject write
   + the five invalidation `DELETE`s). It is **gated behind the P1 gate (ADR-0002)**: wiring it while the
   queue is un-curatable honors a button no one can reach; it earns its value only once reduced ingestion
   volume makes the queue small enough to review.

   > **Retracted 2026-08-11 — the gating clause only.** The button *was* reached: `duplicate_checked` holds
   > 100 human rejections. The move itself stands and is now ungated; see the amendment below.
3. Neither **delete `duplicate_checked`** (its function is real, only dormant) nor go **autonomous-merge**
   (see below).

## Considered options

- **Autonomous merge — drop the sub-threshold queue entirely:** rejected *for now*. Trusting auto-merge ≥0.85
  and leaving uncertain pairs separate is defensible, but committing to "no human ever curates merges" is a
  product decision to make *after* the gate makes the queue curatable, not under pressure from a queue that is
  unusable for a reason (volume) the gate already attacks. Reversible later; premature now.
- **Auto-decide the uncertain band (a second LLM pass / rule to resolve 0.85–composite):** rejected —
  machinery to remove a human from a loop that, once the queue is bounded and small, a human can serve
  cheaply. Evidence-free complexity.
- **Delete `duplicate_checked`:** rejected — it is not dead code, it is quasi-live code missing one edge (the
  read). Deleting throws away the reject write + five invalidations already built, and re-litigates a function
  (rejection memory) that is real once the queue is usable.
- **Bound the queue now + honor rejections after the gate, keep curation (accepted):** smallest set that makes
  the shipped review feature honest, fixes unbounded growth immediately, and defers the value-gated read to
  when it can be used.

## Consequences

- The deferred-tracks ledger's **Track 8** ("`duplicate_checked` bookkeeping bug") is **refuted**: the table
  is not a stagnant-bookkeeping bug but a write-only table whose read #81 replaced with the seq-watermark. Its
  stagnation since 2026-07-08 is the absence of manual rejections, not a defect. The track is re-scoped into
  the two moves above.

  > **Retracted 2026-08-11 — the second sentence.** The stagnation is not the absence of manual rejections:
  > the table holds **100 `not_duplicate` rows** written between 2026-07-04 and 2026-07-08. Curation happened
  > and then stopped. Track 8 stays refuted as a *bookkeeping* bug — the diagnosis (write-only table, read
  > dropped by #81) is unchanged and confirmed.
- **New independent work item:** bound the pending merge-proposal queue (cap/TTL). Verified defect, small fix
  — graduate to an issue.
- **Ordering:** bounding now; the `duplicate_checked` read after the P1 gate (ADR-0002) drops volume. The read
  is worthless before the queue is curatable.
- **Provenance is split.** The unbounded queue is **upstream** — in `upstream/main` the merger files proposals
  identically and only `decay` proposals are pruned, and the reject button ships in upstream's
  `ReviewQueue.tsx`; so **bounding is an upstream contribution**. The `duplicate_checked` table, its
  reject-write, and its invalidation `DELETE`s are **fork** (introduced in the fork's dedup work, commits
  `9cf18d4`/`94d42b3`; upstream's `/proposals/{id}` handler does not record `not_duplicate`), so **restoring
  its read is fork-local** — and moot upstream, which never had the read to lose.
- Residual: until the read is wired, the reject button stays a broken contract; bounding alone does not fix
  that, it only keeps the queue small. Accepted knowingly, gated on the P1 gate.

## Amendment 2026-08-11 — nothing shipped, the P1 gate never enforced, and move 2 loses its gate

Re-measured against the live Beta store (`~/.local/share/ormah/memory/index.db`, read-only) and the working
tree, 25 days after this ADR was accepted. **The decision stands unchanged; neither move was executed.**

### Still true, verified

| Claim above | Evidence today |
| --- | --- |
| Auto-merge at `score >= auto_merge_threshold` (0.85), else a proposal | `duplicate_merger.py:414`, `config.py:238` — unchanged |
| Nothing bounds the queue; only `decay` proposals are pruned | `decay_manager.py:23` still prunes `decay` only. `max_pending` / `proposal_ttl` / `prune_proposals` — **zero occurrences** anywhere in `src/` |
| The reject button writes and nobody reads | One `INSERT` (`routes_agent.py:409`), the invalidation `DELETE`s, and **no `SELECT` on `duplicate_checked` in the entire repo** |

Move 1 was declared "gated on nothing" and was still not done — nor had the issue this ADR ordered
("graduate to an issue") ever been filed. The queue went **3,160 → 3,773 pending** (+19%). Filed as
**r-spade/ormah#209** on 2026-08-11.

### What aged

**The P1 gate exists but runs in shadow, so move 2's trigger never fired.** ADR-0002 shipped
(`engine/relevance_quarantine.py`), but `ingest_relevance_gate_enforce: bool = False` (`config.py:443`) and
every record in the quarantine ledger carries `"mode": "shadow"`. The gate has dropped nothing and cut no
volume. "After the gate drops volume" has not arrived.

**Inflow fell ~74% by another route.** Pending merge proposals by month: 2026-06 → 4, 2026-07 → 3,446
(~111/day), 2026-08 → 323 over 11 days (~29/day). Real improvement, not from the gate (shadow); the cause was
not isolated — *inferred*, plausibly the ingest work around #81. Growth is still monotonic and still
unbounded, so this changes the urgency of move 1, not its necessity.

### Move 2 is ungated

The gating argument was "wiring it while the queue is un-curatable honors a button no one can reach". The
button was reached **100 times**: `duplicate_checked` holds 100 `not_duplicate` rows, 43 on 2026-07-04, 34 on
2026-07-07, 23 on 2026-07-08. Timestamps are 15 s–10 min apart with gaps — a human working a queue, not a
script (*inferred* from the interval distribution; no batch signature).

Two facts make those 100 rejections the load-bearing argument:

- **They are the only surviving record of that curation.** `proposals` today has **0 rows with
  `status != 'pending'`** — the 100 proposals the handler marked `rejected` (`routes_agent.py:384`) are gone
  from the table. *Inferred cause:* the store was rebuilt on 2026-07-08 (cf. `memory.bak-20260708-172456`),
  which recreated `proposals` while `duplicate_checked` survived. This strengthens "do not delete
  `duplicate_checked`" beyond the original argument: it is not merely dormant, it is the **sole ledger** of
  work a human already paid for.
- **Without the read, every one of them can be re-proposed.** Discarding 100 human judgements is a live cost
  today, not a cost that begins after the gate.

Therefore: **move 2 is no longer gated behind ADR-0002.** It is immediate work, a `SELECT`-and-skip mirroring
`auto_link_checked` (`duplicate_merger.py:264-269`). Move 1 remains first — a bounded queue is what makes
curation resumable at all — but move 2 no longer waits on volume.

Correction to the text above: the invalidation `DELETE`s are **six**, not five — the five in
`memory_engine.py` plus `index/builder.py:288` (`_invalidate_checked_pairs`, from #126), which clears all
three checked tables on a fingerprint change. All six remain dormant for the same reason.

### Unchanged

Every rejected option stays rejected on its original reasoning. The 100 rejections *reinforce* the rejection
of "delete `duplicate_checked`" and of "autonomous merge": a human did curate this queue, and would again if
it were small enough.

### Residual risk

- **Verified:** the counts, the dates, the absence of the `SELECT`, `enforce = False`, the absence of any
  cap/TTL, and the absence of the follow-up issue — all read directly from the store and the working tree.
- **Inferred:** that the ~74% inflow drop came from ingest work rather than any deliberate throttle; that the
  100 rejections are human curation (interval distribution); that the missing `rejected` rows were lost to
  the 2026-07-08 rebuild.
- **Housekeeping:** `docs/adr/` is listed in `.git/info/exclude`, so this ADR is untracked — only ADR-0004
  was force-added. If that exclusion is not deliberate, the ADR series lives on one disk only.

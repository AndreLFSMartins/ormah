---
status: accepted
supersedes: 0005
---

# Merge is autonomous above the threshold or does not happen: retire the review queue and the pair-memo tables

[ADR-0005](0005-merge-queue-bounded-and-curated.md) decided to **keep the human in the merge loop** and
explicitly rejected both "autonomous merge" and "delete `duplicate_checked`". Its two load-bearing
arguments were: (a) `duplicate_checked` is *"the sole ledger of work a human already paid for"* — 100
rejections; and (b) *"a human did curate this queue, and would again if it were small enough"*.

Both are dead. Measured 2026-09-02 against the live Beta store
(`~/.local/share/ormah/memory/index.db`, read-only snapshot):

| ADR-0005 claim | Measured today |
| --- | --- |
| `duplicate_checked` holds 100 human rejections — the sole surviving ledger | **0 rows.** `conflict_checked`: **0 rows.** The ledger is gone (*inferred*: another store rebuild, same cause ADR-0005 inferred for the missing `rejected` proposals) |
| A human would curate a smaller queue | `proposals` in its entirety: **354 rows, all `type='merge'`, all `pending`. Zero resolved, ever.** The queue shrank 3,773 → 354 and curation stayed at **0%** |
| Move 1 — bound the queue — is urgent and "gated on nothing" | Never done, and the rebuild bounded it by accident. It changed nothing: a smaller unworked queue is still unworked |

And the decision that only the human in the loop can make was made explicitly: **André, the sole
curator this system has, stated he will not work this queue** — "se tem uma dúvida, simplesmente não
acontece esse merge… ou ele merge automático, ou simplesmente para". ADR-0005's central premise was a
prediction about his future behavior; he refuted it.

## The design defect underneath

`auto_merge_threshold` (0.85) is compared against the **Composite score** — a pre-LLM similarity number
(`0.6·embedding + 0.2·title + 0.2·tokens`, `duplicate_merger.py:16-18,118-120`) — **after** the LLM has
already returned its verdict. The verdict itself is a bare boolean (`is_duplicate: true/false`,
`duplicate_merger.py:63`); it carries no confidence. So the pipeline lets a signal computed *before* the
judge overrule the judge:

```
composite ≥ 0.60 → ask the LLM → LLM says "duplicate" → composite ≥ 0.85 ? merge : queue for a human
```

The score does not measure how sure the judge is. It measures how alike the two texts *look*. A real
pending pair: two memories both recording the decision to use SQLite over PostgreSQL for a local-first
single-user system — `embed=0.87` (same meaning) but `title=0.42`, `token=0.25` (different words),
composite `0.657`. Semantically identical, lexically distinct: precisely the case LLM dedup exists for,
and precisely the case the 0.85 bar rejects. Conversely the pairs that clear 0.85 carry `title=0.94-0.98`
— near-verbatim copies. **In practice the threshold means "auto-merge only near-literal duplicates".**

## Decision

1. **Above `auto_merge_threshold`: auto-merge.** Unchanged.
2. **Below it: nothing happens.** No **Merge proposal**, no row, no queue. The pair stays as two nodes.
3. **Delete the dead pair-memo machinery** — `duplicate_checked`, `conflict_checked`, `pair_skip.py`, the
   rejection `INSERT` (`routes_agent.py:407-413`), and their invalidation `DELETE`s. The `builder.py`
   three-table loop reverts to the single `auto_link_checked`, which stays (it is upstream code with 10
   live readers).
4. **Delete the 354 pending rows** in the same migration. Leaving them keeps a queue that receives nothing
   yet still accepts clicks, on pairs judged against content that has since changed.
5. **Keep a counter, not rows.** `run_duplicate_detection`'s result dict reports `below_threshold` (pairs
   the LLM confirmed and the bar rejected) and the mean barred score. Non-growing, and it is the
   instrument recalibration will need.
6. **`auto_merge_threshold` stays 0.85.** Recalibration is deferred to its own issue with a sampling plan.

## Considered options

- **Trust the LLM verdict alone (drop the composite bar from the merge decision, keep it as the candidate
  filter at 0.60):** rejected — *measured*. A stratified sample of 14 pending pairs, judged by title:
  roughly 4 genuine duplicates, 2 clear false positives, 2 ambiguous in the low band, plus a clear false
  positive at 0.70 (`.gitignore entry for docs/superpowers/` vs `.gitignore entry for graphify-out/` — two
  *different* entries). ~1 in 4 wrong. `execute_merge` deletes a node; that error rate is not survivable.
  This is the option the coherent design argues for and the evidence forbids — the judge would have to be
  better first.
- **Lower `auto_merge_threshold`:** rejected — 309 of 354 pending pairs (87%) sit in 0.60–0.70, the band
  where pre-filter and judge diverge most. Lowering the bar moves hundreds of irreversible merges at once
  on the weakest evidence in the distribution.
- **Bound the queue with a cap/TTL (ADR-0005 move 1):** rejected — the rebuild already performed the
  bounding, and curation stayed at zero. It treats queue *size* as the defect when the defect is that
  nobody reads it.
- **Keep `duplicate_checked` as the home of the human veto (ADR-0005 move 2):** rejected — with no queue
  there is no rejection to record. The **Veto** concept is retired along with the surface that produced it.
- **Move the veto to `proposals` (its `rejected` rows persist and `synthetic_pattern_monitor` already
  reads resolved proposals with recency semantics):** rejected for the same reason — a well-designed home
  for a signal that will no longer be generated.

## Consequences

- **Divergence cost, accepted knowingly.** The proposal filing (`duplicate_merger.py:465`) exists
  identically in `upstream/main:374`, and `ReviewQueue.tsx` ships upstream. Removing them creates a
  permanent local delta in **two shared, hot files**, which will conflict on future Recipe C sync-downs.
  Everything in decision 3 is fork-only (`duplicate_checked`/`conflict_checked`/`pair_skip.py` have zero
  occurrences in `upstream/main`) and removing it moves us *closer* to upstream.
- **The upstream contribution is deliberately deferred.** Whether `r-spade/ormah` should also drop the
  queue is a product decision in someone else's project, discussed separately; `r-spade/ormah#209` (bound
  the queue) is the existing thread. This ADR governs the Beta only.
- **The review queue survives, serving one type.** `ReviewQueue.tsx` renders `p.type` generically. After
  the cut the only remaining producer is `synthetic_pattern_monitor` (`pattern`).
- **The graph keeps its semantic duplicates.** Roughly 50–70% of the 354 are genuine duplicates that will
  now never merge (*estimated* from the same 14-pair sample). This cost is **already being paid**: zero
  proposals were ever resolved, so those pairs coexist today regardless. The cut removes the bookkeeping,
  not a behavior.
- **New issue — producerless proposal types.** Only two code paths insert into `proposals`:
  `duplicate_merger` (`merge`) and `synthetic_pattern_monitor` (`pattern`). `conflict` and `decay` are
  enum members nobody creates — `decay_manager` prunes `decay` proposals that never exist, and
  `routes_agent` handles `conflict` approval for proposals that never exist. Same family, different
  defect; out of scope here.
- **New issue — the candidate filter reads the wrong memo.** The agent path
  (`_find_merge_candidates(respect_checked=True)`) skips pairs present in `auto_link_checked`, a table of
  *link* verdicts. An auto-linker "supports" silently suppresses a merge candidate from the
  Claude-in-the-loop batch. Out of scope here.
- **ADR-0005 is superseded, not amended.** Its decision inverted rather than being refined; it stays
  readable as the correct reasoning for August's facts.

## Residual risk

- **Verified** (read directly from the snapshot and the working tree on `local-main` @ `f629e83`,
  2026-09-02): the row counts; the score distribution; the composite formula and its arithmetic against a
  real `reason` string; the boolean verdict schema; the two proposal producers; `auto_link_checked`
  present in `upstream/main` while the other two tables are absent; `pair_skip.py` having zero importers;
  `ReviewQueue.tsx` being type-agnostic.
- **Estimated, from a 14-pair sample judged by title only:** the ~1-in-4 false-positive rate and the
  50–70% genuine-duplicate share. Full content was not read. If the recalibration issue proceeds, that
  sample must be redone properly against full node content — this ADR's rejection of "trust the LLM" rests
  on it.
- **Inferred:** that the 100 rejections and the 3,773 proposals were lost to a store rebuild rather than
  to a code path that deletes them.
- **Assumed, unchecked:** that no migration or code path outside `src/ormah` writes to the two tables.

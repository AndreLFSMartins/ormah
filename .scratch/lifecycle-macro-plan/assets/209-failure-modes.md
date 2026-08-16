# Draft comment for #209 — failure-mode analysis of the four-way duplicate policy

> Status: draft for André's review. Every code claim cites `file:line` on the current tree
> (`local-main`, 2026-08-14). Claims that could not be verified from code are explicitly marked
> *inferred* or *assumed*. Store numbers are limited to the ones already on record (this issue,
> ADR-0005). Do not post before review.

---

This is the follow-up I owed here: a failure-mode analysis of the agreed four-way policy — (1) clear
duplicate → auto-merge with audit history and undo, (2) uncertain duplicate → leave both alone,
reconsider later, (3) contradiction → preserve both and connect, (4) rare high-impact ambiguity
(core/identity) → optional bounded human review — plus the two agreed mechanics (invalidate pending
proposals when either node is merged or deleted; after #223, restrict candidates to active memories,
conditional on promoted memories becoming eligible again). Everything below is grounded in the code
as it stands today, so we know exactly which failure modes the current machinery already has, which
ones the new policy inherits, and which ones it creates. Format per mode: trigger → blast radius →
detectability → mitigation.

## 0. Baseline: what "clear duplicate" means operationally today

Auto-merge already exists and fires when **both** of these hold
(`background/duplicate_merger.py:417`, threshold `config.py:238` = 0.85):

- composite score ≥ 0.85, where composite = `0.6·embedding + 0.2·title-Levenshtein + 0.2·token-Jaccard`
  (`duplicate_merger.py:16-19,118-120`);
- the LLM judge answered `is_duplicate: true` (`duplicate_merger.py:395,417`) — LLM confirmation is
  mandatory, no merge happens without it (`duplicate_merger.py:326-328`).

So "clear" = *high surface similarity* AND *one LLM yes*. Neither signal measures the thing the
policy cares about — whether merging destroys information. That mismatch is the root of failure
modes 1 and 2.

## 1. Wrong auto-merge of near-duplicates (case 1 misfires)

**Trigger.** Pairs that are textually near-identical but semantically distinct clear both gates:

- *Templated memories.* Memories written from a fixed pattern ("Finished X on <date>", "Set
  <param> to <value>") differ in a handful of tokens. Jaccard token overlap and title Levenshtein
  are near 1.0, embeddings of mostly-shared text are close, so composite ≥ 0.85 is reachable while
  the only differing tokens are exactly the payload (the date, the value). Verified mechanism:
  the three signals are pure surface similarity (`duplicate_merger.py:84-120`); that agent-written
  memories are templated enough to hit this in practice is *inferred*, not measured.
- *The judge sees a truncated pair.* Both the single-pair and batched prompts pass
  `content[:2000]` (`duplicate_merger.py:78,80` and `:134,137`). Any distinguishing detail past
  2,000 chars is invisible to the only gate that reads meaning. Same failure class as #192's
  `content[:300]` consolidator truncation, milder constant.
- *The judge is noisy.* The prompt rules are good (they explicitly protect config-value changes
  and observation-vs-decision pairs, `duplicate_merger.py:47-48`), but the #191 record gives us a
  calibration data point for pairwise LLM judgment in this codebase: the auto-`mark_outdated`
  proposal was withdrawn at ~50% precision *on concordant pairs* (#191 decision record). A
  different task, so transfer is *inferred* — but it is the only measured precision we have for
  an LLM pairwise verdict here, and it is a coin flip.

**Blast radius.** One node deleted from the index and soft-deleted on disk
(`engine/memory_engine.py:1881,1974`), its edges remapped to the keeper (`:1886-1908`), and — the
expensive part — the keeper's own content/title **overwritten by LLM-generated merged text**
(`:1840-1843`). If the LLM "union" silently drops a detail, that detail is gone from the live graph.
Per-event radius is two nodes; the systemic radius is rate × precision: at the ~29 proposals/day
inflow measured in ADR-0005's amendment, even 5% wrong-merge precision loss compounds silently over
months. (*Inferred* extrapolation; the 29/day is from one store, one month.)

**Detectability.** Poor. An auto-merge emits one `logger.info` line (`duplicate_merger.py:422`) and
a `merge_history` row. Nothing surfaces it to the user; `list_merges` exists
(`api/routes_agent.py:480-486`, MCP tool `adapters/tool_schemas.py:404`) but must be polled. Worse,
**the audit trail records *what* but not *why***: `merge_history` has no column for the score or the
LLM's reason (`index/schema.sql:75-84`). The reason string with all four scores is built at
`duplicate_merger.py:413-415` and then only persisted on the *proposal* path (`:440-443`) — on the
auto-merge path it is discarded. A wrong merge cannot be audited for *why* the system thought it was
clear.

**Mitigation.**
(a) Persist score components + LLM reason + prompt/model into `merge_history` — the ruling says
"with audit history"; today's history cannot answer "why did you merge this".
(b) Define "clear" as *agreement of independent signals*, not one composite: e.g. require composite
≥ threshold AND LLM yes AND no protected marker (see §2, §8). The composite alone is surface-only.
(c) Raise or remove the judge truncation for the auto-merge decision specifically (2,000 chars is a
cost optimization on the wrong branch — the irreversible one).
(d) Make auto-merges *visible*: a whisper/UI line "merged A into B (undo: <id>)" turns silent
corruption into a correctable event. Undo exists (`routes_agent.py:503-506`); it is only useful if
someone learns the merge happened.

## 2. Contradiction misclassified as duplicate (the case 3 / case 1 boundary)

This is the most dangerous boundary in the policy, because the failure is a *destructive* action
taken on a pair the policy says must be *preserved*.

**Trigger.** Contradictions are near-duplicates by construction — "threshold is 0.38" vs "threshold
is 0.35 because 0.38 broke temporal queries" share almost all tokens and embed close together. They
are exactly the pairs that maximize the composite score. Verified: **the duplicate path never
consults the conflict machinery.** `run_duplicate_detection` performs no query on `edges` at all
(full read of `duplicate_merger.py:321-552` — the only SQL is on `nodes`, `proposals`, watermark),
so a pair *already connected by a `contradicts` edge* can still be auto-merged. It also never reads
`conflict_checked` (same read). The only defense at composite ≥ 0.85 is the LLM prompt rule at
`duplicate_merger.py:47-48` — one noisy gate (§1) standing between a contradiction and a merge.

**Blast radius.** Worst in the policy. A merged contradiction doesn't just lose a detail — it loses
*the disagreement itself*: one side's claim is deleted, the other (or an LLM blend of both) becomes
the single canonical memory, and any `contradicts` edge between them is destroyed as a self-loop
during remapping (`memory_engine.py:1890-1892`). Downstream, #224's conflict-surfacing has nothing
left to surface. Undo restores the pair (see §3 caveats) — but only if someone notices.

**Detectability.** Same as §1 — near zero, and here the *content* gives no alarm either: the merged
text reads plausibly.

**Mitigation.**
(a) **Hard gate, cheap and already available:** never auto-merge a pair connected by a
`contradicts` edge — one indexed `edges` lookup before `execute_merge`. This makes case 3 win over
case 1 by construction whenever the conflict detector got there first.
(b) Route order matters for pairs neither system has seen: run the conflict check *on the merge
candidate* before merging (the conflict detector and the duplicate merger already share candidate
machinery style, `background/conflict_detector.py:127`), or ask the duplicate judge a three-way
question (duplicate / distinct / contradiction) instead of a boolean — a "contradiction" answer
files the case-3 action (connect) instead of merging.
(c) `conflict_checked` result `evolution`/`tension` (`index/schema.sql:103-109`) should also veto
auto-merge — the system already paid for that verdict.

## 3. Undo is asymmetric: the kept node is unrecoverable (undo fidelity, part 1)

**Trigger.** Any merge that supplied `merged_content`/`merged_title` — which is *every* LLM-driven
merge, auto or approved (`duplicate_merger.py:411-421`) — followed by an undo.

**Blast radius.** Verified from the merge/undo pair:

- `execute_merge` snapshots **only the removed node** (`memory_engine.py:1845-1846`); the keeper's
  pre-merge content/title are overwritten (`:1840-1843`) and never recorded — not in
  `merge_history` (schema `index/schema.sql:75-84` has no kept-snapshot column), not in `audit_log`
  (`_write_audit_log` is not called anywhere in `execute_merge`, `:1816-2005`).
- `undo_merge` restores the removed node from its snapshot and repairs edges
  (`memory_engine.py:2023-2062`) — but **never touches the keeper's content, title, or tags**
  (full read of `:2008-2071`). Tags merged in at `:1867-1869` also stay.

So "undo" restores the deleted node but leaves the keeper carrying the LLM-blended text forever. If
the LLM dropped or hallucinated a detail, undo does not get the original back. Under the ruled
policy this matters doubly: the *stated safety property* of case 1 is "with audit history and undo",
and today undo is only half an undo.

**Detectability.** The gap is invisible until someone diffs the keeper against expectations —
effectively never.

**Mitigation.** Snapshot the kept node too (one more JSON column in `merge_history`, symmetric to
`removed_node_snapshot`), and have `undo_merge` restore it. Cheap, transforms undo from "restore
the deleted row" into an actual inverse operation. This is the **single most important guardrail**
before autonomous merge widens: it converts every §1/§2 misfire from permanent loss into a
recoverable event.

## 4. Undo fidelity after downstream edits (undo fidelity, part 2)

**Trigger.** Time passes between merge and undo; edges, feedback, consolidations, or *further
merges* land on the keeper in between.

**Blast radius.** Several distinct decays, all verified in `undo_merge`:

- *Interim same-triple edges deleted.* Undo deletes every remapped `(source, target, edge_type)`
  triple (`memory_engine.py:2037-2046`). If the auto-linker or a user independently created an edge
  with the same triple after the merge — with fresher weight/reason — undo deletes it
  indiscriminately, then re-inserts the *pre-merge* edge with `INSERT OR IGNORE` and the old weight
  (`:2056-2062`). Post-merge edge evolution on those triples is lost; genuinely new post-merge
  edges on *other* triples stay on the keeper even where they semantically belonged to the restored
  node's content. No warning either way.
- *Merge chains break silently.* The keeper of merge 1 can later be the removed node of merge 2.
  Undoing merge 1 while merge 2 stands restores the node file, but every original edge whose other
  endpoint was the (now deleted) keeper fails the existence check (`:2049-2055`) and is silently
  skipped — the restored node comes back *disconnected*. Nothing enforces reverse-order undo, and
  `merge_history` doesn't model the chain.
- *Lifecycle evidence never moves, in either direction.* `execute_merge` does not remap `signals`,
  `affinity`, `whisper_log`, or `access_count` from removed → kept (full read `:1816-2005`; those
  tables key on bare `node_id` TEXT with no FK, `index/schema.sql:173-216`). The keeper never
  inherits the removed node's confirmed-use history; after undo, feedback given to the keeper
  during the interim stays with it while the restored node returns lifecycle-cold. Under
  #220/#223 semantics this means **every merge destroys confirmed-use evidence** for one of the
  two nodes — a merged-away frequently-used memory contributes nothing to the survivor's stability,
  and the survivor can decay as if the usage never happened.
- *Consolidations don't unwind.* A consolidation that summarized the keeper's merged content keeps
  its `derived_from` provenance after undo; the restored node is outside it. (*Inferred* from the
  absence of any consolidation reference in `undo_merge`, `:2008-2071`.)

**Detectability.** `undone_at` records that an undo happened (`:2064-2068`) but nothing records
what it could not faithfully restore.

**Mitigation.** (a) Timestamp-guard the edge deletion: only delete remapped edges whose `created`
matches the snapshot, leaving interim edges alone. (b) Refuse (or warn on) undo when the keeper has
a later `merge_history` row — make chains explicit. (c) As part of the merge itself, remap
`signals`/`affinity` rows from removed → kept (and back on undo); this also fixes the lifecycle-
evidence destruction independently of undo. (d) Accept and document that undo is best-effort beyond
some window — but then case 1's safety story should say so.

## 5. Proposal invalidation races on merge/delete (agreed mechanic, not yet built)

Today nothing invalidates: `execute_merge` cleans the three `*_checked` tables
(`memory_engine.py:1928-1955`) but never touches `proposals`; `delete_node` likewise
(`:1210-1223`); the only `proposals` DELETE anywhere in `src/` is the legacy decay cleanup
(`background/decay_manager.py:25`; verified by repo-wide grep). When we build the agreed
invalidation, these are the races to design against:

**Trigger / blast radius.**

- *Approve-vs-invalidate race (the real one).* `resolve_proposal` flips status to `approved`
  **before** executing the merge, in its own transaction (`api/routes_agent.py:382-386`), then
  calls `execute_merge` (`:391-397`). An invalidation that targets `status = 'pending'` will miss a
  proposal that is mid-approval. Then the approval's `execute_merge` runs against a node the
  background job just merged away — and **returns the string `"Node … not found."` instead of
  raising** (`memory_engine.py:1832-1835`), so the proposal ends `approved`, nothing merged, no
  error anywhere. The UI shows a successful review of a no-op. (The background job's own in-window
  staleness check, `duplicate_merger.py:406-410`, protects only pairs inside one flush window, not
  the HTTP approval path.)
- *Double-resolution.* `resolve_proposal` never checks the current status (`routes_agent.py:374-386`)
  — an already-approved proposal can be approved again; today that re-runs `execute_merge` (which
  no-ops on the gone node), and under future invalidation logic it is another writer in the race.
- *Matcher fragility.* The only existing pattern for "proposals mentioning node X" is
  `source_nodes LIKE '%<id>%'` (`duplicate_merger.py:428-431`) — an unindexable substring scan over
  a JSON string. Safe for UUIDs, but per-merge cost is a full table scan of `proposals` (3,773 rows
  today and growing), and it silently depends on the id format.
- *Cross-process writers.* The merge/delete serialization is an **in-process** lock
  (`background/memory_lock.py:1-14`, `memory_engine.py:620-624`). The MCP adapter proxies HTTP to
  the single server (`adapters/mcp_adapter.py:22`), so agent traffic is covered; whether every CLI
  entry point goes through HTTP too is *assumed*, not verified — a second process opening the DB
  directly would sit outside the lock, and `execute_merge`'s file-save + `index_single` happen
  *before* its DB transaction (`memory_engine.py:1874-1879`), so the operation is not atomic even
  at the SQLite level.

**Detectability.** The approve-race is invisible today precisely because failure is a returned
string, not an exception; `merge_result` carries it (`routes_agent.py:434`) but status says
`approved`.

**Mitigation.** (a) Make resolution atomic and guarded: single transaction,
`UPDATE … WHERE status='pending'` and treat 0 rows updated as "already resolved/invalidated —
409". (b) Move the status flip *after* a successful merge, or write `approved` only on merge
success and `failed` otherwise; make `execute_merge` raise (or return a typed result) on missing
nodes instead of a prose string. (c) Do invalidation *inside* `execute_merge`/`delete_node`'s
existing transactions, keyed by both node ids — the same place the `*_checked` cleanup already
lives (`memory_engine.py:1928-1955`), which closes the window rather than shrinking it. (d) If
proposals survive at any volume, store source node ids in a join table (or two indexed columns)
instead of LIKE over JSON.

## 6. Queue re-growth and starvation under "leave both alone, reconsider later" (case 2)

**Trigger.** The ruling deliberately removes the human queue as the destination for uncertain
pairs — but "reconsider later" currently has **no mechanism**. Verified state:

- Background dedup's memory of past verdicts is only the seq watermark: it re-scans a pair *only
  when either node's `seq` bumps* (rewrite), by design (`duplicate_merger.py:333-339`, watermark
  advance `:530-535`, "survivor's rewrite bumps seq" `:404-405`). It never consults
  `duplicate_checked` (`:333-337`) — and `duplicate_checked` has no read anywhere in the repo
  (ADR-0005 amendment, re-confirmed for this tree: the reject write at `routes_agent.py:408-412`
  and the invalidation DELETEs are still write-only).
- The LLM verdict for a *sub-threshold* "yes, duplicate" pair becomes a pending proposal
  (`duplicate_merger.py:428-443`) — that is today's implementation of "uncertain", and it is the
  3,773-row queue this issue is about. A verdict of "not a duplicate" leaves **no record at all**
  (`:395-399` — a debug log line).

Two opposite failure modes fall out, depending on how case 2 is implemented:

- *Re-growth:* if "uncertain" keeps filing pending rows (status quo), the queue is unbounded again —
  merely renamed. The existing dedupe-by-LIKE (`:428-431`) only suppresses a second row while the
  first is pending, so any invalidation/expiry re-opens the door. ADR-0005's measured inflow
  (~111/day at July peak, ~29/day in August, one store) says re-growth is months, not years.
- *Starvation:* if "uncertain" writes nothing, then "later" never comes for stable pairs — a pair
  where neither node is ever rewritten is frozen at "uncertain" forever, and every rewrite of
  either node re-buys the same LLM judgment from scratch (pay-per-thrash: same uncertain pair,
  repeatedly judged, never resolved, *inferred* from the watermark design `:333-339`).

**Blast radius.** Not data loss — cost, and policy silently not happening. Also the disposition of
the existing 3,773 pending rows is undefined in the ruling: they are exactly "uncertain duplicates"
under the new taxonomy, so presumably they become case 2 (left alone) — but nothing decided whether
the rows are deleted, aged out, or re-judged.

**Detectability.** Good, for once: `SELECT COUNT(*) FROM proposals WHERE status='pending'` is
trivially monitorable; run stats already log `proposals_created` per run (`:538-547`) — note that
counter currently *also increments on auto-merges* (`:423`), so the stat overstates queue inflow.

**Mitigation.** (a) Record uncertainty durably and cheaply: a `duplicate_checked`-style verdict row
(`uncertain`, with score + judged_at) instead of a proposal row — bounded by pair count, not by
time, and it finally gives `duplicate_checked` its missing read (ADR-0005 move 2) in the same
stroke. (b) Define "later" explicitly: re-judge on seq bump (already free) **plus** an optional
slow TTL re-scan for frozen pairs, bounded per run. (c) Cap + TTL on whatever rows case 2 does
produce — the original ask of this issue survives the policy change. (d) Decide the backlog: my
recommendation is expire-in-place (mark, don't judge — 3,773 LLM judgments is real cost for pairs
that will re-enter via seq bump if they matter).

## 7. Interaction with #223's promotion path (active-only candidacy)

**Trigger.** The agreed post-#223 restriction — duplicate candidates come only from active
memories — collides with two mechanisms:

- *The seq watermark is a one-way cursor.* Candidate seeds are selected by `seq >` watermark
  (`duplicate_merger.py:364-369`); today there is **no tier filter anywhere in the file** (verified:
  zero occurrences of `tier` in `duplicate_merger.py`). Add `WHERE tier != 'archival'` naively and
  a node that is archival *when the cursor passes its seq* is skipped — and when #223 later
  promotes it, its seq is already behind the watermark, so it is **never scanned again** unless
  promotion bumps `seq`. The ruling's own condition ("provided promoted memories become eligible
  for evaluation again") is exactly this: **promotion must be a seq-bumping rewrite**, or
  active-only candidacy silently exempts every promoted memory from dedup forever. #223's design
  (promotion as one atomic lifecycle operation touching markdown + index) makes the seq bump
  natural, but it must be an explicit acceptance criterion, not a hope. (Mechanism verified from
  the watermark code; the #223 wiring is *assumed* — it isn't built yet.)
- *Mid-flight tier changes.* A pending proposal (or an in-window candidate pair) references nodes
  whose tier changes before judgment/approval: `execute_merge` has no tier check (`:1830-1843`), so
  approving a stale proposal happily merges a now-archival node into an active one — the keeper
  choice even *prefers* the higher tier (`memory_engine.py:2309-2315`), so an archival node's
  content gets folded into an active node the user believed was settled. Conversely a node
  archiving mid-flight doesn't invalidate its pending proposal (nothing does, §5). Neither is
  corruption, but both violate "candidates are active memories" at the moment that actually
  matters — the destructive action — rather than at scan time.

**Blast radius.** Silent permanent dedup exemption for promoted memories (first bullet) is the bad
one: it re-creates near-duplicate accumulation precisely for the memories confirmed-use says the
user cares most about. Second bullet is policy drift, bounded per event.

**Detectability.** Poor for the watermark hole (absence of proposals is indistinguishable from
absence of duplicates); fine for mid-flight merges (merge_history shows tiers if we start
recording them).

**Mitigation.** (a) Make "promotion bumps seq" an explicit #223 acceptance criterion (it is the
load-bearing condition of this issue's ruling). (b) Enforce active-only at *merge time* too: a tier
guard inside `execute_merge`'s pre-flight (both nodes active, else convert to case-2 "leave
alone"), not only at candidate selection. (c) Invalidation on archive: when #223 demotes a node,
run the same proposal invalidation as merge/delete (§5) — archival is a lifecycle exit from
candidacy, agreed mechanics should treat it as one.

## 8. Case 4 has no trigger signal today (core/identity ambiguity)

**Trigger/gap.** The policy reserves bounded human review for "rare, high-impact ambiguity (e.g.
core/identity)" — but the duplicate path currently possesses **no notion of protected nodes**: no
tier reference (verified, §7), no check for `defines` edges from the user node (identity membership
is computable — `memory_engine.py:2320-2324` does exactly this for whisper), no
confidence/importance gate. Today a `tier='core'` identity fact clearing 0.85 + LLM-yes is
auto-merged like anything else, and `_pick_keeper` will keep the core node and overwrite its
content with LLM text (`:2309-2315` + `:1840-1843`).

**Blast radius.** Low frequency, maximal per-event cost — identity/core memories are whisper-
eligible permanently (#191: `core` is the explicit permanent-eligibility mechanism), so a mangled
core memory whispers its mangled form into every future session.

**Detectability.** Same silent-merge problem as §1.

**Mitigation.** Define case 4's predicate now, in code terms, since both signals already exist:
`tier = 'core'` on either node, or either node is a `defines`-neighbor of the user node → never
auto-merge; file a bounded review item (bounded = cap + TTL, and expiry action = case 2, leave
both). This is cheap and turns case 4 from prose into a gate.

## Cross-cutting observations

- **`merge_history` and `audit_log` are unbounded** (zero DELETEs on either in `src/`, verified by
  grep) and each merge/undo grows them with full JSON snapshots. Autonomous merge raises the write
  rate on exactly the tables #219 flagged. Adding the kept-node snapshot (§3) makes rows bigger
  still — retention policy should ride along (#219's per-operation retention ruling extends
  naturally: merge snapshots inside the undo window are sacred, after it they are reclaimable).
- **Auto-merge inflates `proposals_created`** in run stats (`duplicate_merger.py:423`) — worth
  splitting into `merged` vs `proposed` before we start monitoring case boundaries (§6
  detectability depends on it).
- **The prompt already promises what the code doesn't keep**: the judge prompt tells the LLM the
  merge is "irreversible (though undoable)" (`duplicate_merger.py:22`) — after §3, "undoable"
  currently means half-undoable.

## Ranked: what to fix before flipping anything on

1. **Symmetric undo** (§3) — kept-node snapshot + restore. Converts every other failure from
   permanent to recoverable. Prerequisite for trusting auto-merge at all.
2. **Contradiction veto** (§2) — `contradicts`-edge + `conflict_checked` check before merge; the
   case-3/case-1 boundary must be enforced by data, not by one LLM answer.
3. **Atomic, guarded proposal resolution + in-transaction invalidation** (§5) — closes the silent
   approved-no-op race before invalidation multiplies the writers.
4. **Case-2 memory** (§6) — durable `uncertain` verdicts (giving `duplicate_checked` its read back)
   + explicit re-trigger; cap/TTL regardless.
5. **Promotion bumps seq as a #223 acceptance criterion** (§7) and a merge-time tier guard.
6. **Case-4 predicate in code** (§8) — core tier / `defines`-neighbor blocks auto-merge.
7. **Audit the why** (§1) — scores + LLM reason into `merge_history`; surface auto-merges.

## Open questions for the maintainer

1. **What is "clear", numerically?** Keep composite ≥ 0.85 + LLM-yes as the operational definition,
   or recalibrate? Given #218 (the similarity-adjacent signals are miscalibrated elsewhere) I'd
   keep the current pair *plus* the vetoes above rather than invent a new score — but that's a
   judgment call.
2. **Disposition of the existing 3,773 pending rows** under the new taxonomy: expire in place,
   re-judge bounded batches, or delete outright? (My lean: expire in place; seq-bump re-entry
   recovers any pair that still matters.)
3. **What does "reconsider later" mean concretely** — only on content change (seq bump), or also a
   slow TTL re-scan for frozen pairs? The former is free but can freeze a pair forever.
4. **Should undo restore the keeper too?** It requires a schema addition to `merge_history`
   (kept-node snapshot). I consider it a prerequisite (§3) — confirming before I build it in.
5. **Case-4 scope:** is `tier='core'` OR user-`defines`-neighbor the right protected-set predicate,
   and does *either* node qualifying protect the pair?
6. **Does archival demotion count as leaving candidacy** for invalidation purposes (§7c), or only
   merge/delete as agreed so far?

# Lifecycle cluster — issue dossier

**Compiled:** 2026-08-14 · **Source:** `gh` against `r-spade/ormah` (live state, not recall)
**Purpose:** single planning reference for the issues assigned to @AndreLFSMartins and the whole
memory-lifecycle thread, with every settled point from the discussions recorded in one place.
**Out of scope:** implementation. This file decides nothing new; it records what was already decided.

---

## 1. Are "assigned to me" and "the lifecycle work" the same thing?

Almost — but not quite. The assigned set is a strict subset.

| Set | Issues |
|---|---|
| **Assigned to me** | #220, #221, #222, #223 — all four `OPEN`, assigned by @r-spade on 2026-08-13 |
| **Lifecycle cluster** | the four above **+ #191** (closed, the decision source) **+ #218**, **#219**, **#224** (unassigned spin-offs) **+ #28/#31** (gated downstream) |
| **Adjacent, same thread** | #217 (maintenance at scale), #192, #193, #194, #151 |
| **False positive** | #39 `lifecycle(main): global _fallback_thread singleton…` — matches the word, unrelated to memory lifecycle. Do not pull it in. |

So: **four issues are mine to implement; three more (#218, #219, #224) came out of the same debate
and carry rulings, but nobody is assigned to them yet.**

---

## 2. The decision record — #191, closed 2026-08-13 as a *completed design decision*

> **Guiding rule:** A memory stays active because of **confirmed use** — not because Ormah surfaced
> it, because it was historically popular, or because it has many connections.

| Area | Decision |
|---|---|
| Archival | Dormant, not dead: excluded from whisper, reachable by deliberate recall, reversible through confirmed use |
| Confirmed use | `recall_node(id)` and **source-qualified** positive feedback |
| **Not** use | Search-result appearance, bare whisper injection, graph activation, conflict expansion |
| Negative feedback | Stays prompt-specific affinity evidence; never lowers stability |
| Forgetting curve | **Keep** the existing exponential `R = exp(-t/S)` |
| Initial working window | ≈ seven unused days → `fsrs_initial_stability = -7/ln(0.3) ≈ 5.814084815577761` |
| Reinforcement | Diminishing growth, spacing reward capped at `2.0`, at most one stability increase per node per day |
| Promotion | `archival → working` on confirmed use, with the initial-stability floor |
| Demotion | Retrievability alone; importance no longer blocks `working → archival` |
| Permanent eligibility | Expressed explicitly by `core`, never accidentally through importance |
| Consolidation | Only *explicitly superseded* consolidation sources are blocked from automatic promotion — **not** every `derived_from` target |

### Why the curve stays (explicitly considered and rejected)

Replacing exponential with FSRS-4.5/5 power-law was on the table. Rejected because the observed
failures have more direct causes: disconnected initial stability (`S=1`), unbounded spacing reward,
result appearances counted as accesses, no same-session cooldown, importance blocking demotion
forever. Fixing those gets the desired lifecycle **without changing the meaning of every stored
stability value**. Not a permanent lock-in: lifecycle math gets centralized and **versioned** so a
future model can migrate nodes *preserving their archival deadlines*.

### Q3 (conflicts) also ruled, tracked in #224

Global × project conflicts are valid; same-project conflicts must be possible; one component owns
`contradicts` edges; edge weight gets one consistent meaning; implementation waits for #81/#87.

### Withdrawn during the debate — do not resurrect

1. "Injection reinforces stability" — withdrawn (bare injection → nothing).
2. "Negative feedback lowers stability" — withdrawn (`-1` is evidence about the *pair*, not the memory; 26% of `-1` nodes also carry a `+1`).
3. "12–17 day window" — dropped in favour of ~7d, conditional on the promotion path landing first.
4. "Degree-based protection gate is paper armor" — wrong; it protects 99.6% of conflicted nodes. Real defect was the missing `edge_type` predicate (fork-only, #31, already fixed).
5. Auto-`mark_outdated` for evolution conflicts — withdrawn (~50% precision even on concordant pairs).
6. The 1,452 historical conflict edges as a resolvable backlog — no batch resolution should touch them.

---

## 3. Discord rulings, 2026-08-14 (transcribed into the issues by me; @r-spade to correct)

| Where | Ruling |
|---|---|
| #220 | #220–#223 assigned to me, **implemented as separate PRs**, preferred landing order **#220 → #222 → #221 → #223**. Draft PR #229 to be **closed as superseded**; its branch stays temporarily as optional reference. |
| #218 | **Fix 3 deferred** (cross-channel strength comparability) until #220–#223 produce better data. **Fixes 1 and 2 stand** as formula corrections. |
| #219 | **Yes to retention by operation.** `delete` snapshots get an explicit, *configurable* recovery window — deletion carries a privacy expectation, so they must **not** be retained indefinitely. `update`/`mark_outdated` snapshots take a shorter default. |
| #217 | **Q1 yes** (delta, not full-history sweeps; PRs #133 and #95 are the first two bricks). **Q2 yes** (user-facing ops take priority; background jobs get a wall-clock limit). **Q3** delegated to #151. **Q4 yes** (behaviour-changing settings documented separately from tuning knobs). Debate now closeable like #191 — @r-spade's call. |
| #209 | Premise change from the maintainer: **human review must not be the normal destination** for uncertain duplicates ("users cannot keep pace with an agent-generated queue"). Four-way policy — see §5. Also agreed: invalidate pending proposals on node merge/delete; **after #223 lands, restrict duplicate candidates to active memories, provided promoted memories become eligible again**. |
| Review order | **#133 is reviewed first, then #95.** Do **not** rebase #95 until #133 lands (avoids a double rebase). **PR #31 → convert to draft** — confirmed "exactly right". |
| PR #229 | Was produced by one of @r-spade's agents by mistake; he closes it as superseded. |

---

## 4. The four assigned issues, in landing order

### #220 — separate surfaced results from confirmed memory use `bug`

**Root cause.** `recall_search` and the default structured-search path call `_touch_access` per direct
result; that one helper updates `access_count`, `last_accessed`, `last_review` **and** stability
together. Appearing in a list becomes indistinguishable from being used → self-reinforcing loop.

**Decision.** Surfacing events (recall result set, bare whisper injection, UI search results, graph
activation, conflict expansion) may be *logged*, but must not increment `access_count`, advance the
confirmed-use/decay anchor, update stability, or promote an archival node.
Confirmed use = `recall_node(id)` **or** source-qualified positive feedback (`explicit`, `implicit`,
`auto_llm_judge`). `auto_heuristic` stays excluded until #218 calibrates signal strength.

> **Note for the record:** the thread converged twice here. I argued source-based gating; @r-spade
> countered with a single strength threshold; my tier breakdown (97% of events pinned at `0.85`)
> showed the threshold is decorative until #218's formula is fixed. Landing point is **source-qualified**,
> with `auto_llm_judge` **admitted** (it judges the finished response) and `auto_heuristic` excluded.

**Acceptance criteria.**
- Broad recall returning N nodes changes lifecycle fields on **none** of them.
- UI search changes no lifecycle fields.
- Bare whisper and graph-added results change no lifecycle fields.
- `recall_node(id)` records confirmed use for **exactly** the requested node, not its neighbours.
- Qualified positive feedback records confirmed use for exactly its resolved node.
- Tests cover hybrid **and** FTS fallback paths.

**Implementation note.** Replace the overloaded `_touch_access` contract with explicit
surfacing/logging vs confirmed-use paths; make the confirmed-use operation reusable by #221/#223.
Keep retrieval/whisper event logging intact so ignored appearances stay observable.

---

### #222 — stop importance from permanently blocking working-tier decay `bug`

**Root cause.** Demotion requires `R < fsrs_decay_threshold` **and** `importance < decay_importance_threshold`.
Importance mixes cumulative access count, edge count, and an FSRS-derived recency signal. 50 accesses
+ 4 edges → permanent non-recency contribution ≈ `0.51445` > the `0.5` gate. Such a node can **never**
leave `working`. Also: `importance_recency_half_life_days = 14` is configured but **never read** —
importance reuses FSRS retrievability, coupling two different concepts.

**Decision.** Retrievability alone controls `working → archival`. Remove importance as a pre-gate.
Wire importance's own recency to `importance_recency_half_life_days`. Keep importance for ranking,
display and core-cap prioritization. `core` is the explicit mechanism for permanent whisper eligibility.

**Acceptance criteria.**
- A working node below the retrievability threshold becomes archival regardless of historical access
  or edge counts, unless protected by an explicit rule such as `core`/identity handling.
- The 50-accesses + 4-edges node does not remain working forever.
- Importance recency follows its 14-day half-life and no longer depends on stability.
- Existing importance uses outside decay keep working.
- Tests: high-importance stale nodes, custom importance weights, independent recency behaviour.
- Config / background-job docs updated.

---

### #221 — bound stability reinforcement and add a per-day cooldown `bug`

**Root cause.** `S' = min(S × 1.5 × R^-0.2, 365)` is unbounded: as `R → 0`, `R^-0.2 → ∞`. An `S=1`
node recalled after 30 days gets a spacing factor ≈ `403.43`. Same-session compounding: the
`days_since >= 0.001` floor lets ten immediate recalls produce ≈ `1.5^10 = 57×`.

**Decision.**
```text
R       = exp(-t / S)                    # unchanged
spacing = min(R^-0.2, 2.0)
S'      = min(S × (1 + g × S^-w × spacing), fsrs_max_stability)
g = 0.5   w = 0.5                        # initial policy, configurable, not fitted
```
At most **one numeric stability increase per node per day**. Every confirmed use still advances its
recency/decay anchor → **two separate timestamps** required: (1) most recent confirmed use,
(2) most recent numeric stability update.

Centralize lifecycle math instead of duplicating formulas across engine and background jobs. Replace
boolean-only migration semantics with an **integer lifecycle-model version**. A future curve
migration must preserve each node's archival deadline, not rescale the curve by a constant.

**Acceptance criteria.**
- `S=1` confirmed-used after 30 days → bounded update `1 → 2`, before any promotion floor.
- Spacing stays finite for extremely old nodes; no retrievability-underflow failure.
- Growth diminishes as stability rises; ≈ **74** closely spaced eligible updates to reach the default cap from `S=1`.
- Ten confirmed uses in one day → **one** numeric stability update, but the latest confirmed-use time is recorded.
- Decay manager and reinforcement path share **one** centralized exponential retrievability implementation.
- Lifecycle-model versioning can represent more than migrated/not-migrated.
- Config validation, tests and configuration docs cover every new knob/state.

---

### #223 — reversible promotion + the seven-day initial lease `enhancement`

**Root cause.** Archival is one-way: `TierManager.promote()` has **no production callers**. New nodes
take `stability = 1.0` from the model default even though `fsrs_initial_stability` is configured and
validated. At `R=0.3`, `S=1` crosses into decay candidacy after ≈ 29 hours. Also: the proposed blanket
exclusion of every `derived_from` target is too broad — `derived_from` is a general relationship and
does not by itself mean supersession.

**Decision.**
- Default initial stability `-7 / ln(0.3) ≈ 5.814` → mathematical seven-day unused working window.
- Use `fsrs_initial_stability` at node creation **and** as the promotion floor.
- Promote `archival → working` on confirmed use from `recall_node` or source-qualified positive feedback.
- Compute bounded reinforcement from the **old** stability first, then apply the floor:
  `bounded update 1 → 2`, then `promotion floor 2 → 5.814`.
- Confirmed use + reinforcement/floor + promotion = **one atomic lifecycle operation**.
- Do **not** rescale existing stability values just because the default is now wired.
- Record explicit consolidation/supersession provenance; block automatic promotion only for those.

**Acceptance criteria.**
- New working nodes use the configured initial stability and cross the default decay threshold at
  seven days, *before* scheduler cadence.
- `recall_node` promotes exactly the requested archival node.
- Qualified positive feedback promotes its archival node; negative and unqualified sources do not.
- Promotion never **reduces** stability.
- The post-update floor does not amplify the same event into a longer-than-initial lease.
- Concurrent promotion/decay cannot leave markdown and index lifecycle state inconsistent.
- A generic `derived_from` target **can** promote; an explicitly superseded consolidation source cannot.
- Migration, markdown serialization, DB schema, tests and docs cover the new provenance/state.

**Dependencies.** Needs #220 (confirmed-use semantics) and #221 (bounded reinforcement) first.

---

## 5. Unassigned issues from the same thread

### #218 — `signals.strength` has no variance in any channel `bug`

A tier enum stored as a float. `submit_feedback` hardcodes `1.0` (`memory_engine.py:2590`) for every
source. `token_overlap` saturates before its own entry gate: the gate needs `overlap_ratio >= 0.5`,
but `min(0.85, 0.45 + overlap_ratio)` saturates at `>= 0.40`, so **every** match reports `0.85`.

Measured on my 36,729-node store: `node_id` 1.0 ×30 · `title` 0.95 ×2 · `sentence` 0.9 ×13 ·
`token_overlap` 0.85 ×**1,520** — 97% in the one tier pinned at its ceiling.

Cross-channel the threshold is **inverted**: `submit_feedback` pinned at the maximum `1.0`, while
`auto_llm_judge` reports honest confidence floored at `0.75`. Any threshold ≤ 1.0 admits every
in-flight self-assessment and filters out the stronger retroactive judgement.

**Three fixes; ruling splits them.** (1) `submit_feedback` records a real strength (explicit vs
implicit must differ; `affinity_implicit_weight = 0.8` already encodes that judgment) — **stands**.
(2) `token_overlap` varies with `overlap_ratio` — **stands**. (3) cross-channel comparability —
**deferred** until #220–#223 produce better data. Until (3), a threshold over mixed sources is
unsound even with (1) and (2) fixed, which is why #191 uses source-based filtering.

**Known cost of the interim rule:** excluding `auto_heuristic` wholesale discards the 45
`node_id`/`title`/`sentence` verbatim matches — the strongest evidence of use in the system. The
`evidence.match` field distinguishes them, so a detector-class rule could recover those without
`strength` at all. Also: `strength` is written in `signals` only, never in `affinity`
(`index/db.py:363` vs `:450`) — any rule using it needs a join or a new column.

### #219 — nothing reclaims disk `enhancement`

Two independent end-of-lifecycle gaps, **neither blocking #191 work**.

1. **`audit_log` has no retention.** `_write_audit_log` (`memory_engine.py:1666-1680`) writes a full
   JSON node snapshot on `update`, `delete`, `mark_outdated`. Nothing ever deletes. Measured: **78 MB,
   10% of the file, 39,573 rows**. Growth is independent of tier/decay/promotion/consolidation.
   `whisper_log_cleanup.py` already implements exactly this pattern with three configured knobs — model
   an `audit_log_retention_days` job directly on it. **Ruled:** retention differs by operation; `delete`
   snapshots get an explicit configurable recovery window (privacy: not indefinite), `update` /
   `mark_outdated` get a shorter default.
2. **No `VACUUM` path exists.** `VACUUM` appears nowhere in `src/` except a comment explaining its own
   absence (`index/db.py:314`). `PRAGMA auto_vacuum` is unset → default `NONE`. Deleting 30,000 nodes
   from a 761 MB store still leaves 761 MB on disk. The objection was to it being *automatic*, but
   there is currently **no mechanism at all**. Suggested: operator-triggered `ormah maintenance vacuum`
   / admin endpoint that reports reclaimable space, refuses without ~2× free disk, and states the
   exclusive-lock cost. `PRAGMA incremental_vacuum` needs `auto_vacuum=INCREMENTAL` at creation, so it
   cannot be retrofitted without a full `VACUUM` first.

### #224 — promote conflict detection to one system-level owner `enhancement`

Carries the Q3 ruling. **Blocked by #81 (incremental watermarks) and #87 (batched pairwise LLM calls)** —
do not expand the candidate space before those land. My implementations are already up as PRs
**#133** (→ #81) and **#95** (→ #87). Acceptance criteria: global-preference × project-decision
candidates judged and stored; two incompatible decisions in the same project can become candidates;
unrelated project × project decision pairs filtered by explicit type/space policy; auto-linker and
maintenance stop creating competing `contradicts` edges; all conflict edges use the documented weight
meaning and stay visible to traversal; docs explain benign vs actionable severity.

### #209 — the pending merge-proposal queue is unbounded `bug`

3,773 rows, no cap, no TTL. The only `proposals` DELETE in the codebase is the legacy decay cleanup.
**The Discord ruling changed the fix I originally filed**, in two steps:

*Agreed mechanics.* Invalidate pending proposals when either node is merged or deleted. **After #223
lands, restrict duplicate candidates to active memories — conditional on promoted memories becoming
eligible for evaluation again.** That is a hard dependency on #223's promotion path.

*Deeper premise change.* Human review must **not** be the normal destination for uncertain duplicates —
users cannot keep pace with an agent-generated queue. Four-way policy:

| Case | Action |
|---|---|
| Clear duplicate | Merge automatically, with audit history and undo |
| Uncertain duplicate | Leave both alone, reconsider later |
| Contradiction | Preserve both and connect them |
| Rare, high-impact ambiguity (core/identity) | Optional, **bounded** human review |

Human review stays available for inspection, undo and exceptional cases, but Ormah must not depend on
someone clearing a queue. **This reopens the "autonomous merge" option that ADR-0005 rejected "for
now"** — the "later" arrived, decided by the maintainer.

**I owe a follow-up comment on #209 analysing failure modes in that direction before implementing.**
Not yet posted.

---

## 6. Gated / downstream

| Item | State |
|---|---|
| **#28 / PR #31 — bounded forgetting** | Fully built (7 protection gates, cap backstop, soft-delete + retention window, hard purge), ships `False`, never exercised on either store. **Explicitly gated:** "Bounded forgetting in #28/#31 should wait until these lifecycle signals are corrected." Flipping it early would protect/delete nodes on bad data. |
| **#217 — maintenance at scale** | Open, Q1/Q2/Q4 ruled, Q3 → #151. Closeable at @r-spade's discretion. |
| **#192** | Consolidator summarizes from `content[:300]` — 85.5% of sources truncated before the LLM sees them, then demoted. Relevant to #223's provenance work. |
| **#193** | Edge `reason` never survives markdown round-trips (all 4,645 edges `NULL`). |
| **#194** | Maintenance conflict candidates omit creation dates → evolution direction decided blind. |
| **#151** | Ingest relevance gate (#217 Q3). My 1.8% manual keep-rate is the argument for it. |

---

## 7. Still genuinely open — needs a call before or during planning

1. **PR #229 disposition.** @r-spade's draft (branch `feat/issue-220-223-memory-lifecycle`, base `main`)
   implements all four issues in one PR and says `Closes #220–#223`. Discord says it is superseded by
   my four separate PRs, but **it is still OPEN as a draft**. Confirm who closes it and when — a stale
   `Closes #220` in an open PR will auto-close my issues if it ever merges.
2. **#218 fixes 1 and 2 have no owner and no PR.** They "stand" but are not assigned. They are not
   blockers for #220–#223 (source-qualification is the interim rule), but #220's `auto_heuristic`
   exclusion is explicitly *conditional* on #218. Decide whether to pick them up after #223 or leave them.
3. **#219 has no owner** despite a clear ruling. Independent of everything else — cheap, self-contained.
4. **Reference regime for measurements.** My store runs `llm_provider=ollama` + watcher (historically);
   @r-spade runs `llm_provider="none"` + watcher off, so **none of the four pairwise jobs has ever
   executed on his machine**. Any acceptance test phrased in store measurements must say which regime.
5. **Whether #191's `auto_llm_judge` admission survives contact with my store.** I turned the session
   watcher off; my store converges to the all-implicit regime. The `auto_llm_judge` confirmed-use path
   in #220 will therefore be effectively untested on live data on my side.

### Debts I owe, agreed and not yet delivered (verified against GitHub on 2026-08-14)

| Debt | State |
|---|---|
| **#209 failure-mode analysis** — I wrote "coming as a follow-up comment here" | **Not posted.** #209 has exactly one comment. |
| ~~**PR #31 → convert to draft**~~ | **Done 2026-08-14.** `isDraft=true`, with [an explanatory comment](https://github.com/r-spade/ormah/pull/31#issuecomment-5295353083) stating the #191 gate, the four blocking issues, and what is still owed from the 2026-07-10 review. |
| **PR #95 rebase** — must wait for #133 to land | #133 `MERGEABLE`, #95 `mergeable=UNKNOWN` (was conflicting). Do **not** rebase #95 yet. |
| **Transcription confirmations** — four issues carry "@r-spade, correct me if I mistranscribe" | No reply yet on #217, #218, #219, #209. |

---

## 8. Execution notes

- **Fork workflow is non-negotiable** — read `FORK-WORKFLOW.md`. Contribution branches cut from
  `upstream/main`, **never** from `local-main`. Push to `fork`. Do not rename remotes.
- **Landing order:** #220 → #222 → #221 → #223, one PR each.
  Dependency reality: #222 is independent of #221/#223 but wants #220's anchor; #221 needs #220;
  #223 needs both #220 and #221.
- **Known-red baseline.** PR #229 reports pre-existing failures on clean `origin/main`:
  `A LIMIT or k = ? constraint is required on vec0 knn queries` in auto-link, conflict and
  worker-thread vector search, plus a setup binary-detection assumption. Establish the baseline
  before claiming any suite green.
- **Config surface touched across the four:** `fsrs_initial_stability` (now actually read),
  `fsrs_reinforcement_gain`, `fsrs_reinforcement_saturation_exponent`, `fsrs_reinforcement_spacing_cap`,
  `fsrs_max_stability`, `importance_recency_half_life_days` (now actually read);
  deprecated-but-parse-compatible: `decay_importance_threshold`, `fsrs_stability_growth`.

---

## Appendix — issue index

| # | Type | State | Assignee | Title |
|---|---|---|---|---|
| 191 | issue | **CLOSED** 2026-08-13 | — | design debate: memory lifecycle — the decision record |
| 220 | issue | open | **me** | separate surfaced results from confirmed memory use |
| 221 | issue | open | **me** | bound stability reinforcement and add a per-day cooldown |
| 222 | issue | open | **me** | stop importance from permanently blocking working-tier decay |
| 223 | issue | open | **me** | reversible promotion and the seven-day initial lease |
| 218 | issue | open | — | `signals.strength` has no variance in any channel |
| 219 | issue | open | — | nothing reclaims disk — `audit_log` retention + `VACUUM` |
| 224 | issue | open | — | one system-level conflict owner (blocked by #81/#87) |
| 217 | issue | open | — | design debate: maintenance at scale (Q1/Q2/Q4 ruled) |
| 209 | issue | open | — | unbounded merge-proposal queue — **depends on #223**, four-way policy, failure-mode comment owed |
| 229 | **PR** | open (draft, @r-spade) | — | fix: repair confirmed-use memory lifecycle — *to be superseded* |
| 31 | **PR** | open, `isDraft=false` (mine) | — | bounded forgetting — **gated**; agreed to convert to draft, not done |
| 133 | **PR** | open, `MERGEABLE` (mine) | — | delta-select watermark (→ #81) — review this first; unblocks #224 |
| 95 | **PR** | open (mine) | — | batch K pairs per LLM call (→ #87) — **do not rebase until #133 lands** |
| 151 | issue | open (mine) | — | ingest relevance gate (#217 Q3) |
| 192 / 193 / 194 | issues | open | — | consolidator truncation · edge `reason` lost · conflict dates stripped |
| 39 | issue | open | — | **not** this cluster — `_fallback_thread` singleton, name collision only |

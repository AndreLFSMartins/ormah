# Map — memory-lifecycle macro planning

Label: wayfinder:map
Created: 2026-08-14

## Destination

Macro planning for the entire memory-lifecycle thread is **closed**: every open decision in the
cluster (ownership, sequencing, policies, external confirmations, gating criteria) is resolved and
recorded, so that implementation — starting with
[#220 — separate surfaced results from confirmed memory use](https://github.com/r-spade/ormah/issues/220)
— can proceed with zero open calls. Implementation itself is out of scope.

## Notes

- **Canonical source:** [`docs/lifecycle/2026-08-14-issue-dossier.md`](../../docs/lifecycle/2026-08-14-issue-dossier.md)
  — live-verified against GitHub on 2026-08-14. Zoom there for full detail on any ruling.
- **Domain terms** per [#191](https://github.com/r-spade/ormah/issues/191): *confirmed use*,
  *surfacing*, *working/archival/core tiers*, *promotion floor*. Do not re-litigate settled terms.
- **Skills:** grilling tickets → `/grilling` + `/domain-modeling`; research tickets → `/research`.
- **Fork workflow is non-negotiable** (`FORK-WORKFLOW.md`): contribution branches from
  `upstream/main`, never `local-main`; push to `fork`; never rename remotes.
- Tracker: local markdown. Claim = `Status: claimed` in the ticket file; André is the sole driver.

## Decisions so far

<!-- pre-seeded from the decision record and Discord rulings; links go to the sources -->

- [#191 — memory-lifecycle decision record](https://github.com/r-spade/ormah/issues/191) — a memory
  stays active only through **confirmed use** (`recall_node` + source-qualified positive feedback);
  exponential curve stays; ≈7-day initial window; archival is dormant-not-dead. Full table: dossier §2.
- [Discord rulings 2026-08-14](../../docs/lifecycle/2026-08-14-issue-dossier.md) (dossier §3) —
  #220→#222→#221→#223 as **four separate PRs** in that order; PR #229 superseded; #218 fix 3
  deferred, fixes 1–2 stand; #219 retention by operation; #217 Q1/Q2/Q4 ruled (Q3 → #151);
  #209 four-way policy replaces human-review-as-default.
- Review order — **PR #133 first, then #95**; no #95 rebase until #133 lands. PR #31 converted to
  draft (done 2026-08-14).
- Withdrawn positions (dossier §2) — six items; do not resurrect.
- [06 — draft the #209 failure-mode analysis](issues/06-209-failure-mode-analysis.md) — draft comment ready for review at `assets/209-failure-modes.md`; top risks are contradiction-as-duplicate merges and half-fidelity undo (kept node never snapshotted); #1 guardrail: symmetric undo before any autonomous-merge widening.

## Not yet specified

<!-- fog: in scope, not yet sharp enough to ticket -->

- **Second-wave sequencing.** Once the disposition tickets (#218, #219, #151, #192–194) resolve,
  the post-#223 roadmap needs an ordering. One patch of fog; graduates after tickets 08–13.
- **Lifecycle validation/eval regime after landing.** How the four landed PRs get validated on live
  stores given the two divergent regimes. Sharpens after tickets 04 and 05.
- **#209 implementation planning.** Only after the approach decision (ticket 07) and after #223
  exists in code (out-of-map execution).
- Whether closing #217 spawns further macro-planning questions.

## Out of scope

- **Implementation of #220–#223** — the repo's own chain (brainstorming → writing-plans → TDD)
  owns it; this map ends when that route is clear.
- **Detailed design of #151/#192/#193/#194** — this map decides *disposition* only; design is a
  future effort per item.
- **Flipping bounded forgetting / un-drafting PR #31** — execution gated on the four issues
  landing; the map only sets the flip criteria (ticket 14).
- **#39** — name collision only, unrelated to memory lifecycle (dossier §1).
- **Batch resolution of the 1,452 historical conflict edges** — withdrawn in #191; never a backlog.

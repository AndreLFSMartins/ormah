# Draft — reply to r-spade on PR #31 — SUPERSEDED 2026-07-14
> Posted as https://github.com/r-spade/ormah/pull/31#issuecomment-4973151833 (intro rewritten + full proposal inline). Kept for the record.

Thanks for the patience — here's the considered response I owed you. I went digging into the archival tier before answering, and what I found changed how I think this should be shaped. I'll keep it at mechanism level.

## What re-examining the archival tier turned up

The FSRS clock that feeds both decay and the forgetting gates is effectively uncalibrated:

- Every node starts at the default `stability = 1.0`. The `fsrs_initial_stability` setting exists in config but is never wired into node creation — it's a dead knob.
- Stability only grows on *explicit* recall; whisper injections don't count as access, and explicit recall is rare by design. So stability stays ~1.0 for nearly everything.
- With `fsrs_decay_threshold = 0.3`, `R = exp(-t/1.0)` crosses the threshold after ~29 hours. A node that isn't explicitly recalled within a day or so of creation becomes a decay candidate — by construction, not by usage.

So today "archival" doesn't mean "long-tail stale"; it means "older than a day or two". That cascades directly into this PR: every forgetting gate is keyed to retrievability and importance, and with stability pinned at 1.0, any node past `deletion_min_archival_days` has R ≈ 0 — the staleness gates stop discriminating and the conjunction quietly degrades to degree + feedback. The gates are the right shape; the signals underneath them aren't real yet.

## The sequence I'd propose

**1. Calibrate the clock first** (small standalone PR): wire `fsrs_initial_stability` (I'd start around 7 days), count whisper injection as weak reinforcement (capped, e.g. once/day/node) with positive feedback as strong reinforcement, and revisit the importance scorer, whose scores in practice don't reach the protection thresholds. Without this, any lifecycle policy — including the one in this PR — operates on noise.

**2. Slim this PR down to the transition machinery**, rebuilt clean from current `main`: gates + atomic guarded soft-delete + retention, with your findings addressed —
- `deleted_reason` stamped on tombstones, so merge/manual tombstones remain a pure undo/purge queue and forgetting output is distinguishable (your `deleted/` semantics point);
- the `archival_soft_cap` backstop dropped entirely — you're right that bypassing the staleness gates to hit a count is indefensible as-is; it can return later with explicit semantics if the need is proven;
- user-facing docs for `ORMAH_DELETION_ENABLED`, retention, and the lifecycle.

**3. Deep Recall as the next PR — I'm on board with the direction**, with one amendment from the digging: cold nodes should *stay indexed*, flagged out of normal queries and maintenance scans, rather than being moved to `deleted/`. Today soft-delete removes the node from the index entirely, so "cold" would be invisible even to a deep search. Concretely:

- forgetting transitions archival → **cold**: still indexed, excluded from normal recall and from maintenance scans (which also shrinks the maintenance working set dramatically — that's where the accumulating cost you described actually bites);
- **deep recall** searches the cold layer explicitly, returning provenance (when/why it went cold);
- a cold memory that proves useful again is restored/promoted — your point 5, wired to feedback;
- hard delete then exists in exactly two places: expired merge/manual tombstones (undo semantics, as today) and explicit user intent (privacy). Whether organically-created memories ever get purged can be decided later, with deep-recall telemetry instead of guesses.

For what the analogy is worth, this matches how human memory behaves: forgetting is loss of *access*, not erasure — effortful, cued retrieval can still reach it, and consolidation (distilling old episodes into durable gist) is how the long tail pays rent. Purge has no biological analogue; it's an engineering decision and should be justified as one.

**On normal recall:** my preference is to keep explicit recall searching archival (penalized, as today) — it's deliberate and cheap — while whisper stays active-only and deep recall adds the cold layer. But that boundary is a product call more than a technical one; happy to go either way.

## One confession about where this PR came from

Part of the original push for deletion was #22: the graph view becomes unusable on a large store, so "fewer nodes" looked like the fix. We've since replaced the graph view in our fork with a WebGL renderer (sigma.js + graphology, FA2 layout, active-first loading with per-space drill-down) that handles large stores comfortably. I'd be glad to upstream that as a separate PR for #22 — it decouples the rendering pain from the lifecycle decision entirely.

## Branch shape

Rather than force-pushing this branch again, I'd split:

- **(a)** clock calibration (new, small);
- **(b)** this PR rebuilt clean from current `main`, carrying only the slimmed #28 lifecycle above;
- **(c)** cold layer + Deep Recall;
- **(d)** WebGL graph view for #22.

Also worth coordinating on ordering: #29 (file-before-index write ordering) would simplify or remove the TOCTOU guard machinery here, and #123 (reindex dropping incoming edges) directly affects the degree-based protection gate — both intersect deletion safety.

If that shape works for you, I'll start with (a) and the rebuild.

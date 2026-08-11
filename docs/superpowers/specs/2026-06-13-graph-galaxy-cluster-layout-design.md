# Galaxy graph: tractable clustered layout at scale

**Date:** 2026-06-13
**Branch:** `feat/graph-galaxy-layout` (PR #17)
**Status:** approved design, pending implementation plan

## Problem

PR #17 introduced an overview-first "galaxy" graph (cluster-by-space, color, clickable
legend). After the maintainer's rework (`ae1cdf4`) dropped the fCoSE + hidden-hub pass for
a single global cola run, the layout no longer converges on large graphs.

Measured on the real graph (5559 nodes / 14048 edges / 70 spaces / 247 orphans):

| Approach | Result | Verdict |
|---|---|---|
| cola global (`ae1cdf4`) + seed/time tweaks | span ~88k, fit zoom at minZoom floor 0.03, `separationRatio` 0.12 | does not converge |
| cola global, 25s simulation | identical (88k, 0.12) | not a time problem |
| fcose single pass (`proof` and `default`) | blocks main thread > 45s at 5.5k nodes | infeasible |

**Root cause (mechanical):** no *global* force-directed layout works for 5.5k clustered
nodes. cola runs incrementally (rAF, no freeze) but dissolves the space clusters — nodes
with few intra-space edges have no force holding them in their space. fcose would cluster
(it is designed for it) but its computation is synchronous and freezes the browser at this
scale. The hidden-hub pass that `ae1cdf4` removed was *what held clusters cohesive*, not
just a perf cost.

**Key insight:** grouping by space is what makes the layout tractable — it partitions one
5.5k-node graph into ~70 sub-graphs of ~80 nodes each. Each small piece a force layout
resolves instantly; a compact macro packing of those pieces keeps `fit` off the zoom floor.

## Approach (chosen: C — deterministic macro + local micro-force)

### Mode `clusterBySpace` ON (default)

Replace the current pipeline (preset seed → global cola) with four steps:

1. **Partition** nodes by space (logic already in `computeClusteredPositions`). Nodes with
   no `space` form the `(no space)` group.
2. **Micro-layout per cluster** — for each space, run an isolated cola over the sub-graph
   (the space's nodes + their *intra*-space edges) in a **headless** cytoscape instance,
   `animate: false`, `avoidOverlap: true`. Output: node positions local to (0,0), plus the
   cluster's bounding-circle radius. Each sub-graph is small (~80 nodes mean) → resolves in
   milliseconds, never blocks.
3. **Macro packing** — circle-pack the clusters by radius: largest at center, the rest
   placed around it, pushed outward only until they no longer collide. Output: macro
   centroid (X, Y) per cluster. ~O(70²), trivial.
4. **Compose + apply** — final node position = macro centroid + local position; apply via
   a `preset` layout (instant). `cy.fit(OVERVIEW_PADDING)` — the compact macro keeps it off
   the floor.

Cross-space edges keep rendering (the existing subtle `.cross-space` class) and participate
in **no** layout — they are visual only.

### Mode `clusterBySpace` OFF

Keep the current global cola layout, plus **dynamic minZoom**: after `fit`, if it clamped at
the floor, lower `minZoom` so the whole graph fits ("always see the whole", as required).
There is no tractable partition without space grouping (the main connected component is
likely thousands of nodes and reproduces the freeze), so OFF does not get rich clusters by
design — it is the crude-connections inspection mode.

## Interaction with the two already-verified fixes

- `min-zoomed-font-size: 8` (node style) — **kept**; mode-independent, fixes label haze
  (problem 4 from #16). Verified.
- `handleDisconnected: !clusterBySpace` — in ON mode the global cola **no longer exists**, so
  orphans are resolved by the micro-layout (they land inside their space cluster by
  construction, more robust than the flag). The flag survives only in the OFF path, where
  `true` is correct; simplify the expression there.

## Risk to validate during implementation

Running cola **headless** and reading positions without a render: confirm that
`cytoscape({ headless: true })` + cola `animate: false` yields usable positions, including
node dimensions for `avoidOverlap`. If it does not work cleanly, fall back to a deterministic
concentric micro-layout for the problematic clusters only — but try headless cola first,
directly in the real-graph harness.

## Verification (real-graph harness, playwright)

Reuse the existing playwright harness (`/tmp/verify_layout.py`). Targets:

- `fit` zoom well off the floor (≫ 0.03; PR head got 0.28 on a 3.5k graph)
- `separationRatio` ≫ 1 (clusters separated; vs 0.12 today)
- 0 overlapping node pairs (preserve the zoom-in-resolves-nodes property)
- orphans ~0% outside their cluster
- layout wall time < ~3s, no main-thread freeze

## Out of scope

- Reintroducing hidden hubs or a second fCoSE pass (the dropped approach).
- Changing tier-based node colors, the legend behavior, drag physics, or appearance settings.
- OFF-mode clustering by an alternate dimension (tier/type) — considered and declined.

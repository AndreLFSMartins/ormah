# Graph Node Size by Degree — Design

**Date:** 2026-06-17
**Branch (impl):** `feat/graph-webgl-sigma` (UI feature → upstream PR), then merge into `local-main`
**Status:** Approved by André, ready for implementation plan

## Problem

In the Ormah WebGL graph (sigma.js), every node renders at nearly the same
(minimum) size, so the view lacks the visual hierarchy of Obsidian's graph,
where well-connected nodes are visibly larger.

**Root cause (measured 2026-06-17 on the live graph, 1831 nodes / 2319 edges):**
node size is currently derived from `access_count`, and **94.6% of nodes have
`access_count == 0`** (p50=0, p90=0, p99=3, max=24). With the current formula
`min(5, max(2, 2 + log2(access_count+1)*0.5))`, an `access_count` of 0 yields
size 2 — so almost every node renders at the floor. Only a handful of accessed
nodes reach ~4.3. The result is no perceptible size variation.

Obsidian sizes nodes by **degree** (number of connections). In this graph the
degree varies widely (p50=2, p90=6, p99=12, max=214), so sizing by degree
produces the visible hierarchy.

## Goal

Size each graph node by its **degree** (total connected edges, in+out) instead
of `access_count`, using a logarithmic curve with a cap, so the view gains
Obsidian-like size variation: isolated nodes stay small, hubs stand out without
dominating.

## Decision: metric and formula

- **Metric:** total degree (`graph.degree(id)` in graphology — counts in+out
  edges; the graph is directed but a connection is a connection visually).
- **Formula** (size in layout-position units, matching the existing
  `itemSizesReference: "positions"` regime):

  ```
  size = min(10, 2 + log2(degree + 1) * 1.3)
  ```

  Validated on the live graph:

  | degree | size |
  |--------|------|
  | 0 (isolated) | 2.00 |
  | 1 | 3.30 |
  | 2 (median) | 4.06 |
  | 5 | 5.36 |
  | 10 | 6.50 |
  | 31 (2nd-highest) | 8.50 |
  | 214 (hub) | 10.00 (capped) |

  Rationale: visible variation from degree 1 upward (most nodes are degree 1–5,
  where the log curve already separates them); the cap keeps the grade-214 hub
  at 5× the floor rather than dominating the canvas (a `sqrt` curve was rejected
  for pushing the hub to ~14, recreating the "one giant blob" problem).

- **Self-role floor preserved:** the `self` node keeps a minimum size (3.5) so it
  never disappears regardless of its degree.

## Components to change

### `ui/src/graph/visual.ts`
- `nodeSize(degree: number)` — replace the body with the degree formula above.
  Parameter renamed from `accessCount` to `degree` to reflect the new meaning.
- `displayNodeSize(degree: number, selfRole: SelfRole)` — same signature shape,
  now takes degree; keeps the `self` floor `Math.max(3.5, size)`.

### `ui/src/graph/graphModel.ts`
Degree is only known **after** edges are added. Today `size` is set inside
`addNode` (before any edge exists). Reorder:

- `buildGraph`: in the node loop, set all other attributes but NOT `size` yet
  (degree is unknown before edges). After the `addEdge` loop, do a single
  deterministic second pass that sets `size` for **every** node:
  `graph.forEachNode((id) => graph.setNodeAttribute(id, "size",
  displayNodeSize(graph.degree(id), roles.get(id) ?? "")))`. Reuse the `roles`
  map already computed at the top of `buildGraph`. No placeholder size on
  `addNode` — the second pass is the single source of truth, so no node can be
  left without a size.
- `applyAppearance`: it re-styles an existing graph (edges already present), so
  it can read `graph.degree(id)` directly when setting `size`. Replace
  `displayNodeSize(n.access_count, role)` with `displayNodeSize(graph.degree(n.id), role)`.

`access_count` is no longer read for sizing. (It remains on the node data for
other uses; we simply stop feeding it into size.)

## Testing (TDD)

### `ui/src/graph/visual.test.ts`
- `nodeSize(0)` returns 2 (floor).
- `nodeSize` grows with degree: `nodeSize(10) > nodeSize(2) > nodeSize(0)`.
- Cap: `nodeSize(214) <= 10` and `nodeSize(10000) <= 10`.
- Self floor: `displayNodeSize(0, "self") >= 3.5`.
- Non-self isolated: `displayNodeSize(0, "") === 2`.

### `ui/src/graph/graphModel.test.ts`
- Build a small graph where node A has several edges and node B has none; assert
  `graph.getNodeAttribute(A, "size") > graph.getNodeAttribute(B, "size")`.
- Assert the isolated node B renders at the floor (2), and the self node (if
  present) is at least 3.5.

## Verification

After implementation, rebuild the UI and confirm on the live graph (headless
Playwright, DEV handles) that node sizes now span the expected range (min 2, hub
~10) and that the rendered graph shows visible size variation — not a uniform
field of dots.

## Out of scope (backlog, separate cycles)

- **Layout d3-force** (replace ForceAtlas2): measured to separate the connected
  core (ringRatio 0.78 → 0.43), but a larger change (new dep, removes FA2).
- **Hide orphans by default**: 896 nodes (48.9%) have degree 0–1; hiding the 544
  fully-isolated nodes removes the orbital "dust". Pairs naturally with the
  layout change.

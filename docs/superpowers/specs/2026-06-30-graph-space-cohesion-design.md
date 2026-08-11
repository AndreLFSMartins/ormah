# Graph Per-Space Cohesion (#22 slice B) — Design

**Goal:** When the `clusterBySpace` toggle is on, lay the graph out so each space forms a
visually cohesive cluster, eliminating the ~26.8% cross-space smear that one global FA2 pass
produces.

**Architecture:** A new pure module `ui/src/graph/clusterLayout.ts` computes final node positions
via a two-phase macro/micro layout (per-space synchronous FA2 + macro ring of centroids).
`GraphView` switches between this static layout (toggle on) and the existing global FA2 worker
(toggle off). No new dependency; no backend change.

**Tech Stack:** Vite/TS, graphology + graphology-layout-forceatlas2 (already in the bundle),
vitest (pure-function tests; no React Testing Library — vitest includes only `src/**/*.test.ts`).

---

## Problem

- `ui/src/graph/graphModel.ts:14` `seedPosition(index, total)` seeds nodes on a ring **by index**,
  interleaving spaces.
- `ui/src/components/GraphView.tsx:376` runs **one global FA2** worker. Global gravity pulls every
  space toward the centre; the index-ring seed plus cross-space edges leave clusters smeared
  (~26.8% cross-space mixing, recorded as the slice-B bug).
- `clusterBySpace` already exists as a prop but currently governs **only legend visibility**
  (`GraphView.tsx:315`), not layout.

## Decisions (locked in brainstorming)

1. **Trigger:** wire the existing `clusterBySpace` toggle to drive layout. ON = cohesive per-space
   clusters; OFF = current global FA2 (unchanged). Reuses existing UI, reversible, no default change
   for the off path.
2. **Approach (A2 — macro/micro two-phase):** chosen over A1 (seed-only, likely re-smears under
   global gravity) and A3 (custom group force, needs d3-force / a custom tick loop). A2 is
   deterministic — cross-space forces never act — reuses FA2 already in the bundle, and matches the
   spec direction.
3. **Macro arrangement:** ring of space centroids (not grid).

## Module: `ui/src/graph/clusterLayout.ts`

Single pure entry point:

```
computeClusterLayout(
  nodes: MemoryNode[],
  edges: Edge[],
  opts?: { iterations?: number },
): Map<string /*nodeId*/, { x: number; y: number }>
```

Algorithm:

1. **Group** nodes by `space`. Treat `""`/null (no-space) as one additional space bucket.
2. **Micro (per space):** build a graphology subgraph containing only that space's nodes and the
   edges with **both** endpoints in the space. Seed deterministic starting positions (small ring by
   intra-space index), then `forceAtlas2.assign(sub, { iterations })` (synchronous, deterministic
   given the seed). Read each node's local `{x, y}`.
3. **Macro (place clusters):** lay space centroids on a ring. Ring radius scales with
   `sqrt(totalNodes)` so the canvas grows with the data; each space gets an angular slot sized by
   its node count, so a large cluster's bounded local radius does not overlap its neighbour.
4. **Translate:** offset each space's local coordinates by its centroid; return the combined
   `Map<nodeId, {x,y}>`.

Determinism ⇒ positions are final; **no global FA2 worker runs** in cluster mode.

### Helper (testability)

```
crossSpaceMixing(positions: Map<string,{x,y}>, nodes: MemoryNode[]): number
```

Fraction of nodes whose nearest neighbour (by position) belongs to a different space. Used by tests
to assert the smear drops; not called in production rendering.

## Wiring: `GraphView.tsx` mount effect

In the mount effect (`GraphView.tsx:321`, deps gain `clusterBySpace`):

- `clusterBySpace === true`: after `buildGraph`, call `computeClusterLayout(nodes, edges)` and write
  each node's `x`/`y` via `setNodeAttribute`. Do **not** start the FA2 worker (`layoutRef` takes the
  static/NOOP path); mark `layoutReady` immediately.
- `clusterBySpace === false`: the current flow verbatim — index seed from `buildGraph` +
  `createForceLayout(graph)` global worker. **Zero regression on the off path.**

Dragging a node in cluster mode moves it without a re-settle (no worker), consistent with a static
layout.

## Testing (TDD, pure functions)

`ui/src/graph/clusterLayout.test.ts`:

- **a** Same-space nodes lie within a bounded radius of their space centroid.
- **b** Distinct-space centroids are separated by ≥ a minimum distance.
- **c** `crossSpaceMixing` on a multi-space fixture falls well below the 26.8% baseline (threshold
  fixed at <5%).
- **d** Determinism: two runs on the same input return identical maps.
- **e** No-space (`""`/null) nodes form their own cluster, not scattered.
- **f** Single-space input yields one centred cluster.

A small worked fixture (3 spaces, a few intra-space edges, 1-2 cross-space edges) drives a, b, c.

## Ceiling (ponytail)

`forceAtlas2.assign` runs synchronously on the main thread. A single very large space could cause a
brief jank. Marked with a `ponytail:` comment naming the upgrade path (move per-space layout to the
FA2 worker if jank is measured). The active graph is backend-gated to core+working, so the common
case is small.

## Out of scope

- Slice C (LOD / progressive rendering).
- The `clusterBySpace === false` global-FA2 path (untouched).
- Any backend / `/ui/graph` change.
- Cross-space edges: they become long connectors between clusters by design — this surfaces the
  link without smearing the clusters; no special handling.

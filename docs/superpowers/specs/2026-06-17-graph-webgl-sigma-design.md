# Graph view: WebGL live-force migration (sigma.js)

**Date:** 2026-06-17
**Branch:** `feat/graph-webgl-sigma`
**Status:** design approved, pending implementation plan

## Problem

The galaxy graph view (`ui/src/components/GraphView.tsx`, cytoscape + cytoscape-cola, Canvas
renderer) renders a dispersed diamond/grid ("losango"), not the organic gravitational clusters
intended. Two compounding causes, both confirmed against the live store (~1.7k nodes, 616
connected components: 1 giant of 870 + 615 fragments):

1. **No live force at scale.** Cola does not converge past ~5.5k nodes and freezes the main
   thread; even at ~1.2k it doesn't form rings.
2. **Component packing.** webcola `handleDisconnected: true` packs the ~505 isolated singletons +
   ~110 tiny components into a rigid grid — the "losango". The freeze is cytoscape's synchronous
   Canvas + synchronous element creation, not lack of persistence.

The "rich" edge curves and dashed archival borders the code defines are not perceptible in
practice (bezier between two nodes with no parallel edge draws ~straight; a 1px dashed border
vanishes on zoom-out), so they are **not** parity requirements.

## Goal

Replace the cytoscape Canvas renderer with **sigma.js v3 (WebGL)** running a **live ForceAtlas2
simulation in a Web Worker** (the Obsidian method). No position persistence — re-simulate on each
open. Preserve the current visual identity. Kill the freeze by moving render to WebGL and physics
off the main thread.

## Approach decision (settled)

- **Library: sigma.js v3.** Only option that delivers true WebGL 2D render *and* fixes the freeze.
  Its `nodeReducer`/`edgeReducer` model maps almost 1:1 to cytoscape's `style`+`class`, so the
  dim/focus legend and color/size logic transfer with minimal rewrite. react-force-graph 2D is
  Canvas (does not fix the freeze) and its 3D mode changes the interaction paradigm; cosmos.gl's
  GPU scale is unneeded (real ceiling <10k post-forgetting) and costs label richness + per-node
  visual control.
- **Layout: pure ForceAtlas2, organic (option A).** Edges pull connected nodes together;
  communities emerge; isolated nodes float to the periphery. FA2 does **not** component-pack, which
  is precisely what eliminates the grid/losango. `space` is already encoded by color. Per-space
  seeding/gravity (option B) is deferred — add only if spaces interleave too much in practice.

## Data source (unchanged)

`GET /ui/graph` → `{ nodes: [...full node rows...], edges: [...], user_node_id }`. Node rows carry
`id`, `tier`, `space`, `access_count`, `content`, and self-identity fields. No server change.

## Components (focused files, one responsibility each)

- **`graphModel.ts`** — build a `graphology.Graph` from the `/ui/graph` payload. Maps each node to
  sigma attributes (`x`, `y` seed, `size`, `color`, `label`) and each edge to `color` by type. Pure
  function: payload → graph. Independently unit-testable.
- **`forceLayout.ts`** — wraps the `graphology-layout-forceatlas2` worker (`FA2Layout` from
  `graphology-layout-forceatlas2/worker`): `start()`, `stop()`, `kill()`, parameter config, and
  inferred settings via `forceAtlas2.inferSettings(graph)`. Owns the simulation lifecycle. (Exact
  worker export name to be confirmed against the installed version during implementation.)
- **`sigmaReducers.ts`** — `nodeReducer` / `edgeReducer` computing per-frame visual state from
  `{hovered, selected, dimmedSpaces}`: hover focus (highlight node + neighbors, dim the rest),
  legend dim/focus, selection. This replaces the cytoscape `class`-based styling.
- **`GraphView.tsx`** — orchestrator: mounts the sigma container, builds the graph via
  `graphModel`, runs `forceLayout`, wires hover/click/zoom events to React state, drives reducers.
  Substantially smaller than the current 1198 lines.
- **Legend (existing DOM/React)** — reused; its toggles now set `dimmedSpaces` state consumed by
  the reducers instead of mutating cytoscape classes.

## Visual mapping (parity)

| Feature (today) | sigma.js mechanism |
|---|---|
| Color by tier / space / self-role | node `color` attribute (computed in `graphModel`) |
| Node size by `access_count` | node `size` attribute |
| Edge color by type | edge `color` attribute |
| Labels (zoom-gated) | sigma label rendering + `labelRenderedSizeThreshold` |
| Legend dim/focus | `nodeReducer`/`edgeReducer` from `dimmedSpaces` |
| Hover highlight | reducer: focus node + neighbors, dim others |
| Zoom / pan / tooltip | sigma camera + DOM tooltip on `enterNode`/`leaveNode` |
| Drag a node | sigma `downNode`/`mousemove` → re-heat FA2 |

**Best-effort / deferred (not parity):** glow halo (custom node program), edge curves
(`@sigma/edge-curve`), dashed archival border. André does not perceive these today, so they are
out of the parity bar; glow may be added later as a custom node program if desired.

## Simulation lifecycle

1. Fetch `/ui/graph`; build graphology graph; seed initial positions (small random or circular —
   FA2 rescales) so the layout is deterministic enough to start.
2. Start the FA2 worker (`barnesHutOptimize: true` above ~1k nodes, `adjustSizes: true`,
   `gravity`, `scalingRatio`, `slowDown` from `inferSettings` + tuning).
3. Render live; the worker posts positions, sigma redraws — main thread stays free.
4. Auto-stop the worker after a settle window (or convergence); dragging a node re-heats it.
5. Re-simulate on each open (no persistence).

## Dependencies

- **Add:** `sigma`, `graphology`, `graphology-layout-forceatlas2`.
- **Remove:** `cytoscape`, `cytoscape-cola`, `cytoscape-fcose`, `@types/cytoscape`.

## Testing

- **Unit:** `graphModel` mapping — happy path, node with missing space/tier, empty graph, isolated
  node (no edges). Assert sigma attributes (color/size/label) and edge colors.
- **Unit:** reducer logic — hovered node highlights neighbors and dims others; `dimmedSpaces` dims
  the right nodes.
- **Playwright visual (reusing the `layout_test.mjs` approach):** load the UI, wait for the FA2
  settle, assert a `<canvas>` is present, measure per-space centroid separation vs intra-space
  spread (separation ratio > 1 — i.e. clusters, not a grid), and capture a screenshot. Assert no
  rigid grid: the bounding-box aspect ratio is not a near-perfect packed rectangle.

## Out of scope

- Position persistence (server-stored `x,y`).
- Bounded-forgetting (#28).
- The embeddings "semantic map" (UMAP/PCA) layout.
- Per-space galaxies (option B) — deferred unless A interleaves spaces visually.

## Success criteria

1. The view renders connected components as organic clusters with isolated nodes on the periphery —
   no grid/losango — at the live store size (~1.7k) and at 5k+ without freezing the main thread.
2. Color (tier/space/self), node size, edge color, labels, zoom, hover highlight, and the
   legend dim/focus all work as they do today.
3. The FA2 simulation runs in a Web Worker; the main thread stays responsive during layout.

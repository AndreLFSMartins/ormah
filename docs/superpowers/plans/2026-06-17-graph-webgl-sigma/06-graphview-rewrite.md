### Task 6: Rewrite GraphView as a sigma orchestrator

The big one. Replace the cytoscape body of `ui/src/components/GraphView.tsx` with sigma + FA2, **preserving the component's external contract** so its callers keep working.

**Files:**
- Modify (rewrite body): `ui/src/components/GraphView.tsx`

> **Before writing anything, read the entire current `ui/src/components/GraphView.tsx`.** It is ~1198 lines. You must preserve the component's full external contract:
> 1. **Props** (current lines 23–31): `nodes`, `edges`, `onNodeSelect`, `focusNodeId`, `userNodeId`, `clusterBySpace`, `appearance`. Keep the same names/types — and **every prop must drive behavior**, including `focusNodeId` (6.6) and `clusterBySpace` (legend visibility, 6.4).
> 2. **Imperative ref API** (current lines 444–502): `focusNode(id)`, `highlightNode(id)`, `highlightNodes(ids)`, `clearHighlight()`. Called by Insights/Review. 6.3 re-implements them on sigma **including the viewport fit/center behavior** of the current `highlightNodes` (Council H1).
> 3. **In-view controls:** the zoom slider (+/−) and any reset/overview control the current view renders (6.6).
>
> Find callers to confirm the contract before/after: `grep -rn "GraphView\|focusNode\|highlightNodes\|focusNodeId" ui/src` .

**Council adjustments folded in (2026-06-17 review):** H1 (restore highlight fit), M1 (`focusNodeId`), M2 (full legend: tier/role/edge, not just space), M3 (zoom slider), M4 (update-in-place, no full remount), M6 (ref semantics note). These are marked inline.

This task is decomposed into verifiable sub-steps. Commit after each sub-step.

#### 6.1 — Mount sigma + build graph + run layout

- [ ] **Step 1: Replace imports and the rendering body**

At the top of `GraphView.tsx`, remove the cytoscape imports (`cytoscape`, `cytoscape-cola`, the `cytoscape.use(cola)` line) and add:

```typescript
import Graph from "graphology";
import Sigma from "sigma";
import { buildGraph } from "../graph/graphModel";
import { createForceLayout, type ForceLayout } from "../graph/forceLayout";
import { makeNodeReducer, makeEdgeReducer, type ViewState } from "../graph/sigmaReducers";
import { GRAPH_THEME_TOKENS } from "../graph/visual";
```

- [ ] **Step 2: Mount sigma in an effect**

Inside the component, keep `containerRef`. Replace the cytoscape mount `useLayoutEffect` with:

> **Council C2 — filters must NOT remount.** `App.tsx` currently passes `filteredNodes`/`filteredEdges` (it shrinks the arrays per filter → every toggle changes `nodes`/`edges` identity → remount + camera reset). Change it: pass the **full** `graph.nodes`/`graph.edges` to `GraphView` plus a `filters` prop, and apply the filters inside the reducer (dim/hide), never by shrinking the arrays. See "App.tsx change" at the end of this task. With that, the mount effect's deps are stable across filter toggles.

```typescript
const sigmaRef = useRef<Sigma | null>(null);
const graphRef = useRef<Graph | null>(null);
const layoutRef = useRef<ForceLayout | null>(null);
// Council C1: the SINGLE source of truth for reducer state. Matches ViewState in Task 4 exactly.
const viewStateRef = useRef<ViewState>({
  hoveredNode: null,
  neighbors: new Set(),
  highlightSet: new Set(),
  dimmed: { space: new Set(), tier: new Set(), role: new Set(), edge: new Set() },
  focusKind: null,                 // A1: legend focus — {kind,val} or null (see 6.4)
  attrsById: new Map(),
  edgeTypeById: new Map(),
  dimColor: appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de",
});

// Council C1 + C2: rebuild ONLY when the node/edge SET changes (full payload identity),
// NOT on filters or appearance. Build the reducer lookup maps here so Task 4's reducer
// and Task 6.4's legend share one consistent state — no dimmedSpaces/spaceById.
useEffect(() => {
  if (!containerRef.current) return;

  const graph = buildGraph({ nodes, edges, user_node_id: userNodeId }, appearance);
  graphRef.current = graph;

  const attrsById = new Map<string, { space: string; tier: string; selfRole: string }>();
  graph.forEachNode((id, a) =>
    attrsById.set(id, { space: (a.space as string) ?? "", tier: a.tier as string, selfRole: a.selfRole as string }),
  );
  const edgeTypeById = new Map<string, string>();
  graph.forEachEdge((e, a) => edgeTypeById.set(e, (a.edgeType as string) ?? ""));
  viewStateRef.current.attrsById = attrsById;
  viewStateRef.current.edgeTypeById = edgeTypeById;

  const renderer = new Sigma(graph, containerRef.current, {
    enableEdgeEvents: true,
    labelRenderedSizeThreshold: 8,
    nodeReducer: (node, data) => makeNodeReducer(viewStateRef.current)(node, data),
    edgeReducer: (edge, data) =>
      makeEdgeReducer(viewStateRef.current, (e) => [graph.source(e), graph.target(e)])(edge, data),
  });
  sigmaRef.current = renderer;

  const layout = createForceLayout(graph);
  layoutRef.current = layout;
  layout.start();

  return () => {
    layout.kill();
    renderer.kill();
    sigmaRef.current = null;
    graphRef.current = null;
    layoutRef.current = null;
  };
}, [nodes, edges, userNodeId]);

// Council M4 + A2: re-style WITHOUT remounting. Reads current props (deps include
// nodes/edges/userNodeId so it never recolors a stale set), but only recolors/resizes
// in place — never recreates sigma/worker, never resets the camera.
useEffect(() => {
  const g = graphRef.current, r = sigmaRef.current;
  if (!g || !r) return;
  applyAppearance(g, { nodes, edges, user_node_id: userNodeId }, appearance);
  viewStateRef.current.dimColor = appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de";
  r.refresh();
}, [appearance, nodes, edges, userNodeId]);
```

> **`applyAppearance(graph, data, appearance)`** is the in-place restyle helper added in Task 3 (recolors/resizes existing nodes using `visual.ts`; never adds/removes nodes).
>
> **App.tsx change (Council C2)** — at the end of this task, switch the `<GraphView>` props from `nodes={filteredNodes} edges={filteredEdges}` to `nodes={graph.nodes} edges={graph.edges} filters={filters}`. Keep `filteredNodes`/`filteredEdges` only for the count badge (`nodeCount`). Add a `filters` prop to the `Props` interface; in the mount effect, seed `viewStateRef.current.dimmed` from `filters` and add a small effect that updates `dimmed` + `r.refresh()` when `filters` change (no remount). The reducer then hides/dims filtered-out nodes/edges. This is what makes filter toggles cost a `refresh()`, not a rebuild.

- [ ] **Step 3: Build, run, eyeball**

Run: `( cd ui && npm run build )` → Expected: compiles (legend/zoom JSX may still reference removed cytoscape refs; if so, temporarily stub them — they're rewired in 6.3/6.4. Prefer doing 6.1→6.4 in one branch of edits, committing per sub-step once each compiles.)

Start the app (`make restart`, then open http://localhost:8787) and confirm: nodes render in WebGL, the graph **spreads into organic clusters and settles** (no rigid grid), colors match tiers/spaces. Screenshot it.

- [ ] **Commit:** `git commit -am "feat(ui): mount sigma + FA2 layout in GraphView"`

#### 6.2 — Hover highlight + selection

- [ ] **Step 4: Wire pointer events to reducer state**

After creating `renderer` in the mount effect, add:

```typescript
function neighborsOf(id: string): Set<string> {
  const s = new Set<string>();
  graph.forEachNeighbor(id, (n) => s.add(n));
  return s;
}
function setHover(id: string | null) {
  viewStateRef.current.hoveredNode = id;
  viewStateRef.current.neighbors = id ? neighborsOf(id) : new Set();
  renderer.refresh();
}

renderer.on("enterNode", ({ node }) => setHover(node));
renderer.on("leaveNode", () => setHover(null));
renderer.on("clickNode", ({ node }) => onNodeSelectRef.current(node));
renderer.on("clickStage", () => setHover(null));
```

Keep the existing `onNodeSelectRef` pattern (current lines 426–427).

- [ ] **Step 5: Verify hover**

Rebuild + reload. Hovering a node highlights it + neighbors and dims the rest; clicking a node fires selection (side panel opens); clicking empty space clears. Screenshot the hover state.

- [ ] **Commit:** `git commit -am "feat(ui): sigma hover highlight + click selection"`

#### 6.3 — Imperative ref API on sigma

- [ ] **Step 6: Re-implement the ref methods**

Replace the `useImperativeHandle(ref, ...)` block (current lines 444–502) with sigma equivalents, keeping the **same method names/signatures**:

```typescript
useImperativeHandle(ref, () => ({
  focusNode(id: string) {
    const r = sigmaRef.current, g = graphRef.current;
    if (!r || !g || !g.hasNode(id)) return;
    const { x, y } = r.getNodeDisplayData(id)!;
    r.getCamera().animate({ x, y, ratio: 0.4 }, { duration: 400 });
  },
  highlightNode(id: string) {
    const g = graphRef.current, r = sigmaRef.current;
    if (!g || !r || !g.hasNode(id)) return;
    // Council A4: search-hover (App.tsx:245) is GLOW-ONLY in the current view —
    // it highlights the node WITHOUT dimming the rest. Do not reuse the mouse-hover
    // path (which dims). Use the dedicated glowOnly set; the reducer marks it
    // highlighted but dims nobody.
    viewStateRef.current.hoveredNode = null;
    viewStateRef.current.glowOnly = new Set([id]);
    r.refresh();
  },
  highlightNodes(ids: string[]) {
    const g = graphRef.current, r = sigmaRef.current;
    if (!g || !r) return;
    const present = ids.filter((i) => g.hasNode(i));
    if (!present.length) return;
    // Council H1/M6: a multi-node highlight is NOT a hover. Use the dedicated
    // highlightSet (so the reducer keeps ALL of them vivid + dims the rest), and
    // restore the current view's fit/center of the matched set (Insights/Review
    // rely on the viewport framing, not just recoloring).
    viewStateRef.current.hoveredNode = null;
    viewStateRef.current.highlightSet = new Set(present);
    fitToNodes(r, present);   // camera fit+center over the matched nodes (see helper)
    r.refresh();
  },
  clearHighlight() {
    const r = sigmaRef.current;
    viewStateRef.current.hoveredNode = null;
    viewStateRef.current.neighbors = new Set();
    viewStateRef.current.highlightSet = new Set();
    viewStateRef.current.glowOnly = new Set();
    r?.refresh();
  },
}));
```

- [ ] **Step 6b: `fitToNodes` helper (Council A3 — concrete, parity with `cy.fit(collection,120)` + clamp)**

Add this module-local helper in `GraphView.tsx`. It mirrors the current `cy.fit(coll,120)` + `Math.max(currentZoom,1.2)` clamp (current lines 488–495) using the graphology positions (authoritative after settle) and sigma's camera:

```typescript
const FIT_PADDING_RATIO = 0.15;   // ~120px of padding at the default 900px viewport height

function fitToNodes(renderer: Sigma, graph: Graph, ids: string[]) {
  if (!ids.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const id of ids) {
    const x = graph.getNodeAttribute(id, "x") as number;
    const y = graph.getNodeAttribute(id, "y") as number;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const camera = renderer.getCamera();
  // Graph-space extent → camera ratio. Larger extent ⇒ larger ratio (more zoomed out).
  const { width, height } = renderer.getDimensions();
  const spanX = Math.max(maxX - minX, 1e-6), spanY = Math.max(maxY - minY, 1e-6);
  const graphToView = Math.max(spanX / width, spanY / height);
  const fitRatio = graphToView * (1 + FIT_PADDING_RATIO);
  // Parity clamp: never zoom IN past the old floor (cy clamped to max(currentZoom, 1.2)).
  // Sigma ratio is inverse of zoom, so clamp the ratio to a max (don't over-zoom in).
  const ratio = Math.min(camera.ratio, Math.max(fitRatio, 0.25));
  camera.animate({ x: cx, y: cy, ratio }, { duration: 400 });
}
```

> Call it as `fitToNodes(r, g, present)` in `highlightNodes` (pass the graph). During implementation, sanity-check the `ratio` direction against the installed sigma version (ratio is inverse of zoom); adjust the clamp if a real 2-node Insights highlight over- or under-zooms.

> **`ViewState` additions (Task 4):** `highlightSet: Set<string>` (multi-highlight: members vivid, rest dim) and `glowOnly: Set<string>` (A4: members highlighted but **nobody dims**). Reducer precedence: legend-dim → `glowOnly` (glow, no dim) → `highlightSet` (focus+dim) → hover (focus+dim). Extend Task 4 tests for both `highlightSet` (members vivid, non-members dim) and `glowOnly` (member highlighted, others UNCHANGED — not dimmed).

- [ ] **Step 7: Verify callers**

From the Insights or Review panel, trigger a node focus/highlight (the actions that call `highlightNodes`). Confirm the graph highlights the right nodes. Rebuild + reload first.

- [ ] **Commit:** `git commit -am "feat(ui): port GraphView imperative ref API to sigma"`

#### 6.4 — Full legend reuse + FOCUS semantics (Council M2 + A1)

The current view has FOUR legend groups: `spaceLegend`, `tierLegend`, `roleLegend`, `edgeLegend` (counts at current lines ~922–953; JSX further down). **Port all four verbatim** (DOM, renderer-independent), and reproduce the current view's **focus** semantics (Council A1, André's choice).

> **Two distinct dimming systems — do not conflate them:**
> - **Legend click = FOCUS** (current `legendFocus`, lines ~850–875 / 969–1008): clicking a legend item highlights *that* item's nodes, **dims everything else**, and **fits the camera** to the focused set. Clicking the active item again clears focus. This is parity (A1).
> - **App.tsx filters = HIDE** (Council C2): the `filters` prop drives `dimmed.*` — filtered-out nodes/edges dim/hide. This is the existing filter behavior, just moved from array-shrinking to the reducer.
> Both feed the reducer; focus takes precedence over filter-dim.

- [ ] **Step 8: Add focus state (A1) + filter-dim state (C2) to ViewState**

`ViewState` (Task 4) gains:
- `focusKind: { kind: "space" | "tier" | "role" | "edge"; val: string } | null` — the active legend focus (A1).
- `dimmed: { space; tier; role; edge: Set<string> }` — the App.tsx filters (C2, HIDE).
- `attrsById`/`edgeTypeById` — built in the mount effect (already added in 6.1).

Legend focus handler (clicking a legend row):

```typescript
const [focusKind, setFocusKind] = useState<{ kind: string; val: string } | null>(null);

function focusLegend(kind: "space" | "tier" | "role" | "edge", val: string) {
  setFocusKind((prev) => {
    const next = prev && prev.kind === kind && prev.val === val ? null : { kind, val };
    viewStateRef.current.focusKind = next;
    const r = sigmaRef.current, g = graphRef.current;
    if (next && r && g) fitToNodes(r, g, idsMatching(g, kind, val)); // focus = fit to the matched set
    r?.refresh();
    return next;
  });
}
```

`idsMatching(graph, kind, val)` returns node ids whose attribute matches (space/tier/selfRole), or — for `edge` — the endpoints of edges of that type. Implement beside `fitToNodes`.

- [ ] **Step 9: Reducer focus logic (Task 4) + wire the JSX + verify**

In `sigmaReducers.ts`, the `nodeReducer` precedence becomes: **filter-dim** (`dimmed.*` → dim) → **focus** (`focusKind` set: a node NOT matching the focus dims; matching stays vivid + `highlighted`) → glowOnly → highlightSet → hover. The `edgeReducer`: filter-dim by `dimmed.edge`, then under focus keep an edge vivid only if both endpoints match. Add Task 4 tests for `focusKind` (matching node vivid, non-matching dim).

Wire each legend row's `onClick` to `focusLegend(kind, val)` (space rawKey `""` for "(no space)"); render the active row marked (accent), others normal. Drop the old cytoscape `legendFocus`/graph mutations; `clusterBySpace` still only gates `showLegend`.

Rebuild + reload. Click a row in EACH group → that item's nodes stay vivid, the rest dim, camera fits the set; click again → clears. Screenshot.

- [ ] **Commit:** `git commit -am "feat(ui): legend focus (space/tier/role/edge) + filter-dim via reducer"`

#### 6.5 — Node drag (reheat) + hover tooltip

Closes two parity items from the spec's visual-mapping table: "drag a node → re-heat FA2" and the hover tooltip.

- [ ] **Step 10: Drag a node and re-heat the layout**

In the mount effect, track a dragged node and pin it under the cursor; release re-heats FA2:

Follow sigma's canonical drag pattern (camera panning is suppressed by `preventSigmaDefault()`, not a camera enable/disable API — that does not exist):

```typescript
let dragged: string | null = null;
renderer.on("downNode", ({ node }) => {
  dragged = node;
  layout.stop();              // freeze sim while dragging
});
renderer.getMouseCaptor().on("mousemovebody", (e) => {
  if (!dragged) return;
  const pos = renderer.viewportToGraph(e);
  graph.setNodeAttribute(dragged, "x", pos.x);
  graph.setNodeAttribute(dragged, "y", pos.y);
  e.preventSigmaDefault();    // stop the camera from panning during drag
  e.original.preventDefault();
  e.original.stopPropagation();
});
renderer.getMouseCaptor().on("mouseup", () => {
  if (!dragged) return;
  dragged = null;
  layout.reheat();            // settle around the moved node
});
```

- [ ] **Step 11: Hover tooltip (label + space)**

Add a positioned DOM tooltip driven by `enterNode`/`leaveNode`. Reuse the existing tooltip element/styles if the old GraphView had one; otherwise add a `div` with `position: absolute; pointer-events: none`. In `setHover` (Step 4) extend the enter handler:

```typescript
renderer.on("enterNode", ({ node }) => {
  setHover(node);
  const { x, y } = renderer.getNodeDisplayData(node)!;
  const label = graph.getNodeAttribute(node, "label") as string;
  const space = (graph.getNodeAttribute(node, "space") as string) || "(no space)";
  showTooltip(label, space, x, y); // sets text + left/top, makes the div visible
});
renderer.on("leaveNode", () => { setHover(null); hideTooltip(); });
```

Implement `showTooltip`/`hideTooltip` as small helpers over a `tooltipRef` div rendered in the component (mirror the current view's tooltip markup if present).

- [ ] **Step 12: Verify drag + tooltip**

Rebuild + reload. Dragging a node moves it and the layout re-settles on release; hovering shows the label + space tooltip. Screenshot both.

- [ ] **Commit:** `git commit -am "feat(ui): node drag reheat + hover tooltip"`

#### 6.6 — `focusNodeId` prop + zoom controls (Council M1, M3)

- [ ] **Step 13: React to the `focusNodeId` prop**

The current view centers the graph when `focusNodeId` changes; preserve it. Add an effect:

```typescript
useEffect(() => {
  const r = sigmaRef.current, g = graphRef.current;
  if (!r || !g || !focusNodeId || !g.hasNode(focusNodeId)) return;
  const { x, y } = r.getNodeDisplayData(focusNodeId)!;
  r.getCamera().animate({ x, y, ratio: 0.4 }, { duration: 400 });
}, [focusNodeId]);
```

- [ ] **Step 14: Port the zoom slider (+/−)**

The current view renders a zoom slider/buttons (current constants ~lines 133–136; `zoomSliderValue` state). Keep the JSX/markup; rewire the handlers to the sigma camera:

```typescript
function zoomIn()  { sigmaRef.current?.getCamera().animatedZoom({ duration: 200 }); }
function zoomOut() { sigmaRef.current?.getCamera().animatedUnzoom({ duration: 200 }); }
function zoomTo(ratio: number) { sigmaRef.current?.getCamera().animate({ ratio }, { duration: 200 }); }
function resetView() { sigmaRef.current?.getCamera().animatedReset({ duration: 300 }); }
```

Map the slider value to a camera `ratio` (higher slider = lower ratio = more zoomed-in); wire +/− buttons to `zoomIn`/`zoomOut` and any reset/overview control to `resetView`. Keep the slider's visual range/step from the current view.

- [ ] **Step 15: Verify focus + zoom**

Rebuild + reload. Changing `focusNodeId` (trigger from a caller) centers that node; the +/− buttons and slider zoom the camera; reset returns to overview. Screenshot.

- [ ] **Step 16: Run the full unit suite + typecheck**

Run: `( cd ui && npm run test && npx tsc --noEmit )`
Expected: all unit tests pass; no type errors.

- [ ] **Commit:** `git commit -am "feat(ui): focusNodeId prop + sigma zoom controls"`

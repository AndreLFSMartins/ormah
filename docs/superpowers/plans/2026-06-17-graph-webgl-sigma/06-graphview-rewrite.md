### Task 6: Rewrite GraphView as a sigma orchestrator

The big one. Replace the cytoscape body of `ui/src/components/GraphView.tsx` with sigma + FA2, **preserving the component's external contract** so its callers keep working.

**Files:**
- Modify (rewrite body): `ui/src/components/GraphView.tsx`

> **Before writing anything, read the entire current `ui/src/components/GraphView.tsx`.** It is ~1198 lines. You must preserve two contracts exactly:
> 1. **Props** (current lines 23–31): `nodes`, `edges`, `onNodeSelect`, `focusNodeId`, `userNodeId`, `clusterBySpace`, `appearance`. Keep the same names/types.
> 2. **Imperative ref API** (current lines 444–502): `focusNode(id)`, `highlightNode(id)`, `highlightNodes(ids)`, `clearHighlight()`. These are called by the Insights/Review panels. Step 4 re-implements them on sigma.
>
> Find callers to confirm the contract before/after: `grep -rn "GraphView\|focusNode\|highlightNodes" ui/src` .

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

```typescript
const sigmaRef = useRef<Sigma | null>(null);
const graphRef = useRef<Graph | null>(null);
const layoutRef = useRef<ForceLayout | null>(null);
const viewStateRef = useRef<ViewState>({
  hoveredNode: null,
  neighbors: new Set(),
  dimmedSpaces: new Set(),
  spaceById: new Map(),
  dimColor: appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de",
});

useEffect(() => {
  if (!containerRef.current) return;

  const graph = buildGraph({ nodes, edges, user_node_id: userNodeId }, appearance);
  graphRef.current = graph;

  const spaceById = new Map<string, string>();
  graph.forEachNode((id, attr) => spaceById.set(id, (attr.space as string) ?? ""));
  viewStateRef.current.spaceById = spaceById;

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
  // Rebuild when the data or appearance changes.
}, [nodes, edges, userNodeId, appearance]);
```

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
    viewStateRef.current.hoveredNode = id;
    const s = new Set<string>();
    g.forEachNeighbor(id, (n) => s.add(n));
    viewStateRef.current.neighbors = s;
    r.refresh();
  },
  highlightNodes(ids: string[]) {
    const g = graphRef.current, r = sigmaRef.current;
    if (!g || !r) return;
    const present = ids.filter((i) => g.hasNode(i));
    viewStateRef.current.hoveredNode = present[0] ?? null;
    viewStateRef.current.neighbors = new Set(present);
    r.refresh();
  },
  clearHighlight() {
    const r = sigmaRef.current;
    viewStateRef.current.hoveredNode = null;
    viewStateRef.current.neighbors = new Set();
    r?.refresh();
  },
}));
```

- [ ] **Step 7: Verify callers**

From the Insights or Review panel, trigger a node focus/highlight (the actions that call `highlightNodes`). Confirm the graph highlights the right nodes. Rebuild + reload first.

- [ ] **Commit:** `git commit -am "feat(ui): port GraphView imperative ref API to sigma"`

#### 6.4 — Legend reuse + space dimming

- [ ] **Step 8: Keep the legend JSX, rewire its handlers**

The tier/space/role/edge legend (`spaceLegend`/`tierLegend`/`roleLegend`/`edgeLegend`, current ~lines 915–960, plus their JSX further down) is DOM and renderer-independent — **port it verbatim**. Replace only the click behavior: where a space row currently set cytoscape `legendFocus`, it now toggles `dimmedSpaces`:

```typescript
const [dimmedSpaces, setDimmedSpaces] = useState<Set<string>>(new Set());

function toggleSpace(space: string) {
  setDimmedSpaces((prev) => {
    const next = new Set(prev);
    if (next.has(space)) next.delete(space); else next.add(space);
    viewStateRef.current.dimmedSpaces = next;
    sigmaRef.current?.refresh();
    return next;
  });
}
```

Wire each space legend row's `onClick` to `toggleSpace(name)` (use the raw space key `""` for "(no space)"), and render dimmed rows with reduced opacity to mirror state. Drop the old cytoscape-based `legendFocus`/`clusterBySpace` graph mutations; `clusterBySpace` now only affects legend visibility (`showLegend`), not layout.

- [ ] **Step 9: Verify legend dimming**

Rebuild + reload. Clicking a space in the legend dims that space's nodes; clicking again restores. Screenshot.

- [ ] **Commit:** `git commit -am "feat(ui): wire legend space toggles to sigma dimming"`

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

- [ ] **Step 13: Run the full unit suite + typecheck**

Run: `( cd ui && npm run test && npx tsc --noEmit )`
Expected: all unit tests pass; no type errors.

- [ ] **Commit:** `git commit -am "feat(ui): node drag reheat + hover tooltip"`

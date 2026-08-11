### Task 4: Sigma reducers (hover / dim / focus)

Pure factories that build sigma's `nodeReducer`/`edgeReducer` from the current view state. This is the parity replacement for cytoscape's `glow`/`glow-neighbor` classes (current `GraphView.tsx:460-467`) and the legend dim/focus. No sigma import — the factories take and return plain attribute objects.

State shape consumed (Council H1/M2 — supports hover, multi-highlight, and 4-dimension legend dimming):
- `hoveredNode: string | null` + `neighbors: Set<string>` — on hover, the node + neighbors stay vivid, everyone else dims.
- `highlightSet: Set<string>` — a programmatic multi-node highlight (from `highlightNodes`, separate from hover): every member stays vivid, non-members dim.
- `dimmed: { space; tier; role; edge: Set<string> }` — legend toggles per dimension; a node dims if its space/tier/role is toggled, an edge dims if its type is toggled.
- `attrsById: Map<string, { space; tier; selfRole }>` — per-node attributes the reducer needs for legend matching.

**Files:**
- Create: `ui/src/graph/sigmaReducers.ts`
- Test: `ui/src/graph/sigmaReducers.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/sigmaReducers.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { makeNodeReducer, makeEdgeReducer, type ViewState } from "./sigmaReducers";

const DIM = "#2a2a2a";

function state(over: Partial<ViewState>): ViewState {
  return {
    hoveredNode: null,
    neighbors: new Set<string>(),
    highlightSet: new Set<string>(),
    glowOnly: new Set<string>(),
    focusKind: null,
    dimmed: { space: new Set(), tier: new Set(), role: new Set(), edge: new Set() },
    attrsById: new Map(),
    edgeTypeById: new Map(),
    dimColor: DIM,
    ...over,
  };
}

describe("makeNodeReducer", () => {
  it("passes attributes through when nothing is active", () => {
    const r = makeNodeReducer(state({}));
    const out = r("a", { color: "#abc", label: "A" });
    expect(out.color).toBe("#abc");
    expect(out.label).toBe("A");
  });

  it("dims non-hovered, non-neighbor nodes and highlights the hovered one", () => {
    const r = makeNodeReducer(state({ hoveredNode: "a", neighbors: new Set(["b"]) }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    expect(r("b", { color: "#abc" }).color).toBe("#abc"); // neighbor stays vivid
    const other = r("c", { color: "#abc" });
    expect(other.color).toBe(DIM);
    expect(other.label).toBeUndefined(); // dimmed nodes drop their label
  });

  it("keeps every highlightSet member vivid and dims the rest (multi-highlight)", () => {
    const r = makeNodeReducer(state({ highlightSet: new Set(["a", "b"]) }));
    expect(r("a", { color: "#abc" }).color).toBe("#abc");
    expect(r("b", { color: "#abc" }).color).toBe("#abc");
    expect(r("c", { color: "#abc" }).color).toBe(DIM);
  });

  it("glowOnly highlights the member and dims NOBODY (Council A4, search-hover)", () => {
    const r = makeNodeReducer(state({ glowOnly: new Set(["a"]) }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    const other = r("b", { color: "#abc" });
    expect(other.color).toBe("#abc");        // NOT dimmed
    expect(other.label).toBeUndefined();     // (no label set in input; just confirm color preserved)
  });

  it("legend focus keeps matching nodes vivid and dims non-matching (Council A1)", () => {
    const attrs = new Map([
      ["a", { space: "work", tier: "core", selfRole: "" }],
      ["b", { space: "home", tier: "working", selfRole: "" }],
    ]);
    const r = makeNodeReducer(state({ attrsById: attrs, focusKind: { kind: "space", val: "work" } }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    expect(r("b", { color: "#abc" }).color).toBe(DIM);
  });

  it("dims a node when its space, tier, or role is toggled off", () => {
    const attrs = new Map([
      ["a", { space: "work", tier: "core", selfRole: "" }],
      ["b", { space: "home", tier: "working", selfRole: "identity" }],
    ]);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(["work"]), tier: new Set(), role: new Set(), edge: new Set() } }))("a", { color: "#abc" }).color).toBe(DIM);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(), tier: new Set(["working"]), role: new Set(), edge: new Set() } }))("b", { color: "#abc" }).color).toBe(DIM);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(), tier: new Set(), role: new Set(["identity"]), edge: new Set() } }))("b", { color: "#abc" }).color).toBe(DIM);
  });
});

describe("makeEdgeReducer", () => {
  it("dims an edge when its type is toggled off", () => {
    const st = state({ edgeTypeById: new Map([["e1", "supports"]]) });
    st.dimmed.edge.add("supports");
    const r = makeEdgeReducer(st, () => ["a", "b"]);
    expect(r("e1", { color: "#0f0" }).color).toBe(DIM);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/sigmaReducers.test.ts )`
Expected: FAIL — cannot find module `./sigmaReducers`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/sigmaReducers.ts`:

```typescript
// Plain attribute shapes (sigma's NodeDisplayData/EdgeDisplayData supersets).
export interface NodeAttrs {
  color?: string;
  label?: string;
  size?: number;
  highlighted?: boolean;
  [key: string]: unknown;
}
export interface EdgeAttrs {
  color?: string;
  hidden?: boolean;
  [key: string]: unknown;
}

export interface NodeAttr { space: string; tier: string; selfRole: string }
export type FocusKind = { kind: "space" | "tier" | "role" | "edge"; val: string } | null;

export interface ViewState {
  hoveredNode: string | null;
  neighbors: Set<string>;
  highlightSet: Set<string>;                                   // Council H1: multi-highlight (focus+dim), separate from hover
  glowOnly: Set<string>;                                       // Council A4: search-hover — highlight WITHOUT dimming others
  focusKind: FocusKind;                                        // Council A1: legend focus — match stays vivid, rest dims
  dimmed: { space: Set<string>; tier: Set<string>; role: Set<string>; edge: Set<string> }; // Council C2: App.tsx filters (HIDE)
  attrsById: Map<string, NodeAttr>;
  edgeTypeById: Map<string, string>;
  dimColor: string;
}

// Council C2: App.tsx filters dim/hide a node.
function nodeIsFilterDimmed(node: string, state: ViewState): boolean {
  const a = state.attrsById.get(node);
  if (!a) return false;
  const { space, tier, role } = state.dimmed;
  return space.has(a.space) || tier.has(a.tier) || role.has(a.selfRole);
}

// Council A1: does this node match the active legend focus?
function nodeMatchesFocus(node: string, state: ViewState): boolean {
  if (!state.focusKind) return true;
  const a = state.attrsById.get(node);
  if (!a) return false;
  const { kind, val } = state.focusKind;
  if (kind === "space") return a.space === val;
  if (kind === "tier") return a.tier === val;
  if (kind === "role") return a.selfRole === val;
  return true; // edge focus is decided on edges; nodes only dim via edge endpoints (handled in GraphView's idsMatching)
}

export function makeNodeReducer(state: ViewState) {
  const { hoveredNode, neighbors, highlightSet, glowOnly, focusKind, dimColor } = state;
  const dim = (out: NodeAttrs) => { out.color = dimColor; out.label = undefined; return out; };
  return (node: string, data: NodeAttrs): NodeAttrs => {
    const out: NodeAttrs = { ...data };

    // 1) Filter-dim (App.tsx) wins — a filtered-out node always dims.
    if (nodeIsFilterDimmed(node, state)) return dim(out);

    // 2) glowOnly (search-hover, A4): the member glows; NOBODY else is dimmed.
    if (glowOnly.size > 0) {
      if (glowOnly.has(node)) out.highlighted = true;
      return out;
    }

    // 3) Legend focus (A1): matching nodes vivid, the rest dim.
    if (focusKind) {
      if (nodeMatchesFocus(node, state)) { out.highlighted = true; return out; }
      return dim(out);
    }

    // 4) Programmatic multi-highlight (Insights/Review): members vivid, rest dim.
    if (highlightSet.size > 0) {
      if (highlightSet.has(node)) { out.highlighted = true; return out; }
      return dim(out);
    }

    // 5) Hover: node + neighbors vivid, rest dim.
    if (hoveredNode) {
      if (node === hoveredNode) out.highlighted = true;
      else if (!neighbors.has(node)) return dim(out);
    }
    return out;
  };
}

export function makeEdgeReducer(state: ViewState, sourceTarget: (edge: string) => [string, string]) {
  const { hoveredNode, neighbors, highlightSet, glowOnly, dimmed, edgeTypeById, dimColor } = state;
  return (edge: string, data: EdgeAttrs): EdgeAttrs => {
    const out: EdgeAttrs = { ...data };

    // Filter-dim by edge type (App.tsx).
    if (dimmed.edge.size > 0 && dimmed.edge.has(edgeTypeById.get(edge) ?? "")) {
      out.color = dimColor;
      return out;
    }
    if (glowOnly.size > 0) return out;           // glowOnly never dims edges

    const [s, t] = sourceTarget(edge);
    if (highlightSet.size > 0) {
      if (!(highlightSet.has(s) && highlightSet.has(t))) out.color = dimColor;
      return out;
    }
    if (hoveredNode) {
      const touches = s === hoveredNode || t === hoveredNode ||
        (neighbors.has(s) && neighbors.has(t));
      if (!touches) out.color = dimColor;
    }
    return out;
  };
}
```

> The legend-focus case for `edge` kind dims at the edge level (handled in GraphView by passing the matched endpoints), so `nodeMatchesFocus` returns `true` for `kind==="edge"` and the visible distinction comes from the edge reducer + the fit. Keep node-level focus to space/tier/role.

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/sigmaReducers.test.ts )`
Expected: PASS — 7 passed (6 node: passthrough, hover, highlightSet, glowOnly, focus, legend-dim; + 1 edge).

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/sigmaReducers.ts ui/src/graph/sigmaReducers.test.ts
git commit -m "feat(ui): pure sigma node/edge reducers for hover + legend dim"
```

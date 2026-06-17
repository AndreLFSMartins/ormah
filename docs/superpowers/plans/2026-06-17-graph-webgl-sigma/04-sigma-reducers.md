### Task 4: Sigma reducers (hover / dim / focus)

Pure factories that build sigma's `nodeReducer`/`edgeReducer` from the current view state. This is the parity replacement for cytoscape's `glow`/`glow-neighbor` classes (current `GraphView.tsx:460-467`) and the legend dim/focus. No sigma import — the factories take and return plain attribute objects.

State shape consumed:
- `hoveredNode: string | null` and `neighbors: Set<string>` — when hovering, the node + its neighbors stay vivid, everyone else dims.
- `dimmedSpaces: Set<string>` — spaces toggled off in the legend (their nodes dim).

**Files:**
- Create: `ui/src/graph/sigmaReducers.ts`
- Test: `ui/src/graph/sigmaReducers.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/sigmaReducers.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { makeNodeReducer, type ViewState } from "./sigmaReducers";

const DIM = "#2a2a2a";

function state(over: Partial<ViewState>): ViewState {
  return {
    hoveredNode: null,
    neighbors: new Set<string>(),
    dimmedSpaces: new Set<string>(),
    spaceById: new Map<string, string>(),
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

  it("dims nodes whose space is toggled off", () => {
    const r = makeNodeReducer(state({
      dimmedSpaces: new Set(["work"]),
      spaceById: new Map([["a", "work"], ["b", "home"]]),
    }));
    expect(r("a", { color: "#abc" }).color).toBe(DIM);
    expect(r("b", { color: "#abc" }).color).toBe("#abc");
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

export interface ViewState {
  hoveredNode: string | null;
  neighbors: Set<string>;
  dimmedSpaces: Set<string>;
  spaceById: Map<string, string>;
  dimColor: string;
}

export function makeNodeReducer(state: ViewState) {
  const { hoveredNode, neighbors, dimmedSpaces, spaceById, dimColor } = state;
  return (node: string, data: NodeAttrs): NodeAttrs => {
    const out: NodeAttrs = { ...data };

    if (dimmedSpaces.size > 0 && dimmedSpaces.has(spaceById.get(node) ?? "")) {
      out.color = dimColor;
      out.label = undefined;
      return out;
    }

    if (hoveredNode) {
      if (node === hoveredNode) {
        out.highlighted = true;
      } else if (!neighbors.has(node)) {
        out.color = dimColor;
        out.label = undefined;
      }
    }
    return out;
  };
}

export function makeEdgeReducer(state: ViewState, sourceTarget: (edge: string) => [string, string]) {
  const { hoveredNode, neighbors, dimColor } = state;
  return (edge: string, data: EdgeAttrs): EdgeAttrs => {
    const out: EdgeAttrs = { ...data };
    if (hoveredNode) {
      const [s, t] = sourceTarget(edge);
      const touches = s === hoveredNode || t === hoveredNode ||
        (neighbors.has(s) && neighbors.has(t));
      if (!touches) out.color = dimColor;
    }
    return out;
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/sigmaReducers.test.ts )`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/sigmaReducers.ts ui/src/graph/sigmaReducers.test.ts
git commit -m "feat(ui): pure sigma node/edge reducers for hover + legend dim"
```

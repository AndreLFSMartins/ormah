### Task 3: Graph model (payload → graphology)

Pure function turning the `/ui/graph` payload into a graphology `Graph` with sigma-ready attributes. Seeds random initial positions (FA2 requires `x`/`y` before running). Filters edges whose endpoints are missing (matches current behavior, `GraphView.tsx:545-546`).

**Files:**
- Create: `ui/src/graph/graphModel.ts`
- Test: `ui/src/graph/graphModel.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/graphModel.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildGraph } from "./graphModel";
import { DEFAULT_GRAPH_APPEARANCE } from "../graphAppearance";
import type { Edge, GraphData, MemoryNode } from "../types";

function node(over: Partial<MemoryNode>): MemoryNode {
  return {
    id: "n", type: "fact", tier: "working", source: "x", space: null,
    title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "", ...over,
  };
}
function data(over: Partial<GraphData>): GraphData {
  return { nodes: [], edges: [], user_node_id: null, ...over };
}

describe("buildGraph", () => {
  it("creates a node per payload node with sigma attributes", () => {
    const g = buildGraph(
      data({ nodes: [node({ id: "a", tier: "core", title: "A", access_count: 4 })] }),
      DEFAULT_GRAPH_APPEARANCE,
    );
    expect(g.order).toBe(1);
    expect(g.getNodeAttribute("a", "label")).toBe("A");
    expect(g.getNodeAttribute("a", "color")).toBe(DEFAULT_GRAPH_APPEARANCE.colors.core);
    expect(g.getNodeAttribute("a", "size")).toBeGreaterThan(0);
    expect(typeof g.getNodeAttribute("a", "x")).toBe("number");
    expect(typeof g.getNodeAttribute("a", "y")).toBe("number");
  });

  it("handles missing space/tier without throwing", () => {
    const g = buildGraph(data({ nodes: [node({ id: "a", space: null })] }), DEFAULT_GRAPH_APPEARANCE);
    expect(g.getNodeAttribute("a", "space")).toBe("");
  });

  it("returns an empty graph for empty payload", () => {
    const g = buildGraph(data({}), DEFAULT_GRAPH_APPEARANCE);
    expect(g.order).toBe(0);
    expect(g.size).toBe(0);
  });

  it("adds an isolated node with no edges", () => {
    const g = buildGraph(data({ nodes: [node({ id: "lonely" })] }), DEFAULT_GRAPH_APPEARANCE);
    expect(g.degree("lonely")).toBe(0);
  });

  it("colors edges by type and drops edges to missing nodes", () => {
    const nodes = [node({ id: "a" }), node({ id: "b" })];
    const edges: Edge[] = [
      { source_id: "a", target_id: "b", edge_type: "supports", weight: 1, created: "" },
      { source_id: "a", target_id: "ghost", edge_type: "related_to", weight: 1, created: "" },
    ];
    const g = buildGraph(data({ nodes, edges }), DEFAULT_GRAPH_APPEARANCE);
    expect(g.size).toBe(1);
    const eid = g.edges()[0];
    expect(g.getEdgeAttribute(eid, "color")).toBe("#4a7a4a");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/graphModel.test.ts )`
Expected: FAIL — cannot find module `./graphModel`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/graphModel.ts`:

```typescript
import Graph from "graphology";
import type { GraphAppearance } from "../graphAppearance";
import type { GraphData } from "../types";
import {
  computeSelfRoles,
  displayNodeSize,
  edgeColor,
  nodeLabel,
  tierColor,
} from "./visual";

// Deterministic small ring seed so FA2 has x/y to start from.
// (FA2 rescales; exact seed positions don't matter, only that they exist and differ.)
function seedPosition(index: number, total: number): { x: number; y: number } {
  const angle = total > 0 ? (2 * Math.PI * index) / total : 0;
  const r = 100 + (index % 7);
  return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
}

export function buildGraph(data: GraphData, appearance: GraphAppearance): Graph {
  const graph = new Graph({ multi: true, type: "directed" });
  const roles = computeSelfRoles(data.nodes, data.edges, data.user_node_id);

  data.nodes.forEach((n, i) => {
    const role = roles.get(n.id) ?? "";
    const { x, y } = seedPosition(i, data.nodes.length);
    graph.addNode(n.id, {
      x,
      y,
      size: displayNodeSize(n.access_count, role),
      color: tierColor(n.tier, role, appearance),
      label: nodeLabel(n),
      space: n.space || "",
      tier: n.tier,
      selfRole: role,
    });
  });

  for (const e of data.edges) {
    if (!graph.hasNode(e.source_id) || !graph.hasNode(e.target_id)) continue;
    graph.addEdge(e.source_id, e.target_id, {
      size: 1,
      color: edgeColor(e.edge_type, appearance.theme),
      edgeType: e.edge_type,
    });
  }

  return graph;
}

// Council M4: re-style an EXISTING graph in place (no add/remove of nodes) when
// the appearance/theme changes — so GraphView can recolor/resize without
// remounting sigma + the worker. Uses the same visual.ts functions as buildGraph.
export function applyAppearance(graph: Graph, data: GraphData, appearance: GraphAppearance): void {
  const roles = computeSelfRoles(data.nodes, data.edges, data.user_node_id);
  for (const n of data.nodes) {
    if (!graph.hasNode(n.id)) continue;
    const role = roles.get(n.id) ?? "";
    graph.setNodeAttribute(n.id, "color", tierColor(n.tier, role, appearance));
    graph.setNodeAttribute(n.id, "size", displayNodeSize(n.access_count, role));
  }
  graph.forEachEdge((edge, attr) => {
    graph.setEdgeAttribute(edge, "color", edgeColor((attr.edgeType as string) ?? "", appearance.theme));
  });
}
```

- [ ] **Step 4: Add an applyAppearance test (Council M4)**

Append to `graphModel.test.ts`:

```typescript
import { buildGraph, applyAppearance } from "./graphModel";

describe("applyAppearance", () => {
  it("recolors existing nodes when the theme flips, without changing node count", () => {
    const d = data({ nodes: [node({ id: "a", tier: "core" })] });
    const g = buildGraph(d, { ...DEFAULT_GRAPH_APPEARANCE, theme: "dark" });
    const before = g.getNodeAttribute("a", "color");
    applyAppearance(g, d, { ...DEFAULT_GRAPH_APPEARANCE, theme: "light",
      colors: { core: "#111111", working: "#222222", archival: "#333333" } });
    expect(g.order).toBe(1);                       // no nodes added/removed
    expect(g.getNodeAttribute("a", "color")).toBe("#111111");
    expect(g.getNodeAttribute("a", "color")).not.toBe(before);
  });
});
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `( cd ui && npx vitest run src/graph/graphModel.test.ts )`
Expected: PASS — 6 passed (5 buildGraph + 1 applyAppearance).

- [ ] **Step 6: Commit**

```bash
git add ui/src/graph/graphModel.ts ui/src/graph/graphModel.test.ts
git commit -m "feat(ui): buildGraph + applyAppearance (in-place restyle) for graphology"
```

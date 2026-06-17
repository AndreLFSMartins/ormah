import { describe, it, expect } from "vitest";
import { buildGraph, applyAppearance } from "./graphModel";
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

  it("sizes nodes by unique-neighbour count: connected > isolated, isolated at floor", () => {
    const nodes = [node({ id: "hub" }), node({ id: "a" }), node({ id: "b" }), node({ id: "lonely" })];
    const edges: Edge[] = [
      { source_id: "hub", target_id: "a", edge_type: "related_to", weight: 1, created: "" },
      { source_id: "hub", target_id: "b", edge_type: "related_to", weight: 1, created: "" },
    ];
    const g = buildGraph(data({ nodes, edges }), DEFAULT_GRAPH_APPEARANCE);
    const hubSize = g.getNodeAttribute("hub", "size") as number;
    const lonelySize = g.getNodeAttribute("lonely", "size") as number;
    expect(hubSize).toBeGreaterThan(lonelySize); // 2 unique neighbours > 0
    expect(lonelySize).toBe(2);                  // isolated -> floor
  });

  it("counts UNIQUE neighbours, not parallel edges (multigraph)", () => {
    const nodes = [node({ id: "x" }), node({ id: "y" }), node({ id: "p" }), node({ id: "q" })];
    const edges: Edge[] = [
      { source_id: "x", target_id: "y", edge_type: "supports", weight: 1, created: "" },
      { source_id: "x", target_id: "y", edge_type: "defines", weight: 1, created: "" },
      { source_id: "x", target_id: "y", edge_type: "related_to", weight: 1, created: "" },
      { source_id: "p", target_id: "q", edge_type: "related_to", weight: 1, created: "" },
    ];
    const g = buildGraph(data({ nodes, edges }), DEFAULT_GRAPH_APPEARANCE);
    // x has 1 unique neighbour (y) via 3 edges; p has 1 unique neighbour (q) via 1 edge.
    expect(g.getNodeAttribute("x", "size")).toBe(g.getNodeAttribute("p", "size"));
  });
});

describe("applyAppearance", () => {
  it("recolors existing nodes when the theme flips, without changing node count", () => {
    const d = data({ nodes: [node({ id: "a", tier: "core" })] });
    const g = buildGraph(d, { ...DEFAULT_GRAPH_APPEARANCE, theme: "dark" });
    const before = g.getNodeAttribute("a", "color");
    applyAppearance(g, d, { ...DEFAULT_GRAPH_APPEARANCE, theme: "light",
      colors: { core: "#111111", working: "#222222", archival: "#333333" } });
    expect(g.order).toBe(1);
    expect(g.getNodeAttribute("a", "color")).toBe("#111111");
    expect(g.getNodeAttribute("a", "color")).not.toBe(before);
  });

  it("keeps degree-based size after appearance changes (hub > isolated)", () => {
    const nodes = [
      node({ id: "hub", access_count: 0 }),
      node({ id: "a", access_count: 0 }),
      node({ id: "lonely", access_count: 999 }), // misleading: high access, zero connections
    ];
    const edges: Edge[] = [
      { source_id: "hub", target_id: "a", edge_type: "related_to", weight: 1, created: "" },
    ];
    const d = data({ nodes, edges });
    const g = buildGraph(d, DEFAULT_GRAPH_APPEARANCE);
    applyAppearance(g, d, { ...DEFAULT_GRAPH_APPEARANCE,
      colors: { core: "#111111", working: "#222222", archival: "#333333" } });
    const hubSize = g.getNodeAttribute("hub", "size") as number;       // 1 neighbour
    const lonelySize = g.getNodeAttribute("lonely", "size") as number; // 0 neighbours, access 999
    expect(hubSize).toBeGreaterThan(lonelySize); // connections win, not access_count
    expect(lonelySize).toBe(2);                  // isolated -> floor (NOT inflated by access 999)
  });
});

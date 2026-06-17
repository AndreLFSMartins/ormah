import { describe, it, expect } from "vitest";
import {
  tierColor,
  edgeColor,
  displayNodeSize,
  nodeLabel,
  computeSelfRoles,
} from "./visual";
import { DEFAULT_GRAPH_APPEARANCE } from "../graphAppearance";
import type { Edge, MemoryNode } from "../types";

const A = DEFAULT_GRAPH_APPEARANCE;

function node(over: Partial<MemoryNode>): MemoryNode {
  return {
    id: "n", type: "fact", tier: "working", source: "x", space: null,
    title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "", ...over,
  };
}

describe("visual", () => {
  it("colors self and identity roles distinctly", () => {
    expect(tierColor("working", "self", A)).toBe("#74b3a5");
    expect(tierColor("working", "identity", A)).toBe("#4d8a7e");
    expect(tierColor("core", "", A)).toBe(A.colors.core);
  });

  it("maps edge types to theme colors", () => {
    expect(edgeColor("supports", "dark")).toBe("#4a7a4a");
    expect(edgeColor("related_to", "dark")).toBe("#333");
  });

  it("sizes self nodes at least the self floor", () => {
    expect(displayNodeSize(0, "self")).toBeGreaterThanOrEqual(Math.round(36 * 1.2));
  });

  it("labels prefer title, then content slice, then id prefix", () => {
    expect(nodeLabel(node({ title: "T" }))).toBe("T");
    expect(nodeLabel(node({ title: null, content: "abc" }))).toBe("abc");
    expect(nodeLabel(node({ id: "abc-123", title: null, content: "" }))).toBe("abc");
  });

  it("computes self/identity roles from defines edges", () => {
    const nodes = [node({ id: "u" }), node({ id: "p" }), node({ id: "q" })];
    const edges: Edge[] = [
      { source_id: "u", target_id: "p", edge_type: "defines", weight: 1, created: "" },
    ];
    const roles = computeSelfRoles(nodes, edges, "u");
    expect(roles.get("u")).toBe("self");
    expect(roles.get("p")).toBe("identity");
    expect(roles.get("q") ?? "").toBe("");
  });
});

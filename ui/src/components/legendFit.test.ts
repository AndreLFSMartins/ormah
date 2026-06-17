import { describe, it, expect } from "vitest";
import Graph from "graphology";
import { focusFitIds } from "./legendFit";

// Builds a tiny graph with two tiers so we can assert which ids feed fitToNodes.
function tinyGraph(): Graph {
  const g = new Graph();
  g.addNode("a", { tier: "core", space: "s1", selfRole: "r1" });
  g.addNode("b", { tier: "core", space: "s2", selfRole: "r2" });
  g.addNode("c", { tier: "working", space: "s1", selfRole: "r1" });
  g.addEdge("a", "b", { edgeType: "relates" });
  g.addEdge("a", "c", { edgeType: "links" });
  return g;
}

describe("focusFitIds", () => {
  it("returns only the matching nodes when a focus is active", () => {
    const ids = focusFitIds(tinyGraph(), { kind: "tier", val: "core" });
    expect(ids.sort()).toEqual(["a", "b"]);
  });

  it("returns edge endpoints when the focus is an edge type", () => {
    const ids = focusFitIds(tinyGraph(), { kind: "edge", val: "links" });
    expect(ids.sort()).toEqual(["a", "c"]);
  });

  // The bug: clearing the focus (next === null) used to skip the camera entirely,
  // leaving it zoomed on the previous focus. Clearing must re-fit the whole graph.
  it("returns ALL nodes when the focus is cleared (next === null)", () => {
    const ids = focusFitIds(tinyGraph(), null);
    expect(ids.sort()).toEqual(["a", "b", "c"]);
  });
});

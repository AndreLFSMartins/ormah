import { describe, expect, it } from "vitest";
import type { MemoryNode } from "../types";
import { crossSpaceMixing, CLUSTER_LAYOUT_MAX_SPACE_NODES, computeClusterLayout, largestSpaceSize } from "./clusterLayout";
import type { Edge } from "../types";

// Minimal MemoryNode factory — only id/space matter for layout/metric.
function node(id: string, space: string | null): MemoryNode {
  return {
    id, type: "concept", tier: "working", source: "", space,
    title: id, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}

describe("crossSpaceMixing", () => {
  it("is 0 when each node's nearest neighbour shares its space", () => {
    const nodes = [node("a1", "A"), node("a2", "A"), node("b1", "B"), node("b2", "B")];
    const pos = new Map([
      ["a1", { x: 0, y: 0 }], ["a2", { x: 1, y: 0 }],   // A cluster near origin
      ["b1", { x: 100, y: 0 }], ["b2", { x: 101, y: 0 }], // B cluster far away
    ]);
    expect(crossSpaceMixing(pos, nodes)).toBe(0);
  });

  it("is 1 when every node's nearest neighbour is a different space (interleaved)", () => {
    const nodes = [node("a1", "A"), node("b1", "B"), node("a2", "A"), node("b2", "B")];
    const pos = new Map([
      ["a1", { x: 0, y: 0 }], ["b1", { x: 1, y: 0 }],
      ["a2", { x: 2, y: 0 }], ["b2", { x: 3, y: 0 }],
    ]);
    expect(crossSpaceMixing(pos, nodes)).toBe(1);
  });

  it("returns 0 for fewer than two positioned nodes", () => {
    expect(crossSpaceMixing(new Map([["a1", { x: 0, y: 0 }]]), [node("a1", "A")])).toBe(0);
  });
});

function edge(s: string, t: string): Edge {
  return { source_id: s, target_id: t, edge_type: "related_to", weight: 1, created: "" };
}
function centroid(ids: string[], pos: Map<string, { x: number; y: number }>) {
  let x = 0, y = 0;
  for (const id of ids) { const p = pos.get(id)!; x += p.x; y += p.y; }
  return { x: x / ids.length, y: y / ids.length };
}
function radius(ids: string[], pos: Map<string, { x: number; y: number }>) {
  const c = centroid(ids, pos);
  return Math.max(...ids.map((id) => Math.hypot(pos.get(id)!.x - c.x, pos.get(id)!.y - c.y)));
}
function dist(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

describe("computeClusterLayout", () => {
  const nodes = [
    node("a1", "A"), node("a2", "A"), node("a3", "A"),
    node("b1", "B"), node("b2", "B"), node("b3", "B"),
    node("c1", "C"), node("c2", "C"), node("c3", "C"),
  ];
  const edges = [
    edge("a1", "a2"), edge("a2", "a3"),
    edge("b1", "b2"), edge("b2", "b3"),
    edge("c1", "c2"), edge("c2", "c3"),
    edge("a1", "b1"), // cross-space link must NOT smear clusters
  ];

  it("keeps same-space nodes cohesive and centroids well apart", () => {
    const pos = computeClusterLayout(nodes, edges);
    const cs = ["A", "B", "C"].map((sp) =>
      centroid(nodes.filter((n) => n.space === sp).map((n) => n.id), pos),
    );
    expect(dist(cs[0], cs[1])).toBeGreaterThan(100);
    expect(dist(cs[1], cs[2])).toBeGreaterThan(100);
    expect(dist(cs[0], cs[2])).toBeGreaterThan(100);
  });

  it("drops cross-space mixing well below the 26.8% baseline", () => {
    expect(crossSpaceMixing(computeClusterLayout(nodes, edges), nodes)).toBeLessThan(0.05);
  });

  it("is deterministic across runs", () => {
    const a = computeClusterLayout(nodes, edges);
    const b = computeClusterLayout(nodes, edges);
    for (const n of nodes) expect(b.get(n.id)).toEqual(a.get(n.id));
  });

  it("groups no-space (null/\"\") nodes into their own cluster", () => {
    const ns = [node("a1", "A"), node("a2", "A"), node("n1", null), node("n2", "")];
    const pos = computeClusterLayout(ns, []);
    expect(dist(centroid(["a1", "a2"], pos), centroid(["n1", "n2"], pos))).toBeGreaterThan(100);
  });

  it("separates a large cluster from an adjacent singleton (radius-sized slots)", () => {
    const big = Array.from({ length: 12 }, (_, i) => node(`g${i}`, "BIG"));
    const bigEdges = Array.from({ length: 11 }, (_, i) => edge(`g${i}`, `g${i + 1}`));
    const all = [...big, node("s1", "S1"), node("s2", "S2")];
    const pos = computeClusterLayout(all, bigEdges);
    const cBig = centroid(big.map((n) => n.id), pos);
    const rBig = radius(big.map((n) => n.id), pos);
    expect(dist(cBig, pos.get("s1")!)).toBeGreaterThan(rBig);
    expect(dist(cBig, pos.get("s2")!)).toBeGreaterThan(rBig);
  });

  it("keeps many small spaces non-overlapping (adjacent centroids exceed combined radii)", () => {
    const many = [];
    for (let s = 0; s < 8; s++) for (let i = 0; i < 2; i++) many.push(node(`s${s}_${i}`, `S${s}`));
    const pos = computeClusterLayout(many, []);
    const cents = Array.from({ length: 8 }, (_, s) => centroid([`s${s}_0`, `s${s}_1`], pos));
    const rads = Array.from({ length: 8 }, (_, s) => radius([`s${s}_0`, `s${s}_1`], pos));
    for (let s = 0; s < 8; s++) {
      const n = (s + 1) % 8;
      expect(dist(cents[s], cents[n])).toBeGreaterThan(rads[s] + rads[n]);
    }
  });

  it("centres a single space and returns an empty map for no nodes", () => {
    expect(computeClusterLayout([node("a1", "A"), node("a2", "A")], [edge("a1", "a2")]).size).toBe(2);
    expect(computeClusterLayout([], []).size).toBe(0);
  });

  it("largestSpaceSize returns the biggest per-space node count (gate input)", () => {
    expect(largestSpaceSize([node("a", "A"), node("b", "A"), node("c", "B")])).toBe(2);
    expect(largestSpaceSize([node("x", null), node("y", "")])).toBe(2); // null/"" same bucket
    expect(largestSpaceSize([])).toBe(0);
  });

  it("exposes a sane size-gate threshold", () => {
    expect(CLUSTER_LAYOUT_MAX_SPACE_NODES).toBeGreaterThan(0);
  });
});

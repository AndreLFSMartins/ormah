import { describe, expect, it } from "vitest";
import type { MemoryNode } from "../types";
import { crossSpaceMixing } from "./clusterLayout";

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

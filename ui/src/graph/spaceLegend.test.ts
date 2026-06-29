import { describe, expect, it } from "vitest";
import { buildSpaceLegend } from "./spaceLegend";
import type { MemoryNode } from "../types";

function n(space: string | null): MemoryNode {
  return {
    id: `${space}-${Math.random()}`, type: "fact", tier: "core", source: "",
    space, title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}

describe("buildSpaceLegend", () => {
  it("includes every space from allSpaces, even archival-only ones (count 0)", () => {
    const legend = buildSpaceLegend([n("work")], ["work", "dead"]);
    expect(legend.find((e) => e.val === "dead")).toEqual({ name: "dead", val: "dead", count: 0 });
    expect(legend.find((e) => e.val === "work")?.count).toBe(1);
  });

  it("counts nodes per space from the loaded payload", () => {
    const legend = buildSpaceLegend([n("a"), n("a"), n("b")], ["a", "b"]);
    expect(legend.find((e) => e.val === "a")?.count).toBe(2);
    expect(legend.find((e) => e.val === "b")?.count).toBe(1);
  });

  it("maps null/empty-space nodes to a '(no space)' group with val ''", () => {
    const legend = buildSpaceLegend([n(null), n("")], []);
    expect(legend.find((e) => e.name === "(no space)")).toEqual({
      name: "(no space)", val: "", count: 2,
    });
  });

  it("F1: renders '(no space)' at count 0 when hasNoSpace is set (archival-only group)", () => {
    const legend = buildSpaceLegend([n("work")], ["work"], true);
    expect(legend.find((e) => e.name === "(no space)")).toEqual({
      name: "(no space)", val: "", count: 0,
    });
  });

  it("omits '(no space)' when no no-space nodes and hasNoSpace is false", () => {
    const legend = buildSpaceLegend([n("work")], ["work"], false);
    expect(legend.find((e) => e.name === "(no space)")).toBeUndefined();
  });
});

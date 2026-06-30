import { describe, expect, it } from "vitest";
import { buildDimmed, selectVisibleNodes } from "./dimming";
import { ALL_TIERS, ALL_NODE_TYPES, ALL_EDGE_TYPES } from "../types";
import type { Filters } from "../App";
import type { MemoryNode, ViewScope } from "../types";

function node(space: string | null): MemoryNode {
  return {
    id: `${space}-${Math.random()}`, type: "fact", tier: "archival", source: "",
    space, title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}
function filters(over: Partial<Filters> = {}): Filters {
  return {
    tiers: new Set(ALL_TIERS), types: new Set(ALL_NODE_TYPES),
    spaces: new Set<string>(["work"]), edgeTypes: new Set(ALL_EDGE_TYPES),
    clusterBySpace: true, ...over,
  };
}

describe("buildDimmed", () => {
  it("active scope: dims a node whose space is not in filters.spaces", () => {
    const scope: ViewScope = { kind: "active" };
    const d = buildDimmed(filters({ spaces: new Set(["work"]) }), [node("other")], scope);
    expect(d.space.has("other")).toBe(true);
  });
  it("active scope: does NOT dim no-space nodes when '' is in filters.spaces (F1 fix)", () => {
    const scope: ViewScope = { kind: "active" };
    const d = buildDimmed(filters({ spaces: new Set(["work", ""]) }), [node(null)], scope);
    expect(d.space.has("")).toBe(false);
  });
  it("space drill: never dims by space or tier, even with restrictive filters (C1/C2)", () => {
    const scope: ViewScope = { kind: "space", space: "dead" };
    const f = filters({ spaces: new Set(["work"]), tiers: new Set(["core", "working"]) });
    const d = buildDimmed(f, [node(null), node("dead")], scope);
    expect(d.space.size).toBe(0);
    expect(d.tier.size).toBe(0);
  });
  it("active scope: still dims tiers not in filters.tiers", () => {
    const scope: ViewScope = { kind: "active" };
    const d = buildDimmed(filters({ tiers: new Set(["core", "working"]) }), [node("work")], scope);
    expect(d.tier.has("archival")).toBe(true);
  });
  it("show-all scope: never dims by space or tier (parity with drill)", () => {
    const scope: ViewScope = { kind: "all" };
    const f = filters({ spaces: new Set(["work"]), tiers: new Set(["core", "working"]) });
    const d = buildDimmed(f, [node(null), node("dead")], scope);
    expect(d.space.size).toBe(0);
    expect(d.tier.size).toBe(0);
  });
});

describe("selectVisibleNodes", () => {
  it("active scope: excludes a node whose space is dimmed", () => {
    const scope: ViewScope = { kind: "active" };
    const f = filters({ spaces: new Set(["work"]) });
    const vis = selectVisibleNodes(f, [node("work"), node("other")], scope);
    expect(vis.map((n) => n.space)).toEqual(["work"]);
  });
  it("space drill: counts nodes the drill shows even when tier/space filters exclude them (badge==canvas)", () => {
    const scope: ViewScope = { kind: "space", space: "dead" };
    const f = filters({ spaces: new Set(["work"]), tiers: new Set(["core", "working"]) });
    // node() is archival + space "dead": both filtered out, yet the drill renders it.
    const vis = selectVisibleNodes(f, [node("dead")], scope);
    expect(vis).toHaveLength(1);
  });
  it("all scope: same parity — tier/space filters don't shrink the count", () => {
    const scope: ViewScope = { kind: "all" };
    const f = filters({ spaces: new Set(["work"]), tiers: new Set(["core"]) });
    const vis = selectVisibleNodes(f, [node("dead"), node(null)], scope);
    expect(vis).toHaveLength(2);
  });
  it("type dimming still excludes in any scope", () => {
    const scope: ViewScope = { kind: "all" };
    const f = filters({ types: new Set(ALL_NODE_TYPES.filter((t) => t !== "fact")) });
    // node() is type "fact", which is now filtered out.
    const vis = selectVisibleNodes(f, [node("x")], scope);
    expect(vis).toHaveLength(0);
  });
});

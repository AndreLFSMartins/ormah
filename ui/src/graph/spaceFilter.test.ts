import { describe, expect, it } from "vitest";
import { nextSpaceFilter } from "./spaceFilter";

describe("nextSpaceFilter", () => {
  it("first seed: selects every space plus the no-space bucket", () => {
    const next = nextSpaceFilter(new Set(), ["work", "home"], false, new Set());
    expect(next).toEqual(new Set(["work", "home", ""]));
  });
  it("after seeding: preserves a deselection of a known space across a drill round-trip", () => {
    const current = new Set(["work", ""]); // user deselected "home"
    const known = new Set(["work", "home", ""]);
    const next = nextSpaceFilter(current, ["work", "home"], true, known);
    expect(next).toEqual(new Set(["work", ""]));
    expect(next.has("home")).toBe(false);
  });
  it("after seeding: auto-checks a brand-new space not seen before (created mid-session via MCP)", () => {
    const current = new Set(["work", ""]);
    const known = new Set(["work", ""]);
    const next = nextSpaceFilter(current, ["work", "newproj"], true, known);
    expect(next.has("newproj")).toBe(true);
    expect(next).toEqual(new Set(["work", "", "newproj"]));
  });
  it("after seeding: keeps a deselected known space out while still adding a new one", () => {
    const current = new Set(["work", ""]); // "home" deselected earlier
    const known = new Set(["work", "home", ""]);
    const next = nextSpaceFilter(current, ["work", "home", "newproj"], true, known);
    expect(next.has("home")).toBe(false); // deselection survives
    expect(next.has("newproj")).toBe(true); // new space appears
    expect(next).toEqual(new Set(["work", "", "newproj"]));
  });
  it("first seed returns a new set (no mutation of the input)", () => {
    const current = new Set<string>();
    const next = nextSpaceFilter(current, ["work"], false, new Set());
    expect(next).not.toBe(current);
  });
  it("seeded reload returns a new set (no mutation of the input)", () => {
    const current = new Set(["work"]);
    const next = nextSpaceFilter(current, ["work", "newproj"], true, new Set(["work"]));
    expect(next).not.toBe(current);
  });
});

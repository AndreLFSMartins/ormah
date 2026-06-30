import { describe, expect, it } from "vitest";
import { nextSpaceFilter } from "./spaceFilter";

describe("nextSpaceFilter", () => {
  it("first seed: selects every space plus the no-space bucket", () => {
    const next = nextSpaceFilter(new Set(), ["work", "home"], false);
    expect(next).toEqual(new Set(["work", "home", ""]));
  });
  it("after seeding: preserves the current set so deselections survive a drill round-trip", () => {
    const current = new Set(["work", ""]); // user deselected "home"
    const next = nextSpaceFilter(current, ["work", "home"], true);
    expect(next).toEqual(new Set(["work", ""]));
    expect(next.has("home")).toBe(false);
  });
  it("first seed returns a new set (no mutation of the input)", () => {
    const current = new Set<string>();
    const next = nextSpaceFilter(current, ["work"], false);
    expect(next).not.toBe(current);
  });
});

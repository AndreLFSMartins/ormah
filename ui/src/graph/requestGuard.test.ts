import { describe, expect, it } from "vitest";
import { createRequestGuard } from "./requestGuard";

describe("createRequestGuard", () => {
  it("treats only the most recent token as current", () => {
    const g = createRequestGuard();
    const first = g.begin();
    const second = g.begin();
    expect(g.isLatest(second)).toBe(true);
    expect(g.isLatest(first)).toBe(false);
  });

  it("a fresh begin() invalidates an in-flight token", () => {
    const g = createRequestGuard();
    const a = g.begin();
    expect(g.isLatest(a)).toBe(true);
    const b = g.begin();
    expect(g.isLatest(a)).toBe(false);
    expect(g.isLatest(b)).toBe(true);
  });
});

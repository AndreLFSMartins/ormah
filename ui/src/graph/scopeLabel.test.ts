import { describe, expect, it } from "vitest";
import { scopeLabel } from "./scopeLabel";

describe("scopeLabel", () => {
  it("labels the active view with a show-all control and no back", () => {
    expect(scopeLabel({ kind: "active" })).toEqual({
      text: "Active graph · archival hidden", showBack: false, showAll: true,
    });
  });

  it("labels a drilled space with a back control and no show-all", () => {
    expect(scopeLabel({ kind: "space", space: "work" })).toEqual({
      text: "Space: work · archival shown", showBack: true, showAll: false,
    });
  });

  it("labels the no-space drill as '(no space)'", () => {
    expect(scopeLabel({ kind: "space", space: "" }).text).toBe(
      "Space: (no space) · archival shown",
    );
  });

  it("labels the show-all view with a back control and no show-all", () => {
    expect(scopeLabel({ kind: "all" })).toEqual({
      text: "All memories · incl. archival", showBack: true, showAll: false,
    });
  });
});

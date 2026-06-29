import { describe, expect, it } from "vitest";
import { scopeLabel } from "./scopeLabel";

describe("scopeLabel", () => {
  it("labels the active view with no back control", () => {
    expect(scopeLabel({ kind: "active" })).toEqual({
      text: "Active graph · archival oculto", showBack: false,
    });
  });

  it("labels a drilled space with a back control", () => {
    expect(scopeLabel({ kind: "space", space: "work" })).toEqual({
      text: "Espaço: work · com archival", showBack: true,
    });
  });

  it("labels the no-space drill as '(sem espaço)'", () => {
    expect(scopeLabel({ kind: "space", space: "" }).text).toBe(
      "Espaço: (sem espaço) · com archival",
    );
  });
});

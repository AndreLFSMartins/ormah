import type { ViewScope } from "../types";

export interface ScopeLabel {
  text: string;
  showBack: boolean; // space drill → active ("← back to active graph")
  showAll: boolean; // active → all ("Show all (incl. archival)")
  showActiveOnly: boolean; // all → active ("Active only")
}

export function scopeLabel(scope: ViewScope): ScopeLabel {
  if (scope.kind === "space") {
    const name = scope.space === "" ? "(no space)" : scope.space;
    return {
      text: `Space: ${name} · archival shown`,
      showBack: true, showAll: false, showActiveOnly: false,
    };
  }
  if (scope.kind === "all") {
    return {
      text: "All memories · incl. archival",
      showBack: false, showAll: false, showActiveOnly: true,
    };
  }
  return {
    text: "Active graph · archival hidden",
    showBack: false, showAll: true, showActiveOnly: false,
  };
}

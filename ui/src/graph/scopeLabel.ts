import type { ViewScope } from "../types";

export interface ScopeLabel {
  text: string;
  showBack: boolean;
  showAll: boolean;
}

export function scopeLabel(scope: ViewScope): ScopeLabel {
  if (scope.kind === "space") {
    const name = scope.space === "" ? "(no space)" : scope.space;
    return { text: `Space: ${name} · archival shown`, showBack: true, showAll: false };
  }
  if (scope.kind === "all") {
    return { text: "All memories · incl. archival", showBack: true, showAll: false };
  }
  return { text: "Active graph · archival hidden", showBack: false, showAll: true };
}

import type { ViewScope } from "../types";

export interface ScopeLabel {
  text: string;
  showBack: boolean;
}

export function scopeLabel(scope: ViewScope): ScopeLabel {
  if (scope.kind === "space") {
    const name = scope.space === "" ? "(sem espaço)" : scope.space;
    return { text: `Espaço: ${name} · com archival`, showBack: true };
  }
  return { text: "Active graph · archival oculto", showBack: false };
}

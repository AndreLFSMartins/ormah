import { ALL_EDGE_TYPES, ALL_NODE_TYPES, ALL_TIERS } from "../types";
import type { Filters } from "../App";
import type { MemoryNode, ViewScope } from "../types";

export interface DimmedSets {
  space: Set<string>;
  tier: Set<string>;
  role: Set<string>;
  type: Set<string>;
  edge: Set<string>;
}

export function buildDimmed(filters: Filters, nodes: MemoryNode[], viewScope: ViewScope): DimmedSets {
  // C1/C2: in a focused space drill — or "show all" — the payload IS exactly the
  // scope (the drilled space, or everything). Dimming by space/tier would hide the
  // very nodes that scope loaded, so skip both. Type/edge dimming still applies.
  const showsEverythingInScope = viewScope.kind === "space" || viewScope.kind === "all";

  const dimmedTier = showsEverythingInScope
    ? new Set<string>()
    : new Set<string>(ALL_TIERS.filter((t) => !filters.tiers.has(t)));

  const dimmedSpace = new Set<string>();
  if (!showsEverythingInScope && filters.spaces.size > 0) {
    for (const n of nodes) {
      const space = n.space || "";
      if (!filters.spaces.has(space)) dimmedSpace.add(space);
    }
  }

  const dimmedType = new Set<string>(ALL_NODE_TYPES.filter((t) => !filters.types.has(t)));
  const dimmedEdge = new Set<string>(ALL_EDGE_TYPES.filter((et) => !filters.edgeTypes.has(et)));

  return { space: dimmedSpace, tier: dimmedTier, role: new Set(), type: dimmedType, edge: dimmedEdge };
}

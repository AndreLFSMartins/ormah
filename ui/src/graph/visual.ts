import {
  type GraphAppearance,
  type GraphTheme,
} from "../graphAppearance";
import type { Edge, MemoryNode, Tier } from "../types";

export type SelfRole = "self" | "identity" | "";

export const GRAPH_THEME_TOKENS: Record<GraphTheme, {
  background: string; label: string; labelGlow: string; accent: string;
  edgeDefault: string; edgeSupports: string; edgeContradicts: string;
  edgeDefines: string; edgeEvolved: string; glowDefault: string;
}> = {
  dark: {
    background: "#0a0a0a", label: "#d8dee6", labelGlow: "#f3f4f6", accent: "#d4a574",
    edgeDefault: "#333", edgeSupports: "#4a7a4a", edgeContradicts: "#7a4a4a",
    edgeDefines: "#5a9e8f", edgeEvolved: "#6a5acd", glowDefault: "#d4a574",
  },
  light: {
    background: "#f6f8fb", label: "#24303c", labelGlow: "#111827", accent: "#8a5f2d",
    edgeDefault: "#aeb8c4", edgeSupports: "#3f7d52", edgeContradicts: "#a65353",
    edgeDefines: "#3e8f82", edgeEvolved: "#7265bd", glowDefault: "#8a5f2d",
  },
};

export function tierColor(tier: string, selfRole: SelfRole, appearance: GraphAppearance): string {
  if (selfRole === "self") return "#74b3a5";
  if (selfRole === "identity") return "#4d8a7e";
  return appearance.colors[tier as Tier] ?? appearance.colors.working;
}

// Note: tierBorderColor from the cytoscape view is intentionally NOT ported —
// the sigma default node program has no border, and dashed borders are deferred
// (spec: not a parity requirement). Re-add with a bordered node program if revived.

// Sizes are in LAYOUT-POSITION units (sigma is configured with
// itemSizesReference: "positions" + zoomToSizeRatioFunction: ratio => ratio),
// so a node's on-screen radius scales 1:1 with zoom, like Obsidian's graph.
// The settled FA2 layout for this store spans ~475 units across ~1800 nodes,
// giving a mean neighbour gap of ~11 units; node *diameters* stay below that
// gap to avoid the overlap that screen-space sizing produced (min Ø4, max Ø10).
function nodeSize(accessCount: number): number {
  return Math.min(5, Math.max(2, 2 + Math.log2(accessCount + 1) * 0.5));
}

export function displayNodeSize(accessCount: number, selfRole: SelfRole): number {
  const size = nodeSize(accessCount);
  return selfRole === "self" ? Math.max(3.5, size) : size;
}

export function edgeColor(edgeType: string, theme: GraphTheme): string {
  const t = GRAPH_THEME_TOKENS[theme];
  switch (edgeType) {
    case "supports": return t.edgeSupports;
    case "contradicts": return t.edgeContradicts;
    case "defines": return t.edgeDefines;
    case "evolved_from": return t.edgeEvolved;
    default: return t.edgeDefault;
  }
}

export function nodeLabel(n: MemoryNode): string {
  if (n.title) return n.title;
  if (n.content) return n.content.slice(0, 40);
  return n.id.split("-")[0];
}

export function computeSelfRoles(
  nodes: MemoryNode[],
  edges: Edge[],
  userNodeId: string | null,
): Map<string, SelfRole> {
  const roles = new Map<string, SelfRole>();
  for (const n of nodes) roles.set(n.id, "");
  if (!userNodeId) return roles;
  for (const e of edges) {
    if (e.edge_type === "defines" && e.source_id === userNodeId) {
      if (roles.has(e.target_id)) roles.set(e.target_id, "identity");
    }
  }
  if (roles.has(userNodeId)) roles.set(userNodeId, "self");
  return roles;
}

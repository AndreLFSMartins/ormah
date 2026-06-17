// Plain attribute shapes (sigma's NodeDisplayData/EdgeDisplayData supersets).
export interface NodeAttrs {
  color?: string;
  label?: string;
  size?: number;
  highlighted?: boolean;
  [key: string]: unknown;
}
export interface EdgeAttrs {
  color?: string;
  hidden?: boolean;
  [key: string]: unknown;
}

export interface NodeAttr { space: string; tier: string; selfRole: string }
export type FocusKind = { kind: "space" | "tier" | "role" | "edge"; val: string } | null;

export interface ViewState {
  hoveredNode: string | null;
  neighbors: Set<string>;
  highlightSet: Set<string>;                                   // Council H1: multi-highlight (focus+dim), separate from hover
  glowOnly: Set<string>;                                       // Council A4: search-hover — highlight WITHOUT dimming others
  focusKind: FocusKind;                                        // Council A1: legend focus — match stays vivid, rest dims
  dimmed: { space: Set<string>; tier: Set<string>; role: Set<string>; edge: Set<string> }; // Council C2: App.tsx filters (HIDE)
  attrsById: Map<string, NodeAttr>;
  edgeTypeById: Map<string, string>;
  dimColor: string;
}

// Council C2: App.tsx filters dim/hide a node.
function nodeIsFilterDimmed(node: string, state: ViewState): boolean {
  const a = state.attrsById.get(node);
  if (!a) return false;
  const { space, tier, role } = state.dimmed;
  return space.has(a.space) || tier.has(a.tier) || role.has(a.selfRole);
}

// Council A1: does this node match the active legend focus?
function nodeMatchesFocus(node: string, state: ViewState): boolean {
  if (!state.focusKind) return true;
  const a = state.attrsById.get(node);
  if (!a) return false;
  const { kind, val } = state.focusKind;
  if (kind === "space") return a.space === val;
  if (kind === "tier") return a.tier === val;
  if (kind === "role") return a.selfRole === val;
  return true; // edge focus is decided on edges; nodes only dim via edge endpoints (handled in GraphView's idsMatching)
}

export function makeNodeReducer(state: ViewState) {
  const { hoveredNode, neighbors, highlightSet, glowOnly, focusKind, dimColor } = state;
  const dim = (out: NodeAttrs) => { out.color = dimColor; out.label = undefined; return out; };
  return (node: string, data: NodeAttrs): NodeAttrs => {
    const out: NodeAttrs = { ...data };

    // 1) Filter-dim (App.tsx) wins — a filtered-out node always dims.
    if (nodeIsFilterDimmed(node, state)) return dim(out);

    // 2) glowOnly (search-hover, A4): the member glows; NOBODY else is dimmed.
    if (glowOnly.size > 0) {
      if (glowOnly.has(node)) out.highlighted = true;
      return out;
    }

    // 3) Legend focus (A1): matching nodes vivid, the rest dim.
    if (focusKind) {
      if (nodeMatchesFocus(node, state)) { out.highlighted = true; return out; }
      return dim(out);
    }

    // 4) Programmatic multi-highlight (Insights/Review): members vivid, rest dim.
    if (highlightSet.size > 0) {
      if (highlightSet.has(node)) { out.highlighted = true; return out; }
      return dim(out);
    }

    // 5) Hover: node + neighbors vivid, rest dim.
    if (hoveredNode) {
      if (node === hoveredNode) out.highlighted = true;
      else if (!neighbors.has(node)) return dim(out);
    }
    return out;
  };
}

export function makeEdgeReducer(state: ViewState, sourceTarget: (edge: string) => [string, string]) {
  const { hoveredNode, neighbors, highlightSet, glowOnly, dimmed, edgeTypeById, dimColor } = state;
  return (edge: string, data: EdgeAttrs): EdgeAttrs => {
    const out: EdgeAttrs = { ...data };

    // Filter-dim by edge type (App.tsx).
    if (dimmed.edge.size > 0 && dimmed.edge.has(edgeTypeById.get(edge) ?? "")) {
      out.color = dimColor;
      return out;
    }
    if (glowOnly.size > 0) return out;           // glowOnly never dims edges

    const [s, t] = sourceTarget(edge);
    if (highlightSet.size > 0) {
      if (!(highlightSet.has(s) && highlightSet.has(t))) out.color = dimColor;
      return out;
    }
    if (hoveredNode) {
      const touches = s === hoveredNode || t === hoveredNode ||
        (neighbors.has(s) && neighbors.has(t));
      if (!touches) out.color = dimColor;
    }
    return out;
  };
}

import type { GraphState, GraphNode, GraphEdge, Tier, SelfRole, EdgeType } from "./types";

export function createGraphState(width: number, height: number): GraphState {
  return {
    nodes: new Map(),
    edges: new Map(),
    width,
    height,
    interactive: false,
    hoveredNodeId: null,
    draggedNodeId: null,
    time: 0,
    gravityCenterX: null,
  };
}

export interface NodeDef {
  id: string;
  label: string;
  tier: Tier;
  selfRole: SelfRole;
  accessCount: number;
}

export interface EdgeDef {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  weight: number;
}

export function addNode(state: GraphState, def: NodeDef): void {
  if (state.nodes.has(def.id)) return;
  const cx = state.width / 2;
  const cy = state.height / 2;
  const node: GraphNode = {
    ...def,
    x: cx + (Math.random() - 0.5) * 100,
    y: cy + (Math.random() - 0.5) * 100,
    vx: 0,
    vy: 0,
    opacity: 0,
    targetOpacity: 1,
    radius: 0,
    pinned: false,
    phase: Math.random() * Math.PI * 2,
  };
  // Self node starts at center
  if (def.selfRole === "self") {
    node.x = cx;
    node.y = cy;
  }
  state.nodes.set(def.id, node);
}

export function addEdge(state: GraphState, def: EdgeDef): void {
  if (state.edges.has(def.id)) return;
  const edge: GraphEdge = {
    ...def,
    opacity: 0,
    targetOpacity: Math.max(0.2, def.weight),
  };
  state.edges.set(def.id, edge);
}

export function setNodeOpacity(
  state: GraphState,
  nodeId: string,
  targetOpacity: number,
): void {
  const node = state.nodes.get(nodeId);
  if (node) node.targetOpacity = targetOpacity;
}

/** Reconcile: add nodes/edges that should exist, fade out those that shouldn't */
export function reconcile(
  state: GraphState,
  targetNodes: NodeDef[],
  targetEdges: EdgeDef[],
): void {
  const targetNodeIds = new Set(targetNodes.map((n) => n.id));
  const targetEdgeIds = new Set(targetEdges.map((e) => e.id));

  // Add new nodes (and sync mutable fields like label)
  for (const def of targetNodes) {
    addNode(state, def);
    const node = state.nodes.get(def.id)!;
    node.targetOpacity = 1;
    node.label = def.label;
  }

  // Add new edges
  for (const def of targetEdges) {
    if (state.nodes.has(def.source) && state.nodes.has(def.target)) {
      addEdge(state, def);
      const edge = state.edges.get(def.id)!;
      edge.targetOpacity = Math.max(0.2, def.weight);
    }
  }

  // Fade out nodes no longer in target
  for (const [id, node] of state.nodes) {
    if (!targetNodeIds.has(id)) {
      node.targetOpacity = 0;
    }
  }

  // Fade out edges no longer in target
  for (const [id, edge] of state.edges) {
    if (!targetEdgeIds.has(id)) {
      edge.targetOpacity = 0;
    }
  }

  // Remove fully faded nodes/edges
  for (const [id, node] of state.nodes) {
    if (node.opacity < 0.01 && node.targetOpacity === 0) {
      state.nodes.delete(id);
    }
  }
  for (const [id, edge] of state.edges) {
    if (edge.opacity < 0.01 && edge.targetOpacity === 0) {
      state.edges.delete(id);
    }
  }
}

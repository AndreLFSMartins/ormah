export type Tier = "core" | "working" | "archival";
export type SelfRole = "self" | "identity" | "";

export type EdgeType =
  | "defines"
  | "related_to"
  | "supports"
  | "contradicts"
  | "evolved_from"
  | "part_of";

export interface GraphNode {
  id: string;
  label: string;
  tier: Tier;
  selfRole: SelfRole;
  accessCount: number;
  // Position
  x: number;
  y: number;
  // Velocity
  vx: number;
  vy: number;
  // Visual state
  opacity: number;
  targetOpacity: number;
  radius: number;
  pinned: boolean;
  // Animation phase offset
  phase: number;
  // Birth timestamp for growth animation (ms, from performance.now)
  birthTime?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  weight: number;
  opacity: number;
  targetOpacity: number;
}

export interface GraphState {
  nodes: Map<string, GraphNode>;
  edges: Map<string, GraphEdge>;
  width: number;
  height: number;
  interactive: boolean;
  hoveredNodeId: string | null;
  draggedNodeId: string | null;
  time: number;
  gravityCenterX: number | null; // override horizontal gravity center (null = canvas center)
}

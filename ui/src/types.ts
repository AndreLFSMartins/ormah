export type NodeType =
  | "fact"
  | "decision"
  | "preference"
  | "event"
  | "person"
  | "project"
  | "concept"
  | "procedure"
  | "goal"
  | "observation";

// Canonical runtime list of every NodeType. Keep in sync with the union above
// (a missing value silently breaks type-based filtering/dimming). Single source
// of truth for App.tsx filters and GraphView's buildDimmed.
export const ALL_NODE_TYPES: NodeType[] = [
  "fact", "decision", "preference", "event", "person",
  "project", "concept", "procedure", "goal", "observation",
];

export type Tier = "core" | "working" | "archival";

export const ALL_TIERS: Tier[] = ["core", "working", "archival"];

export type EdgeType =
  | "related_to"
  | "supports"
  | "contradicts"
  | "part_of"
  | "derived_from"
  | "depends_on"
  | "defines"
  | "evolved_from";

export const ALL_EDGE_TYPES: EdgeType[] = [
  "related_to", "supports", "contradicts", "part_of",
  "derived_from", "depends_on", "defines", "evolved_from",
];

export interface MemoryNode {
  id: string;
  type: NodeType;
  tier: Tier;
  source: string;
  space: string | null;
  title: string | null;
  content: string;
  created: string;
  updated: string;
  last_accessed: string;
  access_count: number;
  file_path: string;
  file_hash: string;
}

export interface Edge {
  source_id: string;
  target_id: string;
  edge_type: EdgeType;
  weight: number;
  created: string;
}

export interface GraphData {
  nodes: MemoryNode[];
  edges: Edge[];
  user_node_id: string | null;
  all_spaces?: string[];
  has_no_space?: boolean; // F1: a no-space group exists over ALL nodes (incl. archival)
}

export type ViewScope = { kind: "active" } | { kind: "space"; space: string };

export interface NodeDetail {
  node: MemoryNode;
  edges: Edge[];
  neighbors: MemoryNode[];
  tags: string[];
}

export type ProposalType = "merge" | "conflict" | "decay";
export type ProposalStatus = "pending" | "approved" | "rejected";

export interface ProposalNode {
  id: string;
  title: string | null;
  content: string;
  type: NodeType;
  tier: Tier;
  space: string | null;
  created: string;
}

export interface Proposal {
  id: string;
  type: ProposalType;
  status: ProposalStatus;
  source_nodes: string;
  proposed_action: string;
  action_summary: string;
  merged_preview: string | null;
  nodes: ProposalNode[];
  reason: string | null;
  created: string;
  resolved: string | null;
}

export interface InsightNode {
  id: string;
  title: string | null;
  type: NodeType;
  tier: Tier;
  content: string;
  created: string;
}

export interface Evolution {
  newer: InsightNode;
  older: InsightNode;
  explanation: string;
}

export interface Tension {
  node_a: InsightNode;
  node_b: InsightNode;
  explanation: string;
}

export interface InsightsData {
  evolutions: Evolution[];
  tensions: Tension[];
}

export interface SearchResult {
  node: MemoryNode;
  score: number;
  source: string;
  formatted: string;
}

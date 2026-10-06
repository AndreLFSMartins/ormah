import type { NodeDef, EdgeDef } from "./graph";
import { ACTS_VH, vhToPx } from "@/lib/constants";

// -- Node definitions --

const SELF: NodeDef = {
  id: "self",
  label: "",
  tier: "core",
  selfRole: "self",
  accessCount: 20,
};

const IDENTITY_NODES: NodeDef[] = [
  { id: "name", label: "Name", tier: "core", selfRole: "identity", accessCount: 12 },
  { id: "role", label: "Role", tier: "core", selfRole: "identity", accessCount: 10 },
  { id: "preferences", label: "Preferences", tier: "core", selfRole: "identity", accessCount: 8 },
];

const CONCEPT_NODES: NodeDef[] = [
  { id: "arch", label: "Architecture", tier: "working", selfRole: "", accessCount: 6 },
  { id: "testing", label: "Testing", tier: "working", selfRole: "", accessCount: 4 },
  { id: "patterns", label: "Patterns", tier: "working", selfRole: "", accessCount: 5 },
  { id: "debugging", label: "Debugging", tier: "working", selfRole: "", accessCount: 3 },
];

const PROJECT_NODES: NodeDef[] = [
  { id: "project-a", label: "Project Alpha", tier: "working", selfRole: "", accessCount: 7 },
  { id: "api-design", label: "API Design", tier: "working", selfRole: "", accessCount: 5 },
];

const CONTRADICTION_NODES: NodeDef[] = [
  { id: "old-approach", label: "Old Approach", tier: "working", selfRole: "", accessCount: 4 },
  { id: "new-approach", label: "New Approach", tier: "working", selfRole: "", accessCount: 6 },
];

const EXPANDED_NODES: NodeDef[] = [
  { id: "meeting-notes", label: "Meeting Notes", tier: "working", selfRole: "", accessCount: 3 },
  { id: "research", label: "Research", tier: "working", selfRole: "", accessCount: 4 },
  { id: "decision-1", label: "Decision", tier: "core", selfRole: "", accessCount: 5 },
  { id: "context-1", label: "Context", tier: "working", selfRole: "", accessCount: 2 },
  { id: "tool-pref", label: "Tool Prefs", tier: "working", selfRole: "", accessCount: 3 },
  { id: "workflow", label: "Workflow", tier: "working", selfRole: "", accessCount: 4 },
  { id: "old-notes", label: "Old Notes", tier: "archival", selfRole: "", accessCount: 1 },
  { id: "archive-1", label: "Archive", tier: "archival", selfRole: "", accessCount: 0 },
  { id: "archive-2", label: "Legacy", tier: "archival", selfRole: "", accessCount: 1 },
  { id: "insight", label: "Insight", tier: "working", selfRole: "", accessCount: 5 },
  { id: "learning", label: "Learning", tier: "working", selfRole: "", accessCount: 3 },
  { id: "habit", label: "Habit", tier: "core", selfRole: "", accessCount: 6 },
  { id: "goal", label: "Goal", tier: "core", selfRole: "", accessCount: 7 },
];

// -- Edge definitions --

const IDENTITY_EDGES: EdgeDef[] = [
  { id: "e-self-name", source: "self", target: "name", type: "defines", weight: 0.9 },
  { id: "e-self-role", source: "self", target: "role", type: "defines", weight: 0.8 },
  { id: "e-self-pref", source: "self", target: "preferences", type: "defines", weight: 0.7 },
];

const CONCEPT_EDGES: EdgeDef[] = [
  { id: "e-role-arch", source: "role", target: "arch", type: "related_to", weight: 0.6 },
  { id: "e-arch-test", source: "arch", target: "testing", type: "related_to", weight: 0.5 },
  { id: "e-arch-pat", source: "arch", target: "patterns", type: "related_to", weight: 0.5 },
  { id: "e-test-debug", source: "testing", target: "debugging", type: "related_to", weight: 0.4 },
];

const PROJECT_EDGES: EdgeDef[] = [
  { id: "e-role-proj", source: "role", target: "project-a", type: "supports", weight: 0.7 },
  { id: "e-proj-api", source: "project-a", target: "api-design", type: "part_of", weight: 0.6 },
  { id: "e-arch-api", source: "arch", target: "api-design", type: "related_to", weight: 0.5 },
];

const CONTRADICTION_EDGES: EdgeDef[] = [
  { id: "e-old-new", source: "old-approach", target: "new-approach", type: "contradicts", weight: 0.6 },
  { id: "e-pat-old", source: "patterns", target: "old-approach", type: "related_to", weight: 0.4 },
  { id: "e-pat-new", source: "patterns", target: "new-approach", type: "evolved_from", weight: 0.5 },
];

const EXPANDED_EDGES: EdgeDef[] = [
  { id: "e-proj-meet", source: "project-a", target: "meeting-notes", type: "related_to", weight: 0.4 },
  { id: "e-proj-res", source: "project-a", target: "research", type: "supports", weight: 0.5 },
  { id: "e-res-dec", source: "research", target: "decision-1", type: "supports", weight: 0.6 },
  { id: "e-meet-ctx", source: "meeting-notes", target: "context-1", type: "related_to", weight: 0.3 },
  { id: "e-pref-tool", source: "preferences", target: "tool-pref", type: "defines", weight: 0.5 },
  { id: "e-pref-wf", source: "preferences", target: "workflow", type: "defines", weight: 0.4 },
  { id: "e-old-archive", source: "old-notes", target: "archive-1", type: "related_to", weight: 0.2 },
  { id: "e-archive-leg", source: "archive-1", target: "archive-2", type: "related_to", weight: 0.2 },
  { id: "e-debug-old", source: "debugging", target: "old-notes", type: "related_to", weight: 0.3 },
  { id: "e-dec-ins", source: "decision-1", target: "insight", type: "supports", weight: 0.5 },
  { id: "e-ins-learn", source: "insight", target: "learning", type: "related_to", weight: 0.4 },
  { id: "e-learn-hab", source: "learning", target: "habit", type: "evolved_from", weight: 0.5 },
  { id: "e-self-goal", source: "self", target: "goal", type: "defines", weight: 0.8 },
  { id: "e-goal-proj", source: "goal", target: "project-a", type: "supports", weight: 0.6 },
  { id: "e-hab-wf", source: "habit", target: "workflow", type: "related_to", weight: 0.4 },
];

// Mobile-reduced set: fewer expanded nodes
const MOBILE_EXPANDED_NODES: NodeDef[] = EXPANDED_NODES.slice(0, 7);
const MOBILE_EXPANDED_EDGES: EdgeDef[] = EXPANDED_EDGES.slice(0, 8);

// -- Scenario builder --

export interface ScenarioFrame {
  nodes: NodeDef[];
  edges: EdgeDef[];
}

/** Compute which nodes/edges should exist at a given scrollY (in px) */
export function getScenarioFrame(
  scrollY: number,
  isMobile: boolean,
): ScenarioFrame {
  const nodes: NodeDef[] = [];
  const edges: EdgeDef[] = [];

  const act2Start = vhToPx(ACTS_VH.act2.startVh);
  const act2End = vhToPx(ACTS_VH.act2.endVh);
  const act3Start = vhToPx(ACTS_VH.act3.startVh);
  const act3End = vhToPx(ACTS_VH.act3.endVh);
  const act4Start = vhToPx(ACTS_VH.act4.startVh);
  const act4End = vhToPx(ACTS_VH.act4.endVh);

  // SELF node with dynamic label: empty in Act 1, "Self" from Act 2 onward
  const selfLabeled: NodeDef = scrollY >= act2Start
    ? { ...SELF, label: "Self" }
    : SELF;

  // Act 1 (0 - 100vh): ambient SELF node present from the start
  if (scrollY < act2Start) {
    nodes.push(selfLabeled);
    return { nodes, edges };
  }

  // Act 2: self node always present (was already visible in Act 1)
  const act2Progress = localProgressPx(scrollY, act2Start, act2End);
  nodes.push(selfLabeled);
  void act2Progress;
  if (scrollY < act3Start) {
    return { nodes, edges };
  }

  // Act 3: progressive graph growth
  const act3Progress = localProgressPx(scrollY, act3Start, act3End);

  // 0.0 - 0.15: identity nodes
  if (act3Progress >= 0) {
    nodes.push(selfLabeled);
    const count = Math.min(
      IDENTITY_NODES.length,
      Math.ceil(((act3Progress - 0) / 0.15) * IDENTITY_NODES.length),
    );
    for (let i = 0; i < count; i++) {
      nodes.push(IDENTITY_NODES[i]);
      if (IDENTITY_EDGES[i]) edges.push(IDENTITY_EDGES[i]);
    }
  }

  // 0.15 - 0.3: concept cluster
  if (act3Progress >= 0.15) {
    nodes.push(...IDENTITY_NODES);
    edges.push(...IDENTITY_EDGES);
    const t = (act3Progress - 0.15) / 0.15;
    const count = Math.min(
      CONCEPT_NODES.length,
      Math.ceil(t * CONCEPT_NODES.length),
    );
    for (let i = 0; i < count; i++) {
      nodes.push(CONCEPT_NODES[i]);
      if (CONCEPT_EDGES[i]) edges.push(CONCEPT_EDGES[i]);
    }
  }

  // 0.3 - 0.5: project nodes
  if (act3Progress >= 0.3) {
    nodes.push(...CONCEPT_NODES);
    edges.push(...CONCEPT_EDGES);
    const t = (act3Progress - 0.3) / 0.2;
    const count = Math.min(
      PROJECT_NODES.length,
      Math.ceil(t * PROJECT_NODES.length),
    );
    for (let i = 0; i < count; i++) {
      nodes.push(PROJECT_NODES[i]);
      if (PROJECT_EDGES[i]) edges.push(PROJECT_EDGES[i]);
    }
  }

  // 0.5 - 0.7: contradiction + expanded
  if (act3Progress >= 0.5) {
    nodes.push(...PROJECT_NODES);
    edges.push(...PROJECT_EDGES);
    nodes.push(...CONTRADICTION_NODES);
    edges.push(...CONTRADICTION_EDGES);

    const expNodes = isMobile ? MOBILE_EXPANDED_NODES : EXPANDED_NODES;
    const expEdges = isMobile ? MOBILE_EXPANDED_EDGES : EXPANDED_EDGES;

    if (act3Progress >= 0.7) {
      nodes.push(...expNodes);
      edges.push(...expEdges);
    } else {
      const t = (act3Progress - 0.5) / 0.2;
      const count = Math.min(
        expNodes.length,
        Math.ceil(t * expNodes.length),
      );
      for (let i = 0; i < count; i++) {
        nodes.push(expNodes[i]);
        if (expEdges[i]) edges.push(expEdges[i]);
      }
    }
  }

  if (scrollY < act4Start) return { nodes, edges };

  // Act 4+: all nodes present
  nodes.push(
    selfLabeled,
    ...IDENTITY_NODES,
    ...CONCEPT_NODES,
    ...PROJECT_NODES,
    ...CONTRADICTION_NODES,
    ...(isMobile ? MOBILE_EXPANDED_NODES : EXPANDED_NODES),
  );
  edges.push(
    ...IDENTITY_EDGES,
    ...CONCEPT_EDGES,
    ...PROJECT_EDGES,
    ...CONTRADICTION_EDGES,
    ...(isMobile ? MOBILE_EXPANDED_EDGES : EXPANDED_EDGES),
  );

  return { nodes: dedup(nodes), edges: dedupEdges(edges) };
}

/** Get decay/recall overrides for Act 4 (scrollY in px) */
export function getAct4Overrides(
  scrollY: number,
): Map<string, number> {
  const overrides = new Map<string, number>();
  const act4Start = vhToPx(ACTS_VH.act4.startVh);
  const act4End = vhToPx(ACTS_VH.act4.endVh);
  const act4Progress = localProgressPx(scrollY, act4Start, act4End);
  if (act4Progress < 0) return overrides;

  // Decay: old-notes dims
  if (act4Progress < 0.3) {
    const t = act4Progress / 0.3;
    overrides.set("old-notes", 1 - t * 0.7); // 1 → 0.3
    overrides.set("archive-1", 1 - t * 0.7);
  } else {
    overrides.set("old-notes", 0.3);
    overrides.set("archive-1", 0.3);
  }

  // Recall: insight brightens
  if (act4Progress >= 0.3 && act4Progress < 0.6) {
    const t = (act4Progress - 0.3) / 0.3;
    overrides.set("insight", 0.7 + t * 0.3);
    overrides.set("decision-1", 0.7 + t * 0.3);
  }

  return overrides;
}

function localProgressPx(scrollY: number, startPx: number, endPx: number): number {
  if (scrollY < startPx) return -1;
  if (scrollY >= endPx) return 1;
  return (scrollY - startPx) / (endPx - startPx);
}

function dedup(nodes: NodeDef[]): NodeDef[] {
  const seen = new Set<string>();
  return nodes.filter((n) => {
    if (seen.has(n.id)) return false;
    seen.add(n.id);
    return true;
  });
}

function dedupEdges(edges: EdgeDef[]): EdgeDef[] {
  const seen = new Set<string>();
  return edges.filter((e) => {
    if (seen.has(e.id)) return false;
    seen.add(e.id);
    return true;
  });
}

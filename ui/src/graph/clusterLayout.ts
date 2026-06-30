import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import type { Edge, MemoryNode } from "../types";

/**
 * Fraction of nodes whose nearest neighbour (by Euclidean position) belongs to a
 * different space. Test-only diagnostic for cluster cohesion — NOT called in render.
 * ponytail: O(n^2) brute force; only ever runs over test fixtures, so no kd-tree.
 */
export function crossSpaceMixing(
  positions: Map<string, { x: number; y: number }>,
  nodes: MemoryNode[],
): number {
  const pts = nodes
    .map((n) => ({ space: n.space ?? "", p: positions.get(n.id) }))
    .filter((x): x is { space: string; p: { x: number; y: number } } => x.p !== undefined);
  if (pts.length < 2) return 0;
  let cross = 0;
  for (let i = 0; i < pts.length; i++) {
    let best = Infinity;
    let bestSpace = pts[i].space;
    for (let j = 0; j < pts.length; j++) {
      if (i === j) continue;
      const dx = pts[i].p.x - pts[j].p.x;
      const dy = pts[i].p.y - pts[j].p.y;
      const d = dx * dx + dy * dy;
      if (d < best) {
        best = d;
        bestSpace = pts[j].space;
      }
    }
    if (bestSpace !== pts[i].space) cross += 1;
  }
  return cross / pts.length;
}

/**
 * Max nodes in a SINGLE space for the synchronous cluster path. FA2 cost is
 * per-space, so the gate keys on the largest space, not the total. Above this,
 * GraphView keeps the async global FA2 worker (council R1+R2).
 * ponytail: a flat per-space cap, not a measured frame budget — lower it if a
 * real vault with one big space still janks.
 */
export const CLUSTER_LAYOUT_MAX_SPACE_NODES = 1500;

/** Largest per-space node count (null/"" share the no-space bucket). Gate input. */
export function largestSpaceSize(nodes: MemoryNode[]): number {
  const counts = new Map<string, number>();
  let max = 0;
  for (const n of nodes) {
    const c = (counts.get(n.space ?? "") ?? 0) + 1;
    counts.set(n.space ?? "", c);
    if (c > max) max = c;
  }
  return max;
}

export interface ClusterLayoutOptions {
  /** FA2 iterations per space (default 100). */
  iterations?: number;
}

/**
 * Macro/micro layout: each space laid out independently with synchronous FA2
 * (micro, Barnes-Hut for parity with the global worker), then placed on a macro
 * ring whose angular slot per space is sized by that cluster's radius — so
 * large/uneven clusters never overlap. Cross-space forces never act:
 * deterministic, cohesive.
 */
export function computeClusterLayout(
  nodes: MemoryNode[],
  edges: Edge[],
  opts: ClusterLayoutOptions = {},
): Map<string, { x: number; y: number }> {
  const iterations = opts.iterations ?? 100;
  const positions = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return positions;

  const bySpace = new Map<string, MemoryNode[]>();
  const spaceOf = new Map<string, string>();
  for (const n of nodes) {
    const key = n.space ?? "";
    const bucket = bySpace.get(key);
    if (bucket) bucket.push(n);
    else bySpace.set(key, [n]);
    spaceOf.set(n.id, key);
  }

  // One O(E) pass: bucket intra-space edges by space (council R2 — no per-space rescan).
  const edgesBySpace = new Map<string, Array<[string, string]>>();
  for (const e of edges) {
    const ss = spaceOf.get(e.source_id);
    if (ss !== undefined && ss === spaceOf.get(e.target_id)) {
      const b = edgesBySpace.get(ss);
      if (b) b.push([e.source_id, e.target_id]);
      else edgesBySpace.set(ss, [[e.source_id, e.target_id]]);
    }
  }

  const spaceKeys = [...bySpace.keys()].sort(); // deterministic order
  const MARGIN = 60;
  const clusters = spaceKeys.map((space) => {
    const members = bySpace.get(space)!;
    const sub = new Graph({ type: "directed" });
    members.forEach((m, mi) => {
      const a = (2 * Math.PI * mi) / members.length;
      const r = 10 + (mi % 7);
      sub.addNode(m.id, { x: r * Math.cos(a), y: r * Math.sin(a) });
    });
    for (const [s, t] of edgesBySpace.get(space) ?? []) {
      if (sub.hasNode(s) && sub.hasNode(t) && !sub.hasEdge(s, t)) sub.addEdge(s, t);
    }
    if (sub.order > 1) {
      // Barnes-Hut parity with the global worker (forceLayout.ts) so a big space
      // stays O(n log n) on the main thread, not O(n^2).
      const settings = { ...forceAtlas2.inferSettings(sub), barnesHutOptimize: sub.order > 1000 };
      forceAtlas2.assign(sub, { iterations, settings });
    }
    let lx = 0, ly = 0;
    sub.forEachNode((_id, a) => { lx += a.x as number; ly += a.y as number; });
    const cx = lx / sub.order, cy = ly / sub.order;
    const local: Array<{ id: string; x: number; y: number }> = [];
    let rad = 0;
    sub.forEachNode((id, a) => {
      const dx = (a.x as number) - cx, dy = (a.y as number) - cy;
      rad = Math.max(rad, Math.hypot(dx, dy));
      local.push({ id, x: dx, y: dy });
    });
    return { local, slot: rad + MARGIN };
  });

  const totalSlot = clusters.reduce((s, c) => s + c.slot, 0);
  const macroRadius = Math.max(200, totalSlot / Math.PI);
  let acc = 0;
  for (const c of clusters) {
    const frac = c.slot / totalSlot;
    const theta = 2 * Math.PI * (acc + frac / 2);
    acc += frac;
    const cx = macroRadius * Math.cos(theta);
    const cy = macroRadius * Math.sin(theta);
    for (const p of c.local) positions.set(p.id, { x: cx + p.x, y: cy + p.y });
  }
  return positions;
}

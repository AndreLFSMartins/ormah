import type { MemoryNode } from "../types";

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

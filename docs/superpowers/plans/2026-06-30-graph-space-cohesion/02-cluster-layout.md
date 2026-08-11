# Task 2: `computeClusterLayout` macro/micro layout

**Files:**
- Modify: `ui/src/graph/clusterLayout.ts` (add `computeClusterLayout`, `ClusterLayoutOptions`,
  `CLUSTER_LAYOUT_MAX_SPACE_NODES`, `largestSpaceSize`)
- Test: `ui/src/graph/clusterLayout.test.ts` (add a `computeClusterLayout` describe block)

Per-space synchronous FA2 (micro) translated onto a macro ring whose **angular slots are sized by
each cluster's radius** (no overlap). Two council R2 hardenings: (1) the micro FA2 enables
**Barnes-Hut** for parity with the global worker, so a big space stays O(n log n); (2) intra-space
edges are bucketed in **one O(E) pass**, not rescanned per space. The size gate (Task 4) keys on the
**largest single space**, since FA2 cost is per-space — `largestSpaceSize` is exported for it.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/graph/clusterLayout.test.ts` (reuse the `node` factory from Task 1):

```typescript
import {
  CLUSTER_LAYOUT_MAX_SPACE_NODES,
  computeClusterLayout,
  largestSpaceSize,
} from "./clusterLayout";
import type { Edge } from "../types";

function edge(s: string, t: string): Edge {
  return { source_id: s, target_id: t, edge_type: "related_to", weight: 1, created: "" };
}
function centroid(ids: string[], pos: Map<string, { x: number; y: number }>) {
  let x = 0, y = 0;
  for (const id of ids) { const p = pos.get(id)!; x += p.x; y += p.y; }
  return { x: x / ids.length, y: y / ids.length };
}
function radius(ids: string[], pos: Map<string, { x: number; y: number }>) {
  const c = centroid(ids, pos);
  return Math.max(...ids.map((id) => Math.hypot(pos.get(id)!.x - c.x, pos.get(id)!.y - c.y)));
}
function dist(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

describe("computeClusterLayout", () => {
  const nodes = [
    node("a1", "A"), node("a2", "A"), node("a3", "A"),
    node("b1", "B"), node("b2", "B"), node("b3", "B"),
    node("c1", "C"), node("c2", "C"), node("c3", "C"),
  ];
  const edges = [
    edge("a1", "a2"), edge("a2", "a3"),
    edge("b1", "b2"), edge("b2", "b3"),
    edge("c1", "c2"), edge("c2", "c3"),
    edge("a1", "b1"), // cross-space link must NOT smear clusters
  ];

  it("keeps same-space nodes cohesive and centroids well apart", () => {
    const pos = computeClusterLayout(nodes, edges);
    const cs = ["A", "B", "C"].map((sp) =>
      centroid(nodes.filter((n) => n.space === sp).map((n) => n.id), pos),
    );
    expect(dist(cs[0], cs[1])).toBeGreaterThan(100);
    expect(dist(cs[1], cs[2])).toBeGreaterThan(100);
    expect(dist(cs[0], cs[2])).toBeGreaterThan(100);
  });

  it("drops cross-space mixing well below the 26.8% baseline", () => {
    expect(crossSpaceMixing(computeClusterLayout(nodes, edges), nodes)).toBeLessThan(0.05);
  });

  it("is deterministic across runs", () => {
    const a = computeClusterLayout(nodes, edges);
    const b = computeClusterLayout(nodes, edges);
    for (const n of nodes) expect(b.get(n.id)).toEqual(a.get(n.id));
  });

  it("groups no-space (null/\"\") nodes into their own cluster", () => {
    const ns = [node("a1", "A"), node("a2", "A"), node("n1", null), node("n2", "")];
    const pos = computeClusterLayout(ns, []);
    expect(dist(centroid(["a1", "a2"], pos), centroid(["n1", "n2"], pos))).toBeGreaterThan(100);
  });

  it("separates a large cluster from an adjacent singleton (radius-sized slots)", () => {
    const big = Array.from({ length: 12 }, (_, i) => node(`g${i}`, "BIG"));
    const bigEdges = Array.from({ length: 11 }, (_, i) => edge(`g${i}`, `g${i + 1}`));
    const all = [...big, node("s1", "S1"), node("s2", "S2")];
    const pos = computeClusterLayout(all, bigEdges);
    const cBig = centroid(big.map((n) => n.id), pos);
    const rBig = radius(big.map((n) => n.id), pos);
    expect(dist(cBig, pos.get("s1")!)).toBeGreaterThan(rBig);
    expect(dist(cBig, pos.get("s2")!)).toBeGreaterThan(rBig);
  });

  it("keeps many small spaces non-overlapping (adjacent centroids exceed combined radii)", () => {
    const many = [];
    for (let s = 0; s < 8; s++) for (let i = 0; i < 2; i++) many.push(node(`s${s}_${i}`, `S${s}`));
    const pos = computeClusterLayout(many, []);
    const cents = Array.from({ length: 8 }, (_, s) => centroid([`s${s}_0`, `s${s}_1`], pos));
    const rads = Array.from({ length: 8 }, (_, s) => radius([`s${s}_0`, `s${s}_1`], pos));
    for (let s = 0; s < 8; s++) {
      const n = (s + 1) % 8;
      expect(dist(cents[s], cents[n])).toBeGreaterThan(rads[s] + rads[n]);
    }
  });

  it("centres a single space and returns an empty map for no nodes", () => {
    expect(computeClusterLayout([node("a1", "A"), node("a2", "A")], [edge("a1", "a2")]).size).toBe(2);
    expect(computeClusterLayout([], []).size).toBe(0);
  });

  it("largestSpaceSize returns the biggest per-space node count (gate input)", () => {
    expect(largestSpaceSize([node("a", "A"), node("b", "A"), node("c", "B")])).toBe(2);
    expect(largestSpaceSize([node("x", null), node("y", "")])).toBe(2); // null/"" same bucket
    expect(largestSpaceSize([])).toBe(0);
  });

  it("exposes a sane size-gate threshold", () => {
    expect(CLUSTER_LAYOUT_MAX_SPACE_NODES).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/clusterLayout.test.ts )`
Expected: FAIL — `computeClusterLayout` / `largestSpaceSize` / `CLUSTER_LAYOUT_MAX_SPACE_NODES` not exported.

- [ ] **Step 3: Write minimal implementation**

Add to `ui/src/graph/clusterLayout.ts`:

```typescript
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import type { Edge, MemoryNode } from "../types";

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/clusterLayout.test.ts )`
Expected: PASS (Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/clusterLayout.ts ui/src/graph/clusterLayout.test.ts
git commit -m "feat(ui): macro/micro per-space cluster layout, Barnes-Hut + radius slots (#22 slice B)"
```

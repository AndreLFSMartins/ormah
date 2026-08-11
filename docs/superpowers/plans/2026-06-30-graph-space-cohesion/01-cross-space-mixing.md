# Task 1: `crossSpaceMixing` metric helper

**Files:**
- Create: `ui/src/graph/clusterLayout.ts`
- Test: `ui/src/graph/clusterLayout.test.ts`

Pure, test-only metric: the fraction of nodes whose nearest neighbour (by position) belongs to a
different space. Task 2's tests assert this drops well below the 26.8% baseline, so it ships first.

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/clusterLayout.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import type { MemoryNode } from "../types";
import { crossSpaceMixing } from "./clusterLayout";

// Minimal MemoryNode factory — only id/space matter for layout/metric.
function node(id: string, space: string | null): MemoryNode {
  return {
    id, type: "concept", tier: "working", source: "", space,
    title: id, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}

describe("crossSpaceMixing", () => {
  it("is 0 when each node's nearest neighbour shares its space", () => {
    const nodes = [node("a1", "A"), node("a2", "A"), node("b1", "B"), node("b2", "B")];
    const pos = new Map([
      ["a1", { x: 0, y: 0 }], ["a2", { x: 1, y: 0 }],   // A cluster near origin
      ["b1", { x: 100, y: 0 }], ["b2", { x: 101, y: 0 }], // B cluster far away
    ]);
    expect(crossSpaceMixing(pos, nodes)).toBe(0);
  });

  it("is 1 when every node's nearest neighbour is a different space (interleaved)", () => {
    const nodes = [node("a1", "A"), node("b1", "B"), node("a2", "A"), node("b2", "B")];
    const pos = new Map([
      ["a1", { x: 0, y: 0 }], ["b1", { x: 1, y: 0 }],
      ["a2", { x: 2, y: 0 }], ["b2", { x: 3, y: 0 }],
    ]);
    expect(crossSpaceMixing(pos, nodes)).toBe(1);
  });

  it("returns 0 for fewer than two positioned nodes", () => {
    expect(crossSpaceMixing(new Map([["a1", { x: 0, y: 0 }]]), [node("a1", "A")])).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/clusterLayout.test.ts )`
Expected: FAIL — `crossSpaceMixing` is not exported / module not found.

- [ ] **Step 3: Write minimal implementation**

Create `ui/src/graph/clusterLayout.ts`:

```typescript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/clusterLayout.test.ts )`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/clusterLayout.ts ui/src/graph/clusterLayout.test.ts
git commit -m "feat(ui): add crossSpaceMixing cohesion metric (#22 slice B)"
```

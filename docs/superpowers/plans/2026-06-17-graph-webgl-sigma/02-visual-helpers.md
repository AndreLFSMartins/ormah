### Task 2: Extract pure visual helpers

Move the visual mapping out of `GraphView.tsx` into a pure, sigma-agnostic, fully-testable module. Values are ported verbatim from the current `GraphView.tsx` (lines cited). Adds `computeSelfRoles`, which replaces the inline `selfRole`/`identityNodeIds` logic (current lines 432–441, 510–514).

**Files:**
- Create: `ui/src/graph/visual.ts`
- Test: `ui/src/graph/visual.test.ts`

> `GRAPH_THEME_TOKENS` is currently defined inside `GraphView.tsx` (lines 33–69). Move the whole constant here unchanged.

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/visual.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  tierColor,
  edgeColor,
  displayNodeSize,
  nodeLabel,
  computeSelfRoles,
} from "./visual";
import { DEFAULT_GRAPH_APPEARANCE } from "../graphAppearance";
import type { Edge, MemoryNode } from "../types";

const A = DEFAULT_GRAPH_APPEARANCE;

function node(over: Partial<MemoryNode>): MemoryNode {
  return {
    id: "n", type: "fact", tier: "working", source: "x", space: null,
    title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "", ...over,
  };
}

describe("visual", () => {
  it("colors self and identity roles distinctly", () => {
    expect(tierColor("working", "self", A)).toBe("#74b3a5");
    expect(tierColor("working", "identity", A)).toBe("#4d8a7e");
    expect(tierColor("core", "", A)).toBe(A.colors.core);
  });

  it("maps edge types to theme colors", () => {
    expect(edgeColor("supports", "dark")).toBe("#4a7a4a");
    expect(edgeColor("related_to", "dark")).toBe("#333");
  });

  it("sizes self nodes at least the self floor", () => {
    expect(displayNodeSize(0, "self")).toBeGreaterThanOrEqual(Math.round(36 * 1.2));
  });

  it("labels prefer title, then content slice, then id prefix", () => {
    expect(nodeLabel(node({ title: "T" }))).toBe("T");
    expect(nodeLabel(node({ title: null, content: "abc" }))).toBe("abc");
    expect(nodeLabel(node({ id: "abc-123", title: null, content: "" }))).toBe("abc");
  });

  it("computes self/identity roles from defines edges", () => {
    const nodes = [node({ id: "u" }), node({ id: "p" }), node({ id: "q" })];
    const edges: Edge[] = [
      { source_id: "u", target_id: "p", edge_type: "defines", weight: 1, created: "" },
    ];
    const roles = computeSelfRoles(nodes, edges, "u");
    expect(roles.get("u")).toBe("self");
    expect(roles.get("p")).toBe("identity");
    expect(roles.get("q") ?? "").toBe("");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/visual.test.ts )`
Expected: FAIL — cannot find module `./visual`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/visual.ts`:

```typescript
import {
  GRAPH_DISPLAY_SCALE,
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

function nodeSize(accessCount: number): number {
  const baseSize = Math.min(56, Math.max(24, 24 + Math.log2(accessCount + 1) * 6));
  return Math.round(baseSize * GRAPH_DISPLAY_SCALE);
}

export function displayNodeSize(accessCount: number, selfRole: SelfRole): number {
  const size = nodeSize(accessCount);
  return selfRole === "self" ? Math.max(Math.round(36 * GRAPH_DISPLAY_SCALE), size) : size;
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/visual.test.ts )`
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/visual.ts ui/src/graph/visual.test.ts
git commit -m "refactor(ui): extract pure graph visual helpers + self-role map"
```

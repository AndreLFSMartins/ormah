# Task 3 — Pure helpers: `buildSpaceLegend` + `scopeLabel`

Funções puras com a lógica testável da legenda de espaços e do banner. Sem render de componente (vitest só inclui `src/**/*.test.ts`).

**Files:**
- Create: `ui/src/graph/spaceLegend.ts` + `ui/src/graph/spaceLegend.test.ts`
- Create: `ui/src/graph/scopeLabel.ts` + `ui/src/graph/scopeLabel.test.ts`

## 3a. `buildSpaceLegend`

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/spaceLegend.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { buildSpaceLegend } from "./spaceLegend";
import type { MemoryNode } from "../types";

function n(space: string | null): MemoryNode {
  return {
    id: `${space}-${Math.random()}`, type: "fact", tier: "core", source: "",
    space, title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}

describe("buildSpaceLegend", () => {
  it("includes every space from allSpaces, even archival-only ones (count 0)", () => {
    const legend = buildSpaceLegend([n("work")], ["work", "dead"]);
    expect(legend.find((e) => e.val === "dead")).toEqual({ name: "dead", val: "dead", count: 0 });
    expect(legend.find((e) => e.val === "work")?.count).toBe(1);
  });

  it("counts nodes per space from the loaded payload", () => {
    const legend = buildSpaceLegend([n("a"), n("a"), n("b")], ["a", "b"]);
    expect(legend.find((e) => e.val === "a")?.count).toBe(2);
    expect(legend.find((e) => e.val === "b")?.count).toBe(1);
  });

  it("maps null/empty-space nodes to a '(no space)' group with val ''", () => {
    const legend = buildSpaceLegend([n(null), n("")], []);
    expect(legend.find((e) => e.name === "(no space)")).toEqual({
      name: "(no space)", val: "", count: 2,
    });
  });

  it("F1: renders '(no space)' at count 0 when hasNoSpace is set (archival-only group)", () => {
    const legend = buildSpaceLegend([n("work")], ["work"], true);
    expect(legend.find((e) => e.name === "(no space)")).toEqual({
      name: "(no space)", val: "", count: 0,
    });
  });

  it("omits '(no space)' when no no-space nodes and hasNoSpace is false", () => {
    const legend = buildSpaceLegend([n("work")], ["work"], false);
    expect(legend.find((e) => e.name === "(no space)")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && npm run test -- spaceLegend.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `ui/src/graph/spaceLegend.ts`:

```typescript
import type { MemoryNode } from "../types";

export interface SpaceLegendEntry {
  name: string; // display name; "(no space)" for the null/empty group
  val: string; // value passed to drill/focus ("" for the no-space group)
  count: number; // nodes of this space in the loaded payload
}

export function buildSpaceLegend(
  nodes: MemoryNode[],
  allSpaces: string[],
  hasNoSpace = false, // F1: render "(no space)" even at count 0 when the group exists
): SpaceLegendEntry[] {
  const counts = new Map<string, number>();
  for (const s of allSpaces) counts.set(s, 0);
  let noSpace = 0;
  for (const node of nodes) {
    const key = node.space || "";
    if (key === "") {
      noSpace += 1;
      continue;
    }
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const entries: SpaceLegendEntry[] = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, count]) => ({ name, val: name, count }));
  if (noSpace > 0 || hasNoSpace) entries.push({ name: "(no space)", val: "", count: noSpace });
  return entries;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ui && npm run test -- spaceLegend.test.ts` → PASS (3 tests).

## 3b. `scopeLabel`

- [ ] **Step 5: Write the failing test**

Create `ui/src/graph/scopeLabel.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { scopeLabel } from "./scopeLabel";

describe("scopeLabel", () => {
  it("labels the active view with no back control", () => {
    expect(scopeLabel({ kind: "active" })).toEqual({
      text: "Active graph · archival oculto", showBack: false,
    });
  });

  it("labels a drilled space with a back control", () => {
    expect(scopeLabel({ kind: "space", space: "work" })).toEqual({
      text: "Espaço: work · com archival", showBack: true,
    });
  });

  it("labels the no-space drill as '(sem espaço)'", () => {
    expect(scopeLabel({ kind: "space", space: "" }).text).toBe(
      "Espaço: (sem espaço) · com archival",
    );
  });
});
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd ui && npm run test -- scopeLabel.test.ts` → FAIL (module missing).

- [ ] **Step 7: Implement**

Create `ui/src/graph/scopeLabel.ts`:

```typescript
import type { ViewScope } from "../types";

export interface ScopeLabel {
  text: string;
  showBack: boolean;
}

export function scopeLabel(scope: ViewScope): ScopeLabel {
  if (scope.kind === "space") {
    const name = scope.space === "" ? "(sem espaço)" : scope.space;
    return { text: `Espaço: ${name} · com archival`, showBack: true };
  }
  return { text: "Active graph · archival oculto", showBack: false };
}
```

## 3c. `createRequestGuard` (F2 — race de reload)

Guarda de sequência: `loadGraph` pega um token a cada chamada e só aplica a resposta se ainda for a última. Evita que um drill e um voltar resolvam fora de ordem e travem a UI no escopo errado.

- [ ] **Step 8: Write the failing test**

Create `ui/src/graph/requestGuard.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createRequestGuard } from "./requestGuard";

describe("createRequestGuard", () => {
  it("treats only the most recent token as current", () => {
    const g = createRequestGuard();
    const first = g.begin();
    const second = g.begin();
    expect(g.isLatest(second)).toBe(true);
    expect(g.isLatest(first)).toBe(false);
  });

  it("a fresh begin() invalidates an in-flight token", () => {
    const g = createRequestGuard();
    const a = g.begin();
    expect(g.isLatest(a)).toBe(true);
    const b = g.begin();
    expect(g.isLatest(a)).toBe(false);
    expect(g.isLatest(b)).toBe(true);
  });
});
```

- [ ] **Step 9: Run to verify it fails**

Run: `cd ui && npm run test -- requestGuard.test.ts` → FAIL (module missing).

- [ ] **Step 10: Implement**

Create `ui/src/graph/requestGuard.ts`:

```typescript
export interface RequestGuard {
  begin(): number;
  isLatest(token: number): boolean;
}

export function createRequestGuard(): RequestGuard {
  let latest = 0;
  return {
    begin() {
      latest += 1;
      return latest;
    },
    isLatest(token) {
      return token === latest;
    },
  };
}
```

- [ ] **Step 11: Run to verify it passes + commit all three helpers**

Run: `cd ui && npm run test -- spaceLegend.test.ts scopeLabel.test.ts requestGuard.test.ts` → PASS.

```bash
git add ui/src/graph/spaceLegend.ts ui/src/graph/spaceLegend.test.ts \
        ui/src/graph/scopeLabel.ts ui/src/graph/scopeLabel.test.ts \
        ui/src/graph/requestGuard.ts ui/src/graph/requestGuard.test.ts
git commit -m "feat(ui): buildSpaceLegend + scopeLabel + requestGuard pure helpers (#22)"
```

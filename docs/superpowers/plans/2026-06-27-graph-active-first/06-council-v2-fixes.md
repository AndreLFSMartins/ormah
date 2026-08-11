# Task 6 — Fixes do council v2 (C1/C2/C3) + cobertura

O council v2 verificou que o F1 não entrega visibilidade: nós sem-espaço e archival drillados ficam **dimmed** pelo `buildDimmed`/`sigmaReducers` existentes. Esta task extrai `buildDimmed` para um módulo puro **scope-aware** (testável) e endereça o tratamento de erro do `loadGraph`.

**Files:**
- Create: `ui/src/graph/dimming.ts` + `ui/src/graph/dimming.test.ts`
- Modify: `ui/src/components/GraphView.tsx` (remover `buildDimmed` local; importar do novo módulo; passar `nodes` + `viewScope` nas chamadas)
- Modify: `ui/src/App.tsx` (`loadGraph` ganha `.catch`; incluir `""` em `filters.spaces`)

## 6a. Extrair `buildDimmed` puro e scope-aware (C1 + C2 + cobertura CX3)

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/dimming.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { buildDimmed } from "./dimming";
import { ALL_TIERS, ALL_NODE_TYPES, DEFAULT_EDGE_TYPES } from "../types";
import type { Filters } from "../App";
import type { MemoryNode } from "../types";

function node(space: string | null): MemoryNode {
  return {
    id: `${space}-${Math.random()}`, type: "fact", tier: "archival", source: "",
    space, title: null, content: "", created: "", updated: "", last_accessed: "",
    access_count: 0, file_path: "", file_hash: "",
  };
}

function filters(over: Partial<Filters> = {}): Filters {
  return {
    tiers: new Set(ALL_TIERS), types: new Set(ALL_NODE_TYPES),
    spaces: new Set<string>(["work"]), edgeTypes: new Set(DEFAULT_EDGE_TYPES),
    clusterBySpace: true, ...over,
  };
}

describe("buildDimmed", () => {
  it("active scope: dims a node whose space is not in filters.spaces", () => {
    const d = buildDimmed(filters({ spaces: new Set(["work"]) }), [node("other")], { kind: "active" });
    expect(d.space.has("other")).toBe(true);
  });

  it("active scope: does NOT dim no-space nodes when '' is in filters.spaces (F1 fix)", () => {
    const d = buildDimmed(filters({ spaces: new Set(["work", ""]) }), [node(null)], { kind: "active" });
    expect(d.space.has("")).toBe(false);
  });

  it("space drill: never dims by space or tier, even with restrictive filters (C1/C2)", () => {
    const f = filters({ spaces: new Set(["work"]), tiers: new Set(["core", "working"]) }); // archival OFF
    const d = buildDimmed(f, [node(null), node("dead")], { kind: "space", space: "dead" });
    expect(d.space.size).toBe(0);
    expect(d.tier.size).toBe(0);
  });

  it("active scope: still dims tiers not in filters.tiers", () => {
    const d = buildDimmed(filters({ tiers: new Set(["core", "working"]) }), [node("work")], { kind: "active" });
    expect(d.tier.has("archival")).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && npm run test -- dimming.test.ts` → FAIL (module missing).

- [ ] **Step 3: Implement `ui/src/graph/dimming.ts`**

Move a lógica de `GraphView.tsx:769-800` para cá, sem dependência de graphology (deriva spaces dos `nodes`) e com consciência de `viewScope`:

```typescript
import { ALL_EDGE_TYPES, ALL_NODE_TYPES, ALL_TIERS } from "../types";
import type { Filters } from "../App";
import type { MemoryNode, ViewScope } from "../types";

export interface DimmedSets {
  space: Set<string>;
  tier: Set<string>;
  role: Set<string>;
  type: Set<string>;
  edge: Set<string>;
}

export function buildDimmed(
  filters: Filters,
  nodes: MemoryNode[],
  viewScope: ViewScope,
): DimmedSets {
  // C1/C2: in a focused space drill the payload IS exactly the scope (one space,
  // active + archival). Dimming by space/tier here would hide the very nodes the
  // drill loaded — so skip both. Type/edge dimming still applies.
  const inDrill = viewScope.kind === "space";

  const dimmedTier = inDrill
    ? new Set<string>()
    : new Set<string>(ALL_TIERS.filter((t) => !filters.tiers.has(t)));

  const dimmedSpace = new Set<string>();
  if (!inDrill && filters.spaces.size > 0) {
    for (const n of nodes) {
      const space = n.space || "";
      if (!filters.spaces.has(space)) dimmedSpace.add(space);
    }
  }

  const dimmedType = new Set<string>(ALL_NODE_TYPES.filter((t) => !filters.types.has(t)));
  const dimmedEdge = new Set<string>(ALL_EDGE_TYPES.filter((et) => !filters.edgeTypes.has(et)));

  return { space: dimmedSpace, tier: dimmedTier, role: new Set(), type: dimmedType, edge: dimmedEdge };
}
```

- [ ] **Step 4: Wire `GraphView.tsx` to the extracted helper**

- Remover a função local `buildDimmed` (linhas ~769-800).
- Importar: `import { buildDimmed } from "../graph/dimming";`
- Em **todas** as chamadas (mount effect + o effect que reage a `filters`), trocar `buildDimmed(filters, graph)` por `buildDimmed(filters, nodes, viewScope)`.
- Garantir que o effect que recomputa `dimmed` ao mudar `filters` também tenha `viewScope` nas deps (recomputar ao entrar/sair de drill).

- [ ] **Step 5: Run to verify it passes**

Run: `cd ui && npm run test -- dimming.test.ts` → PASS (4 tests).

## 6b. `loadGraph` no-space filter + tratamento de erro (C1 overview + C3)

- [ ] **Step 6: App — incluir `""` em `filters.spaces` e tratar erro no `loadGraph`**

No `loadGraph` (Task 4, Step 3), incluir `""` na reposição de `filters.spaces` (overview mostra no-space nodes) e adicionar `.catch` com toast (não atualizar `viewScope` em erro):

```typescript
  const loadGraph = useCallback((space?: string) => {
    const token = reqGuard.current.begin();
    fetchGraph(space === undefined ? undefined : { space })
      .then((data) => {
        if (!reqGuard.current.isLatest(token)) return; // F2: stale response — drop it
        setGraph(data);
        setUserNodeId(data.user_node_id);
        setHasNoSpace(data.has_no_space ?? false);
        setViewScope(space === undefined ? { kind: "active" } : { kind: "space", space });
        if (space === undefined) {
          const spaceList = data.all_spaces ?? [];
          setAllSpaces(spaceList);
          // C1: include "" so no-space nodes are not space-dimmed in the overview.
          setFilters((f) => ({ ...f, spaces: new Set([...spaceList, ""]) }));
        }
      })
      .catch(() => {
        if (!reqGuard.current.isLatest(token)) return;
        addToast("Falha ao carregar o grafo", "error"); // C3: surface, keep current view
      });
  }, [addToast]);
```

> `addToast` já existe em `App.tsx:74`. Mantém `viewScope`/`graph` anteriores em erro (sem estado inconsistente).

- [ ] **Step 7: Build + suite + commit**

Run: `cd ui && npm run test && npm run build` → tudo verde.

```bash
git add ui/src/graph/dimming.ts ui/src/graph/dimming.test.ts \
        ui/src/components/GraphView.tsx ui/src/App.tsx
git commit -m "fix(ui): scope-aware dimming + no-space visibility + loadGraph error toast (#22, council v2)"
```

## 6c. Correções de contagem no plano (C4)

- [ ] **Step 8: Ajustar os DoD de contagem** (apenas texto do plano, sem código):
  - Task 1 Step 4: "PASS (6 tests)" → **8 tests** (2 testes de `has_no_space` adicionados).
  - Task 3 Step 4: `spaceLegend.test.ts` → **5 tests** (2 de `hasNoSpace` adicionados).

## Verificação adicional (somar à Task 5)

- [ ] No smoke: com ≥1 espaço nomeado, nós **sem espaço** aparecem **não-dimmed** no overview; ao drillar um espaço (ou o "(no space)"), os nós archival aparecem **visíveis** mesmo com o tier `archival` desligado no FilterDrawer.

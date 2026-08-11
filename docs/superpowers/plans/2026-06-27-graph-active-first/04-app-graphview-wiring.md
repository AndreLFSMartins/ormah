# Task 4 — Wiring: `App.tsx` (estado + fetch) e `GraphView.tsx` (legenda drill + banner)

Wiring de UI. Sem teste unitário (o projeto não tem infra de teste de componente React); a lógica testável já está coberta nas Tasks 2-3. Verificação = typecheck/build verde (`npm run build`) + smoke manual (Task 5).

**Files:**
- Modify: `ui/src/App.tsx` (state, effect 93-105, render do GraphView 249-259)
- Modify: `ui/src/components/GraphView.tsx` (Props, imports, spaceLegend 261-268, space row 726-733, banner, styles)

## 4a. `App.tsx`

- [ ] **Step 1: Imports**

Adicione `ViewScope` ao import de tipos vindo de `"./types"` (junte ao import existente, ex.: `import type { ..., ViewScope } from "./types";`), e importe a guarda de sequência:

```typescript
import { createRequestGuard } from "./graph/requestGuard";
```

- [ ] **Step 2: Add `viewScope` + `hasNoSpace` state and the request guard**

Logo após `const [userNodeId, setUserNodeId] = useState<string | null>(null);` (linha 60):

```typescript
  const [viewScope, setViewScope] = useState<ViewScope>({ kind: "active" });
  const [hasNoSpace, setHasNoSpace] = useState(false);
  const reqGuard = useRef(createRequestGuard());
```

- [ ] **Step 3: Replace the mount effect (lines 93-105) with `loadGraph` + effect**

`loadGraph` usa a guarda (F2): pega um token por chamada e descarta respostas que não são mais a última — evita que drill/voltar sobrepostos travem a UI no escopo errado.

```typescript
  const loadGraph = useCallback((space?: string) => {
    const token = reqGuard.current.begin();
    fetchGraph(space === undefined ? undefined : { space }).then((data) => {
      if (!reqGuard.current.isLatest(token)) return; // F2: stale response — drop it
      setGraph(data);
      setUserNodeId(data.user_node_id);
      setHasNoSpace(data.has_no_space ?? false);
      setViewScope(space === undefined ? { kind: "active" } : { kind: "space", space });
      // allSpaces/filters reflect the FULL space list — only refresh them on the
      // active load (a drilled payload is scoped to one space).
      if (space === undefined) {
        const spaceList = data.all_spaces ?? [];
        setAllSpaces(spaceList);
        setFilters((f) => ({ ...f, spaces: new Set(spaceList) }));
      }
    });
  }, []);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);
```

- [ ] **Step 4: Pass new props to `<GraphView>` (render block 249-259)**

Acrescente, dentro do `<GraphView ... />`:

```tsx
            viewScope={viewScope}
            allSpaces={allSpaces}
            hasNoSpace={hasNoSpace}
            onDrillSpace={(s) => loadGraph(s)}
            onExitDrill={() => loadGraph()}
```

## 4b. `GraphView.tsx`

- [ ] **Step 5: Imports**

Adicione no topo:

```typescript
import type { CSSProperties } from "react";
import type { ViewScope } from "../types";
import { buildSpaceLegend } from "../graph/spaceLegend";
import { scopeLabel } from "../graph/scopeLabel";
```

- [ ] **Step 6: Extend `Props` and destructuring**

No `interface Props` (ou type) do componente, adicione:

```typescript
  viewScope: ViewScope;
  allSpaces: string[];
  hasNoSpace: boolean;
  onDrillSpace: (space: string) => void;
  onExitDrill: () => void;
```

E inclua `viewScope, allSpaces, hasNoSpace, onDrillSpace, onExitDrill` na lista de desestruturação dos props do componente (junto de `nodes, edges, ...`).

- [ ] **Step 7: Style consts**

Junto dos outros style consts no topo do arquivo:

```typescript
const BANNER_STYLE: CSSProperties = {
  position: "absolute", top: 12, left: 12, zIndex: 15,
  display: "flex", alignItems: "center", gap: 8,
  padding: "4px 10px", borderRadius: 6, fontSize: 12,
  background: "rgba(12,14,18,0.7)", color: "#cdd6e0",
  border: "1px solid rgba(255,255,255,0.12)",
};
const BANNER_BTN_STYLE: CSSProperties = {
  cursor: "pointer", border: "none", borderRadius: 4,
  padding: "2px 8px", fontSize: 11,
  background: "rgba(255,255,255,0.12)", color: "inherit",
};
const DRILL_BTN_STYLE: CSSProperties = {
  cursor: "pointer", border: "none", background: "transparent",
  color: "inherit", opacity: 0.6, padding: "0 4px", fontSize: 13,
};
```

- [ ] **Step 8: Replace the `spaceLegend` memo (lines 261-268)**

```typescript
    const spaceLegend = useMemo(
      () => buildSpaceLegend(nodes, allSpaces, hasNoSpace),
      [nodes, allSpaces, hasNoSpace],
    );
```

- [ ] **Step 9: Update the space-legend rows (lines 726-733) — keep focus click, add drill button**

```tsx
                    <div style={SPACE_LEGEND_LIST_STYLE}>
                      {spaceLegend.map((sp) => (
                        <LegendRow
                          key={sp.name}
                          data-testid={`legend-space-${sp.name}`}
                          active={!legendFocus || (legendFocus.kind === "space" && legendFocus.val === sp.val)}
                          onClick={() => focusLegend("space", sp.val)}
                        >
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                            {sp.name}
                          </span>
                          <span style={{ opacity: 0.4 }}>{sp.count}</span>
                          <button
                            type="button"
                            data-testid={`drill-space-${sp.name}`}
                            title="Entrar no espaço (carrega archival)"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDrillSpace(sp.val);
                            }}
                            style={DRILL_BTN_STYLE}
                          >
                            ↳
                          </button>
                        </LegendRow>
                      ))}
                    </div>
```

- [ ] **Step 10: Add the scope banner**

Dentro do wrapper externo `<div style={{ width: "100%", height: "100%", position: "relative" }}>`, logo após o `<div ref={containerRef} ... />`:

```tsx
        {(() => {
          const label = scopeLabel(viewScope);
          return (
            <div style={BANNER_STYLE} data-testid="graph-scope-banner">
              <span>{label.text}</span>
              {label.showBack && (
                <button type="button" data-testid="exit-drill" onClick={onExitDrill} style={BANNER_BTN_STYLE}>
                  ← voltar ao active graph
                </button>
              )}
            </div>
          );
        })()}
```

- [ ] **Step 11: Typecheck/build + existing tests**

Run: `cd ui && npm run build`
Expected: tsc + vite build sem erros (props novas tipadas, helpers importados).

Run: `cd ui && npm run test`
Expected: toda a suite verde (incl. api/spaceLegend/scopeLabel novos; graphModel/sigmaReducers/visual/fit intactos).

- [ ] **Step 12: Commit**

```bash
git add ui/src/App.tsx ui/src/components/GraphView.tsx
git commit -m "feat(ui): active-graph-first default + space drill-down + scope banner (#22)"
```

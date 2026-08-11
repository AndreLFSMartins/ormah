# Design — Graph active-first com drill-down de espaço (#22 slice 1)

- **Issue:** [#22](https://github.com/r-spade/ormah/issues/22) — perf(ui): make graph view scale for large number of nodes
- **Data:** 2026-06-27
- **Escopo:** fatia 1 de 3 da #22, reescopada para o renderer atual (sigma.js + graphology + forceatlas2). Fatias B e C ficam fora (ver §6).

## Contexto — por que a issue está defasada

A #22 foi escrita por @r-spade contra a implementação **Cytoscape**, cujo gargalo central era a criação síncrona de elementos no main thread. A `local-main` já migrou o graph view para **sigma.js (WebGL) + graphology + forceatlas2** (spec `2026-06-17-graph-webgl-sigma-design.md`). Consequências verificadas no código:

- FA2 já roda em **web worker** (`ui/src/graph/forceLayout.ts:36`, `graphology-layout-forceatlas2/worker`, auto-settle ~4s) — não há mais freeze síncrono.
- Sigma renderiza em **WebGL** — milhares de nós não travam o paint.
- Dimming client-side por tier/space/role já existe (`ui/src/graph/sigmaReducers.ts`).

Portanto a "crise de performance" original está majoritariamente resolvida. O que permanece aberto e mapeia para os acceptance criteria são três frentes **separáveis**: (A) active-graph-first, (B) coesão por espaço, (C) progressive/LOD. Esta spec cobre **apenas (A)**.

Verificado em 2026-06-27 que #22 continua OPEN e não foi tratada em nenhum commit/PR (o único commit adjacente, `a3c4b41`, é sizing de nó por zoom, ortogonal).

## Estado atual (fatos)

- **Backend:** `src/ormah/api/routes_ui.py:10` — `GET /ui/graph` faz `SELECT * FROM nodes` + `get_all_edges()`, sem query params. Dump total. Response: `{nodes, edges, user_node_id}`.
- **Frontend fetch:** `ui/src/api.ts:29` `fetchGraph(): Promise<GraphData>`.
- **Build:** `ui/src/graph/graphModel.ts:23` `buildGraph(data, appearance)` injeta TODOS os nós no graphology (atributos `space`, `tier`, `selfRole`, `nodeType`), roda **um** FA2 global.
- **Tier model:** `ui/src/types.ts:21` `Tier = "core" | "working" | "archival"`. `self`/`identity` NÃO são tiers — são *roles* derivados de edges `defines` (`computeSelfRoles`).
- **Escala:** store ~8.3k nós, ~80% archival → active graph ≈ 1.6k nós.
- **Endpoints úteis já existentes (para fatias futuras):** `GET /ui/graph/node/{id}` (vizinhos) e `GET /ui/search` (hybrid FTS+vector).

## Decisão

Slice A (active-graph-first), com **gating no backend** e drill-down de espaço como **sub-view focado que substitui** a vista. Justificativas: payload é ~80% archival (gating no frontend não economiza rede); sub-view focado mantém cada vista limitada em nós (escala por construção, que é o objetivo da issue) e é o de menor código (sem merge incremental nem repin de FA2).

## 1. Backend — `/ui/graph` ganha gating por tier + drill por espaço

`src/ormah/api/routes_ui.py`.

- **Default (sem params):** retorna o *active graph* — nós com `tier IN ('core','working')`, mais o nó `user_node_id` (garantia, caso o self esteja noutro tier). Archival fora.
  - **Premissa sobre identity:** nós `identity` (alvos de edges `defines` a partir do self) são tratados como pertencentes ao active graph por serem `core`/`working` — assunção do modelo de memória (whisper é core+working). Se na prática existir um nó identity em `archival`, ele cairia fora do default; nesse caso a correção é incluir explicitamente os alvos de `defines` do `user_node_id` no set (follow-up barato), **não** carregar archival. Documentar essa premissa no teste do backend.
- **`?space=<S>`:** retorna o conjunto completo do espaço `S` (active + archival de `S`). É o payload do sub-view focado.
- **Edges:** filtradas no backend para apenas as que ligam dois nós incluídos (set de ids). Evita mandar ~14k edges e dangling.
- **Response: campo aditivo `all_spaces`.** Shape vira `{nodes, edges, user_node_id, all_spaces}`, onde `all_spaces` é a lista de espaços distintos sobre **TODOS** os nós (incl. archival). Campos antigos inalterados (contrato retrocompatível). **Por quê:** o default exclui archival, então derivar a lista de espaços do payload (como `App.tsx` faz hoje) perderia espaços **100% archival** → seus chips sumiriam → o archival deles ficaria inalcançável por drill-down, violando o AC. `all_spaces` garante que todo espaço é drillável.

Sem migração de schema, sem índice novo; filtro em Python sobre o set de ids.

## 2. Frontend — default active + sub-view focado por espaço

`ui/src/components/GraphView.tsx`, `ui/src/api.ts`.

**Importante (arquitetura):** o fetch vive no `App.tsx` (estado `graph`, effect de mount em `App.tsx:93-105`); o `GraphView` é apresentacional sobre props `nodes`/`edges`/`userNodeId`. Logo o `viewScope` e o re-fetch moram no **App**, e o chip de espaço (dentro do GraphView) dispara via **callback**.

- **Carga inicial:** `loadGraph()` no App chama `fetchGraph()` (sem params) → `buildGraph` monta só o active graph. FA2 worker roda igual.
- **`fetchGraph` ganha arg opcional** `{ space?: string }` → adiciona `?space=S` à URL (`?space=` vazio = grupo "sem espaço").
- **Estado de vista (no App):** `viewScope: { kind: 'active' } | { kind: 'space'; space: string }`. `loadGraph(space?)` chama `fetchGraph`, seta `graph`/`userNodeId`/`viewScope`; em modo active também repõe `allSpaces`/`filters.spaces` a partir de `data.all_spaces`.
- **Drill (sem regredir o focus do PR#17):** clicar na linha do espaço **continua** fazendo focus-fit (comportamento PR#17 preservado). O drill é um **botão dedicado por linha** ("↳", `stopPropagation`) → `onDrillSpace(S)` → `loadGraph(S)` → **substitui** o grafo (novo `buildGraph` + novo FA2) com só aquele espaço e seus archival.
- **Voltar:** botão "← voltar ao active graph" → `onExitDrill()` → `loadGraph()`.
- **Banner/affordance:** badge persistente no canto do painel do grafo, texto derivado de um helper puro `scopeLabel(viewScope)`. Modo active: *"Active graph · archival oculto"*. Modo space: *"Espaço: S · com archival"* + botão voltar.
- **Legenda completa:** os chips de espaço vêm de um helper puro `buildSpaceLegend(nodes, allSpaces)` — semeia todos os espaços de `allSpaces` (count 0) e conta a partir dos nós carregados, de modo que espaços 100% archival aparecem (count 0) e ficam drilláveis.

Substituição reusa o caminho de mount existente; sem merge incremental, sem pin de FA2, sem endpoint novo no frontend.

**Decomposição testável:** como o vitest do projeto só inclui `src/**/*.test.ts` (sem `@testing-library/react`, sem testes de componente), a lógica nova vive em **funções puras** testáveis: `fetchGraph` (montagem de URL), `buildSpaceLegend(nodes, allSpaces)`, `scopeLabel(viewScope)`. O JSX do GraphView só renderiza o resultado dessas funções (sem lógica própria a testar).

## 3. Interação com features do PR#17 (não regredir)

Permanecem intactos: zoom-out, legend/focus controls, identity legend rows, space legend scrollável, label haze fix, zoom control à direita.

O `FilterDrawer` continua fazendo dimming sobre o set carregado. O checkbox de tier **archival** fica sem efeito enquanto a vista é o active graph (não há archival carregado para dimar) — **comportamento esperado e documentado, não regressão**. Archival só aparece ao drillar um espaço.

## 4. Componentes e fronteiras

| Unidade | Responsabilidade | Depende de |
|---|---|---|
| `get_graph` (backend) | Servir active graph (default) ou conjunto de um espaço (`?space`), com edges podadas + `all_spaces` | `engine.db`, `engine.graph.get_all_edges` |
| `fetchGraph(opts?)` | Buscar `/ui/graph` com/sem `space` | fetch |
| `App` (`loadGraph`, `viewScope`) | Dono do fetch e do estado de vista; orquestra default vs drill; passa props/callbacks ao GraphView | `fetchGraph` |
| `buildSpaceLegend(nodes, allSpaces)` | **Puro** — chips de todos os espaços com counts dos nós carregados | — |
| `scopeLabel(viewScope)` | **Puro** — label do banner + flag `showBack` | — |
| `GraphView` | Renderiza grafo + legenda (com botão drill) + banner; dispara `onDrillSpace`/`onExitDrill` | `buildGraph`, `buildSpaceLegend`, `scopeLabel` |
| `buildGraph` | **Inalterado** — monta qualquer `GraphData` que receber | graphology |

`buildGraph` não muda: já é agnóstico ao subconjunto. O gating vive antes dele (backend), a orquestração de vista vive acima (App), e a lógica testável da legenda/banner vive em helpers puros.

## 5. Testes (TDD)

- **Backend** (`tests/`):
  - default exclui `archival` e inclui `user_node_id`;
  - `?space=S` inclui archival de `S` e exclui nós de outros espaços;
  - edges retornadas só ligam nós incluídos (sem dangling).
- **Frontend** (`ui/src/**/*.test.ts`, funções puras — sem render de componente):
  - `fetchGraph()` → `/ui/graph`; `fetchGraph({space:'work'})` → `/ui/graph?space=work`; `fetchGraph({space:''})` → `/ui/graph?space=`;
  - `buildSpaceLegend(nodes, allSpaces)` inclui todos os espaços de `allSpaces` (espaço 100% archival aparece com count 0), conta a partir dos nós, e mapeia o grupo sem espaço para `val=""`;
  - `scopeLabel(viewScope)` retorna label correto e `showBack` por modo (active vs space).

## 6. Fora de escopo (explícito)

- Coesão por espaço / macro-micro layout (**fatia B** — smear ~26.8% cross-space sob FA2 global).
- Progressive rendering / LOD — redução de edges/labels no overview (**fatia C**).
- On-demand por **busca** e por **foco de nó** (vizinhança) — o AC exige ao menos um mecanismo, satisfeito pelo drill-down de espaço.
- Cap de tamanho no próprio active graph (só relevante se o active crescer muito; pertence à fatia C).
- Badges de contagem de archival por espaço na legenda.

## 7. Acceptance criteria cobertos por esta fatia

- ✅ Default renderiza self/identity/core/working sem carregar todo archival no sigma.
- ✅ Archival alcançável via drill-down de espaço (um dos mecanismos exigidos).
- ✅ UI comunica que mostra o active graph, com archival sob demanda.
- ✅ Features do PR#17 intactas.
- ⏭️ Coesão de espaço sem force layout global caro → **fatia B**.
- ⏭️ "Render responsivo a 3.5K+ / sem warnings de unresponsive" → já largamente atendido pela migração WebGL; LOD residual em **fatia C**.

## 8. Ajustes pós-council (2026-06-29)

Revisão por Cursor+Codex (perfis architecture/performance) incorporou dois achados e deferiu um:

- **F1 — archival sem espaço inalcançável (aceito).** `all_spaces` cobre só espaços nomeados; o grupo "(no space)" só aparecia se houvesse nó ativo sem espaço. Correção: backend retorna `has_no_space` (existe nó sem espaço sobre TODOS os nós) e `buildSpaceLegend(nodes, allSpaces, hasNoSpace)` renderiza "(no space)" mesmo com count 0, mantendo-o drillável.
- **F2 — race de reload (aceito).** `loadGraph('space')` e `loadGraph()` sobrepostos podiam resolver fora de ordem e travar a UI no escopo errado. Correção: helper puro `createRequestGuard` (token por chamada; aplica só a última resposta).
- **F3 — filtro de edges em Python no caminho ativo (deferido, com rationale).** A issue afirma que o backend não é o gargalo; a ~14k edges o filtro Python é µs, e constranger em SQL esbarra no limite ~999 de bind-params do SQLite (set ativo ~1.6k ids) exigindo tabela temporária. Mantido com comentário `ponytail:` nomeando o teto e o upgrade path; reavaliar em B/C.

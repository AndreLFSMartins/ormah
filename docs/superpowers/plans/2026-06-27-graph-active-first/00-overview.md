# Graph active-first com drill-down de espaço — Implementation Plan (#22 slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each subagent gets ONLY its task file + this overview.

**Goal:** Fazer o graph view carregar por padrão só o *active graph* (tiers `core`/`working` + nó self), com archival sob demanda via drill-down de espaço — no renderer sigma.js atual.

**Architecture:** Gating no **backend** (`GET /ui/graph` filtra por tier; `?space=S` traz o espaço completo incl. archival; edges podadas ao set de nós; campo **aditivo** `all_spaces`). O fetch e o estado `viewScope` vivem no `App.tsx`; o `GraphView` é apresentacional e dispara o drill via callback. A lógica testável fica isolada em **funções puras** (`fetchGraph` URL, `buildSpaceLegend`, `scopeLabel`), porque o vitest do projeto só inclui `src/**/*.test.ts` e não há infra de teste de componente React.

**Tech Stack:** Backend Python/FastAPI/pytest — rodar via `.venv/bin/python`. Frontend Vite/TypeScript/vitest (jsdom) — `npm run test` / `npm run build` em `ui/`.

**Spec:** `docs/superpowers/specs/2026-06-27-graph-active-first-design.md`

## Tasks (executar em ordem)

1. **`01-backend-gating.md`** — `/ui/graph`: default sem archival (+ user_node), `?space=S` drill, `?space=` grupo sem-espaço, edges podadas, campo `all_spaces`.
2. **`02-frontend-types-api.md`** — `GraphData.all_spaces?`, tipo `ViewScope`, `fetchGraph(opts?)`.
3. **`03-pure-helpers.md`** — `buildSpaceLegend(nodes, allSpaces)` e `scopeLabel(viewScope)` (puras + testes).
4. **`04-app-graphview-wiring.md`** — App: `loadGraph`/`viewScope`/props; GraphView: props, botão drill na legenda, banner. Verificação via `npm run build` (tsc).
5. **`05-verify.md`** — suite completa backend+frontend, lint, build, smoke manual via `make dev`.
6. **`06-council-v2-fixes.md`** — fixes do council v2: `buildDimmed` extraído/scope-aware (C1/C2), `loadGraph` com `.catch`+toast e `""` em `filters.spaces` (C3), correções de contagem (C4).

## Ajustes do council (2026-06-29)

Revisão por Cursor+Codex (perfis architecture/performance) incorporou 2 achados e deferiu 1:

- **F1 (aceito):** archival do grupo "sem espaço" ficava inalcançável — backend agora retorna `has_no_space` e `buildSpaceLegend` renderiza "(no space)" mesmo com count 0 (Task 1 + Task 3).
- **F2 (aceito):** race entre `loadGraph('space')` e `loadGraph()` — guarda de sequência `createRequestGuard` aplica só a última resposta (Task 3c + Task 4).
- **F3 (deferido, com rationale):** filtro de edges em Python no caminho ativo — mantido com comentário `ponytail:` (a issue diz que o backend não é o gargalo; SQL-constrain esbarra no limite de bind-params do SQLite). Reavaliar em B/C.

## Out of scope

Coesão por espaço (fatia B), LOD/redução de edges no overview (fatia C), on-demand por busca/foco de nó, cap no próprio active graph, badges de contagem de archival. **Não regredir** features do PR#17 (zoom, legend/focus, identity rows, space legend, label haze, zoom control). O click na linha do espaço **continua** fazendo focus-fit; o drill é um botão dedicado.

## Notas operacionais

- `docs/superpowers/` é **gitignored** — não versionar o spec/plano.
- Branch: trabalhar numa feature branch a partir de `local-main` (não commitar direto na main).
- Follow-up (não-código, decisão do André): comentar em #22 que o diagnóstico Cytoscape está defasado e que a fatia 1 (active-first) foi implementada; B/C seguem abertas.

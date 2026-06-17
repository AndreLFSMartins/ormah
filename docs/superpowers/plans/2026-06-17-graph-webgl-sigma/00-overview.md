# Graph view WebGL live-force migration — Implementation Plan (overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each task lives in its own file in this directory; give a subagent only its task file + this overview. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the cytoscape + cola Canvas graph view with sigma.js v3 (WebGL) running a live ForceAtlas2 simulation in a Web Worker, preserving the current visual identity.

**Architecture:** Pure helpers (colors/sizes/edge-color/self-roles) extracted to `ui/src/graph/visual.ts`. A pure `graphModel.ts` turns the `/ui/graph` payload into a graphology `Graph`. A pure `sigmaReducers.ts` computes per-frame hover/dim/focus overrides. `forceLayout.ts` wraps the FA2 worker. `GraphView.tsx` becomes a thin orchestrator that mounts sigma, runs the layout, and wires events + the (reused) legend to reducer state. Layout is pure organic FA2 (option A) — no component packing, so the grid/losango disappears. No position persistence.

**Tech Stack:** React 18 + Vite + TypeScript; sigma v3 (WebGL render); graphology + graphology-layout (`random.assign`) + graphology-layout-forceatlas2 (`FA2Layout` worker, `inferSettings`); vitest + jsdom (unit tests); Playwright (Python, uv tool) for the visual test.

**Spec:** `docs/superpowers/specs/2026-06-17-graph-webgl-sigma-design.md`
**Branch:** `feat/graph-webgl-sigma`

---

## File structure

| File | Responsibility | Task |
|------|----------------|------|
| `ui/package.json`, `ui/vitest.config.ts` | deps + JS test runner | 1 |
| `ui/src/graph/visual.ts` | pure: tier/border color, node size, edge color, node label, self-role map, theme tokens | 2 |
| `ui/src/graph/visual.test.ts` | unit tests for the above | 2 |
| `ui/src/graph/graphModel.ts` | pure: `GraphData` + appearance → graphology `Graph` (x/y/size/color/label, edge color) | 3 |
| `ui/src/graph/graphModel.test.ts` | unit tests (happy, missing space/tier, empty, isolated) | 3 |
| `ui/src/graph/sigmaReducers.ts` | pure: `makeNodeReducer`/`makeEdgeReducer` from view state | 4 |
| `ui/src/graph/sigmaReducers.test.ts` | unit tests (hover highlight+dim, dimmedSpaces) | 4 |
| `ui/src/graph/forceLayout.ts` | FA2 worker wrapper: start/stop/kill + settle timer | 5 |
| `ui/src/components/GraphView.tsx` | orchestrator: mount sigma, run layout, wire events + legend → reducers | 6 |
| `ui/playwright/test_graph_layout.py` | visual test: settle, canvas present, cluster separation | 7 |
| `ui/package.json` (cleanup) | remove cytoscape*, delete dead code | 8 |

## Tasks (in order)

1. `01-tooling-and-deps.md` — add sigma/graphology deps + vitest; keep cytoscape until Task 8.
2. `02-visual-helpers.md` — extract pure visual helpers + `computeSelfRoles`, with tests.
3. `03-graph-model.md` — `buildGraph` payload→graphology, with tests.
4. `04-sigma-reducers.md` — hover/dim/focus reducer factories, with tests.
5. `05-force-layout.md` — FA2 worker wrapper.
6. `06-graphview-rewrite.md` — sigma orchestrator + legend wiring (the big one).
7. `07-playwright-visual.md` — Python Playwright settle + cluster-separation assertion.
8. `08-cleanup-and-verify.md` — remove cytoscape, lint/build/test green.

## Conventions

- TDD: failing test → run (fail) → minimal impl → run (pass) → commit. One concept per commit.
- Pure modules (`visual`, `graphModel`, `sigmaReducers`) carry no DOM/sigma imports — fully unit-testable.
- Visual parity values are ported verbatim from the current `GraphView.tsx` (cited line numbers per task) — do not re-derive colors/sizes.
- Run UI commands from `ui/` in a subshell: `( cd ui && npm run <script> )`.
- Manual app verification (Task 6) uses the dev-run setup; see `[[ormah-dev-run-setup]]`.

## Out of scope (from spec)

Position persistence; bounded-forgetting (#28); embeddings semantic-map layout; per-space galaxies (option B); glow halo / edge curves / dashed archival border (not perceived today — not parity).

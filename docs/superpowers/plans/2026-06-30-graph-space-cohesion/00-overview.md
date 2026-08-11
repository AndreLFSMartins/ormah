# Graph Per-Space Cohesion (#22 slice B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each subagent gets THIS overview + its own task file.

**Goal:** When the `clusterBySpace` toggle is on AND the graph is small enough to lay out cheaply,
render each space as a cohesive cluster (deterministic macro/micro layout), replacing the global-FA2
smear (~26.8% cross-space). Large graphs and the toggle-off path keep the existing async FA2 worker
— no main-thread freeze.

**Architecture:** New pure module `ui/src/graph/clusterLayout.ts` computes final node positions
(per-space synchronous FA2 micro-layout with Barnes-Hut + macro ring with slots sized by cluster
radius). `GraphView` picks the layout: cluster (static, synchronous) only when `clusterBySpace` is on
AND the largest single space is small (`largestSpaceSize(nodes) <= CLUSTER_LAYOUT_MAX_SPACE_NODES`);
otherwise the existing global FA2 worker. A new FilterDrawer checkbox drives `clusterBySpace`. No new
dependency; no backend change.

**Tech Stack:** Vite/TS, graphology + graphology-layout-forceatlas2 (already in bundle), vitest
(pure-function tests — vitest includes `src/**/*.test.ts`; there is NO React Testing Library, so
component wiring is verified by `tsc`/`build` + the existing Playwright E2E + manual smoke).

**Spec:** `docs/superpowers/specs/2026-06-30-graph-space-cohesion-design.md`

---

## Why the size gate (council R1, accepted)

The original plan assumed the rendered graph is the small active set. **It is not:** App mounts with
`loadAll()` (`App.tsx:150`, `?scope=all`) → the full graph incl. archival (~8.3k nodes), and
`clusterBySpace` defaults `true` (`App.tsx:60`). Running synchronous FA2 over the full store on the
main thread would freeze the UI. The gate routes the large default to the async worker (cohesion not
attempted there — it is a zoomed-out hairball anyway) and applies cluster cohesion only where it is
visible and affordable: the active view, a drilled space, or any graph whose largest single space is
under the threshold. The gate keys on the **largest space** (not the total) because FA2 cost is
per-space, and the micro layout enables **Barnes-Hut** for parity with the global worker (council R2).

## Run commands (this repo)

- Frontend tests: `( cd ui && npm run test )`
- Type-check + build: `( cd ui && npm run build )`
- Single test file: `( cd ui && npx vitest run src/graph/clusterLayout.test.ts )`
- Playwright drag E2E (needs DEV server): `( cd ui && python3 playwright/test_graph_drag.py )`
- Playwright cluster E2E (needs DEV server): `( cd ui && python3 playwright/test_graph_cluster.py )`

Anchor every command to `ui/` via a subshell, never a bare `cd` that leaks.

## File structure (decomposition)

| File | Responsibility | Task |
|------|----------------|------|
| `ui/src/graph/clusterLayout.ts` | Pure: `crossSpaceMixing` + `computeClusterLayout` (macro/micro, Barnes-Hut, radius-sized slots) + `largestSpaceSize` + `CLUSTER_LAYOUT_MAX_SPACE_NODES` | 1, 2 |
| `ui/src/graph/clusterLayout.test.ts` | vitest unit tests | 1, 2 |
| `ui/src/components/FilterDrawer.tsx` | New "layout" checkbox driving `clusterBySpace` | 3 |
| `ui/src/App.tsx` | `toggleClusterBySpace` setter + DEV-only `window.__ormahSetClusterBySpace` hook | 3 |
| `ui/src/graph/forceLayout.ts` | Export the existing NOOP static layout | 4 |
| `ui/src/components/GraphView.tsx` | Mount-effect layout pick (largest-space gate) + `__ormahLayoutMode` DEV hook + `clusterBySpace` dep + immediate `layoutReady` | 4 |
| `ui/playwright/test_graph_drag.py` | Force cluster off before asserting global-worker reheat | 4 |
| `ui/playwright/test_graph_cluster.py` | Assert the cluster path runs (mode + node count) | 4 |

## Key facts the engineer must not rediscover

- `MemoryNode.space` is `string | null`. Treat `null` and `""` as ONE "no-space" bucket (key `""`).
- `Edge` uses `source_id` / `target_id`.
- `forceAtlas2.assign(graph, { iterations, settings })` is the synchronous API (default export of
  `graphology-layout-forceatlas2`); deterministic given starting x/y.
- `clusterBySpace` is `filters.clusterBySpace` (boolean, default `true`, `App.tsx:60`). It is NOT a
  `Set`, so `toggleFilter` (which mutates Sets) cannot drive it — Task 3 adds a dedicated setter.
- The mount effect (`GraphView.tsx:321`) deps are `[nodes, edges, userNodeId]`; Task 4 adds
  `clusterBySpace` so toggling re-runs the layout (full remount is fine for a mode switch).
- The size gate keys on `largestSpaceSize(nodes)` (largest per-space count), NOT total node count —
  FA2 runs per space, so a 1500-node graph split across many small spaces is cheap.
- `test_graph_drag.py` asserts `reheated_delta > 0.001` (FA2 worker resumes after drag). That only
  holds on the global-worker path, so Task 4 makes the test force `clusterBySpace=false` first.

## Task order

1. **Task 1** — `crossSpaceMixing` metric helper (TDD).
2. **Task 2** — `computeClusterLayout` (TDD): radius-sized macro slots + `CLUSTER_LAYOUT_MAX_NODES`.
3. **Task 3** — FilterDrawer checkbox + App setter + DEV hook (no unit test; `build` verifies).
4. **Task 4** — GraphView size-gated wiring + `forceLayout` export + Playwright fix (`build` + E2E).
5. **Task 5** — full verification (build, vitest, Playwright, manual smoke).

## Out of scope

- Slice C (LOD / progressive rendering).
- Cohesion on the large incl-archival default view (intentionally left to the worker; upgrade path:
  per-space layout in the worker if that view ever needs cohesion).
- Any backend / `/ui/graph` change.

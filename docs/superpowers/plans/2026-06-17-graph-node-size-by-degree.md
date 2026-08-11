# Graph Node Size by Degree — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Size each graph node by its connection count (degree) instead of `access_count`, so the WebGL graph gains Obsidian-like visual hierarchy (hubs large, isolated nodes small).

**Architecture:** The size is computed in `ui/src/graph/visual.ts` (`nodeSize`/`displayNodeSize`) and applied in `ui/src/graph/graphModel.ts`. Because degree is only known after edges are added, `buildGraph` moves the `size` assignment into a second pass that runs after the edge loop; `applyAppearance` reads degree directly from the already-built graph.

**Tech Stack:** TypeScript, graphology (graph model), vitest (tests), sigma.js v3 (renderer, `itemSizesReference: "positions"` regime). Run tests from `ui/` with `npx vitest run <file>`.

**Branch:** `feat/graph-webgl-sigma` (UI feature → upstream PR). After all tasks pass on that branch, merge into `local-main` and rebuild `ui_dist`.

**Spec:** `docs/superpowers/specs/2026-06-17-graph-node-size-by-degree-design.md`

---

## Branch setup (do once before Task 1)

- [ ] **Step 0: Switch to the feature branch**

The implementation belongs on the UI feature branch, not `local-main`.

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git checkout feat/graph-webgl-sigma
git branch --show-current
```
Expected: `feat/graph-webgl-sigma`

---

### Task 1: Change `nodeSize`/`displayNodeSize` to take degree (visual.ts)

**Files:**
- Modify: `ui/src/graph/visual.ts` (current `nodeSize` lines 36-39, `displayNodeSize` lines 41-44)
- Test: `ui/src/graph/visual.test.ts` (existing self-floor test at lines 34-36; existing range test added by the size fix)

**Current code (for reference — this is what you are replacing):**
```ts
function nodeSize(accessCount: number): number {
  return Math.min(5, Math.max(2, 2 + Math.log2(accessCount + 1) * 0.5));
}

export function displayNodeSize(accessCount: number, selfRole: SelfRole): number {
  const size = nodeSize(accessCount);
  return selfRole === "self" ? Math.max(3.5, size) : size;
}
```

- [ ] **Step 1: Update the tests to express the degree contract**

Replace the existing range test block in `ui/src/graph/visual.test.ts`. Find this block (added by the prior node-size fix):
```ts
  it("keeps node sizes within the position-unit range (Ø below FA2 neighbour gap)", () => {
    expect(displayNodeSize(0, "")).toBe(2); // floor
    expect(displayNodeSize(1_000_000, "")).toBeLessThanOrEqual(5); // ceiling
    expect(displayNodeSize(8, "")).toBeGreaterThan(displayNodeSize(0, "")); // grows with access
  });
```
Replace it with (degree-based, cap 10). The first assertion is the one that
fails under the old `access_count` formula (old cap is 5, so a high input
saturates at 5 — strictly less than the new curve's value at degree 31):
```ts
  it("sizes nodes by degree: floor at 2, grows past old cap, capped at 10", () => {
    expect(displayNodeSize(31, "")).toBeGreaterThan(5);          // FAILS on old formula (old cap = 5)
    expect(displayNodeSize(0, "")).toBe(2);                       // isolated -> floor
    expect(displayNodeSize(2, "")).toBeGreaterThan(displayNodeSize(0, "")); // grows
    expect(displayNodeSize(10, "")).toBeGreaterThan(displayNodeSize(2, "")); // keeps growing
    expect(displayNodeSize(214, "")).toBeLessThanOrEqual(10);    // hub capped
    expect(displayNodeSize(10_000, "")).toBeLessThanOrEqual(10); // cap holds
  });
```

The existing self-floor test (lines 34-36) stays as-is and still passes:
```ts
  it("sizes self nodes at least the self floor", () => {
    expect(displayNodeSize(0, "self")).toBeGreaterThanOrEqual(3.5);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd ui && npx vitest run src/graph/visual.test.ts
```
Expected: FAIL — **deterministically**. The first assertion, `expect(displayNodeSize(31, "")).toBeGreaterThan(5)`, fails under the old `access_count` formula because its cap is 5: `displayNodeSize(31,"")` = `min(5, 2+log2(32)*0.5)` = `min(5, 5)` = 5, which is NOT > 5. This is the required red gate (council: Cursor). **Do not proceed to Step 3 unless this assertion actually fails** — if the suite is green here, the old formula was not in place and the premise is wrong; stop and re-check the working tree.

- [ ] **Step 3: Replace the formula with the degree curve**

In `ui/src/graph/visual.ts`, replace the `nodeSize` and `displayNodeSize` functions (and update the comment above them) with:
```ts
// Sizes are in LAYOUT-POSITION units (sigma uses itemSizesReference: "positions"
// + zoomToSizeRatioFunction: ratio => ratio), so radius scales 1:1 with zoom.
// Node size reflects DEGREE (connection count), like Obsidian's graph: isolated
// nodes stay small (Ø floor), hubs grow but are capped so they don't dominate.
// Validated on the live graph: deg 0 -> 2, deg 2 (median) -> 4.06, deg 214 (hub) -> 10.
function nodeSize(degree: number): number {
  return Math.min(10, 2 + Math.log2(degree + 1) * 1.3);
}

export function displayNodeSize(degree: number, selfRole: SelfRole): number {
  const size = nodeSize(degree);
  return selfRole === "self" ? Math.max(3.5, size) : size;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd ui && npx vitest run src/graph/visual.test.ts
```
Expected: PASS — `displayNodeSize(0,"")` = 2, `displayNodeSize(2,"")` ≈ 4.06, `displayNodeSize(10,"")` ≈ 6.50, `displayNodeSize(214,"")` = 10 (capped), self-floor 3.5 holds.

- [ ] **Step 5: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git add ui/src/graph/visual.ts ui/src/graph/visual.test.ts
git commit -m "feat(graph): size nodes by degree, not access_count

access_count is 0 on 94.6% of nodes, so node size never varied. Switch
nodeSize/displayNodeSize to take degree (connection count) with a log curve
capped at 10, matching Obsidian's degree-based sizing. Self floor (3.5) kept.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Feed degree (not access_count) into the graph (graphModel.ts)

**Files:**
- Modify: `ui/src/graph/graphModel.ts` (`buildGraph` lines 20-54, `applyAppearance` lines 59-70)
- Test: `ui/src/graph/graphModel.test.ts`

**Current code (for reference):**

`buildGraph` sets size inside the node loop (before edges exist):
```ts
  data.nodes.forEach((n, i) => {
    const role = roles.get(n.id) ?? "";
    const { x, y } = seedPosition(i, data.nodes.length);
    graph.addNode(n.id, {
      x,
      y,
      size: displayNodeSize(n.access_count, role),
      color: tierColor(n.tier, role, appearance),
      label: nodeLabel(n),
      space: n.space || "",
      tier: n.tier,
      nodeType: n.type,
      selfRole: role,
    });
  });
```
`applyAppearance` re-sets size from access_count:
```ts
    graph.setNodeAttribute(n.id, "size", displayNodeSize(n.access_count, role));
```

- [ ] **Step 1: Write the failing test in graphModel.test.ts**

Add this test inside the `describe("buildGraph", ...)` block in `ui/src/graph/graphModel.test.ts`:
```ts
  it("sizes nodes by unique-neighbour count: connected > isolated, isolated at floor", () => {
    const nodes = [node({ id: "hub" }), node({ id: "a" }), node({ id: "b" }), node({ id: "lonely" })];
    const edges: Edge[] = [
      { source_id: "hub", target_id: "a", edge_type: "related_to", weight: 1, created: "" },
      { source_id: "hub", target_id: "b", edge_type: "related_to", weight: 1, created: "" },
    ];
    const g = buildGraph(data({ nodes, edges }), DEFAULT_GRAPH_APPEARANCE);
    const hubSize = g.getNodeAttribute("hub", "size") as number;
    const lonelySize = g.getNodeAttribute("lonely", "size") as number;
    expect(hubSize).toBeGreaterThan(lonelySize); // 2 unique neighbours > 0
    expect(lonelySize).toBe(2);                  // isolated -> floor
  });

  it("counts UNIQUE neighbours, not parallel edges (multigraph)", () => {
    // x↔y connected by THREE parallel edges (different edge_types). The node has
    // ONE unique neighbour, so its size must equal a single-neighbour node's size,
    // NOT a degree-3 node's size. This fails if the code uses graph.degree().
    const nodes = [node({ id: "x" }), node({ id: "y" }), node({ id: "p" }), node({ id: "q" })];
    const edges: Edge[] = [
      { source_id: "x", target_id: "y", edge_type: "supports", weight: 1, created: "" },
      { source_id: "x", target_id: "y", edge_type: "defines", weight: 1, created: "" },
      { source_id: "x", target_id: "y", edge_type: "related_to", weight: 1, created: "" },
      { source_id: "p", target_id: "q", edge_type: "related_to", weight: 1, created: "" },
    ];
    const g = buildGraph(data({ nodes, edges }), DEFAULT_GRAPH_APPEARANCE);
    // x has 1 unique neighbour (y) via 3 edges; p has 1 unique neighbour (q) via 1 edge.
    expect(g.getNodeAttribute("x", "size")).toBe(g.getNodeAttribute("p", "size"));
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd ui && npx vitest run src/graph/graphModel.test.ts
```
Expected: FAIL — under the current code, every node's size comes from `access_count` (all 0 here), so `hub` and `lonely` are both size 2; `expect(hubSize).toBeGreaterThan(lonelySize)` fails (2 is not > 2).

- [ ] **Step 3: Move size to a post-edge pass in buildGraph**

In `ui/src/graph/graphModel.ts`, edit `buildGraph`. Remove `size` from the `addNode` call:
```ts
  data.nodes.forEach((n, i) => {
    const role = roles.get(n.id) ?? "";
    const { x, y } = seedPosition(i, data.nodes.length);
    graph.addNode(n.id, {
      x,
      y,
      color: tierColor(n.tier, role, appearance),
      label: nodeLabel(n),
      space: n.space || "",
      tier: n.tier,
      // NOTE: store the domain node type under `nodeType`, NOT `type` — sigma
      // reserves the node `type` attribute to pick the render program (e.g.
      // "circle"); a domain value like "concept" makes sigma throw
      // "could not find a suitable program for node type". See FilterDrawer type filter.
      nodeType: n.type,
      selfRole: role,
    });
  });
```
Then, AFTER the existing `for (const e of data.edges) { ... graph.addEdge(...) }` loop and BEFORE `return graph;`, add the size pass:
```ts
  // Size by UNIQUE NEIGHBOUR count (not edge degree — the graph is a multigraph
  // with parallel edges, council R2). Known only after edges are added.
  // Single deterministic pass over every node — the source of truth for size.
  graph.forEachNode((id) => {
    graph.setNodeAttribute(id, "size", displayNodeSize(graph.neighbors(id).length, roles.get(id) ?? ""));
  });
```

- [ ] **Step 4: Update applyAppearance to read unique-neighbour count**

In `ui/src/graph/graphModel.ts`, in `applyAppearance`, replace the size line. Find:
```ts
    graph.setNodeAttribute(n.id, "size", displayNodeSize(n.access_count, role));
```
Replace with:
```ts
    graph.setNodeAttribute(n.id, "size", displayNodeSize(graph.neighbors(n.id).length, role));
```

- [ ] **Step 5: Run the graphModel tests to verify they pass**

Run:
```bash
cd ui && npx vitest run src/graph/graphModel.test.ts
```
Expected: PASS — `hub` (degree 2) ≈ 4.06, `lonely` (degree 0) = 2, so `hubSize > lonelySize` and `lonelySize === 2`. The existing tests still pass: the `size > 0` test (node "a", isolated, degree 0 → size 2 > 0) holds; `applyAppearance` recolor test unaffected (it doesn't assert size).

- [ ] **Step 6: Add the applyAppearance size-regression test (council: Cursor + Codex)**

Both peers flagged that `applyAppearance` switches to degree sizing but no test
guards it — reverting only that line keeps tests green. Add this test inside the
`describe("applyAppearance", ...)` block in `ui/src/graph/graphModel.test.ts`. The
node payloads carry a misleading high `access_count` so the test fails if the code
ever falls back to access-count sizing:
```ts
  it("keeps degree-based size after appearance changes (hub > isolated)", () => {
    const nodes = [
      node({ id: "hub", access_count: 0 }),
      node({ id: "a", access_count: 0 }),
      node({ id: "lonely", access_count: 999 }), // misleading: high access, zero degree
    ];
    const edges: Edge[] = [
      { source_id: "hub", target_id: "a", edge_type: "related_to", weight: 1, created: "" },
    ];
    const d = data({ nodes, edges });
    const g = buildGraph(d, DEFAULT_GRAPH_APPEARANCE);
    applyAppearance(g, d, { ...DEFAULT_GRAPH_APPEARANCE,
      colors: { core: "#111111", working: "#222222", archival: "#333333" } });
    const hubSize = g.getNodeAttribute("hub", "size") as number;       // degree 1
    const lonelySize = g.getNodeAttribute("lonely", "size") as number; // degree 0, access 999
    expect(hubSize).toBeGreaterThan(lonelySize); // degree wins, not access_count
    expect(lonelySize).toBe(2);                  // isolated -> floor (NOT inflated by access 999)
  });
```

- [ ] **Step 7: Run graphModel tests to verify the new test passes**

Run:
```bash
cd ui && npx vitest run src/graph/graphModel.test.ts
```
Expected: PASS — after `applyAppearance`, `hub` (degree 1) ≈ 3.30 > `lonely` (degree 0, access 999) = 2. If the code regressed to access_count, `lonely` would be ≈ `min(10, 2+log2(1000)*1.3)` ≈ 10.96→cap, failing both assertions.

- [ ] **Step 8: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git add ui/src/graph/graphModel.ts ui/src/graph/graphModel.test.ts
git commit -m "feat(graph): size by unique-neighbour count after edges are built

buildGraph now sets node size in a post-edge pass (connection count is unknown
before edges exist); both buildGraph and applyAppearance use
graph.neighbors(id).length (UNIQUE neighbours), not graph.degree(), because the
multigraph has parallel edges that would over-count connections. access_count is
no longer used for sizing. Adds an applyAppearance size-regression test and a
parallel-edge test so a revert to access_count or degree cannot pass silently
(council: Cursor + Codex).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Full UI test suite + empirical verification on the live graph

**Files:**
- No code changes — verification only.

- [ ] **Step 1: Run the full graph test suite**

Run:
```bash
cd ui && npx vitest run src/graph/
```
Expected: PASS — all graph tests (visual, graphModel, sigmaReducers, forceLayout) green.

- [ ] **Step 2: Rebuild the production UI bundle**

Run:
```bash
cd ui && npm run build
```
Expected: `tsc && vite build` succeeds with no type errors (confirms no dangling `access_count` size reference), emits a new `../src/ormah/ui_dist/assets/index-*.js`.

- [ ] **Step 3: Verify node-size variation on the live graph (headless)**

The dev server (Vite 5173) exposes `window.__ormahGraph` in DEV. Confirm the dev server is up (`curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/` → 200) and the backend on 8787 is serving the graph. Then create `ui/verify_degree_size.py`:
```python
"""Verify node sizes now vary by degree on the live graph."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://localhost:5173", wait_until="domcontentloaded")
    pg.wait_for_function("() => window.__ormahGraph && window.__ormahSigma", timeout=30000)
    pg.wait_for_timeout(7000)
    res = pg.evaluate("""() => {
        const g = window.__ormahGraph; const rows = [];
        // size is RADIUS in position units; unique-neighbour count drives it.
        g.forEachNode((id, a) => rows.push({ id, nbr: g.neighbors(id).length, r: a.size, x: a.x, y: a.y }));
        const sizes = rows.map(n => n.r);
        rows.sort((p, q) => p.nbr - q.nbr);

        // Council R2 (Cursor + Codex): overlap must be measured over the WHOLE
        // graph, not just the top-degree hubs — mid-degree nodes (r 4-8.5) can
        // overlap user-visibly. Count every pair whose centre distance is less
        // than the sum of radii (true overlap). O(n^2) ~ 1800^2 = 3.2M, fine here.
        let overlappingPairs = 0, minGap = Infinity;
        for (let i = 0; i < rows.length; i++) {
            for (let j = i + 1; j < rows.length; j++) {
                const a = rows[i], b = rows[j];
                const gap = Math.hypot(a.x - b.x, a.y - b.y) - (a.r + b.r); // edge-to-edge
                if (gap < 0) overlappingPairs++;
                if (gap < minGap) minGap = gap;
            }
        }
        const isolated = rows.find(n => n.nbr === 0);
        return {
            order: g.order,
            sizeMin: Math.min(...sizes), sizeMax: Math.max(...sizes),
            distinctSizes: new Set(sizes.map(s => s.toFixed(2))).size,
            isolatedSize: isolated ? isolated.r : null,
            maxNbr: rows[rows.length - 1].nbr, hubSize: rows[rows.length - 1].r,
            overlappingPairs,                       // global count — must be ~0 / small
            minGapEdgeToEdge: +minGap.toFixed(2),   // most-negative = worst overlap depth
        };
    }""")
    import json
    print(json.dumps(res, indent=2))
    b.close()
```
Run:
```bash
cd ui && uv run --with playwright python verify_degree_size.py
```
Expected: `sizeMin` = 2 (isolated nodes), `sizeMax` ≈ 10 (hub capped), `distinctSizes` well above 1 (variation exists — was effectively 1 before), `isolatedSize` = 2, `hubSize` ≈ 10. The overlap gate is **global** (council R2): `overlappingPairs` should be small relative to the ~1800 nodes (a handful is tolerable since FA2's `adjustSizes: true` already spaces by size; a large count means the cap-10 curve packs mid-degree nodes too tightly). Record the baseline number; if `overlappingPairs` is large or `minGapEdgeToEdge` is strongly negative, lower the cap or the curve multiplier in `nodeSize` (Task 1) and re-verify. Delete the scratch script afterward (`rm ui/verify_degree_size.py`) — it is not part of the repo. (Promoting this to a permanent integration test is a documented follow-up — `ui/` has no Playwright in CI today.)

- [ ] **Step 4: Final commit (if any test scaffolding changed)**

No commit expected for this task unless Step 1-3 surfaced a regression requiring a fix. If a fix was needed, commit it with a message describing the regression and the fix.

---

## Merge into the Beta (after all tasks green)

- [ ] **Step 1: Merge feat → local-main and rebuild the served bundle**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git checkout local-main
git merge feat/graph-webgl-sigma --no-edit
cd ui && npm run build
```
Expected: clean merge; `ui_dist` rebuilt so the launchd server (`com.ormah.server.dev`) serves the degree-sized graph. (Do NOT start a server manually — the launchd job owns the dev server; a hard-refresh on http://localhost:8787 picks up the new bundle.)

---

## Notes for the implementer

- **Run all tests from `ui/`**, not the repo root: `cd ui && npx vitest run <path>`.
- **Connection count = UNIQUE NEIGHBOURS, not edge degree (council R2, Codex — verified).** The graph is a directed **multigraph** (`new Graph({ multi: true })`) and the backend PK is `(source_id, target_id, edge_type)`, so a single pair of nodes can have **parallel edges** (e.g. `supports` + `defines`). Measured on the live graph: **19.8% of pairs carry >1 edge** (up to 3), so `graph.degree(id)` over-counts connections by up to +7 vs distinct neighbours. Use **`graph.neighbors(id).length`** (graphology returns the set of unique adjacent nodes, in+out, deduped) everywhere size is computed — NOT `graph.degree()`, `inDegree`, or `outDegree`. The "connection count" the feature name refers to is *how many distinct memories this one links to*, which is exactly unique neighbours.
- **`access_count` stays on the node payload** (`MemoryNode.access_count`); we only stop using it for *size*. Do not remove the field.
- **Self floor:** the `self` node must never be smaller than 3.5, even at degree 0. This is in `displayNodeSize`, already covered by the existing test.

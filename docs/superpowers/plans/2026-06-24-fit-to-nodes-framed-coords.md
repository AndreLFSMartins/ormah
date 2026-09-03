# fitToNodes Framed-Coordinate Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the graph-view bug where clicking a space in the legend blanks the canvas, by making `fitToNodes` operate in sigma's framed (normalized) coordinate space instead of raw graphology coordinates.

**Architecture:** Extract the private `fitToNodes` helper out of `GraphView.tsx` into a focused, unit-testable module `fit.ts`. Replace its raw-coordinate bbox (`graph.getNodeAttribute(id,"x")`) with framed coordinates from `renderer.getNodeDisplayData(id)` — the same space the sigma camera and the working `focusNode` handler already use. Compute the zoom ratio relatively via sigma's own `viewportToFramedGraph` conversion. Redesign the ratio so focus **fits the selection** (zoom in OR out) capped by a max-zoom-in floor — which makes the old `forceFit` hack obsolete.

**Tech Stack:** TypeScript, sigma.js v3.0.3, graphology, vitest (arithmetic unit tests — the deterministic gate), pytest-playwright (manual real-sigma smoke check).

**Root cause (verified):** `GraphView.tsx:60-82`. `fitToNodes` builds the bbox from raw graphology x/y (post-FA2, e.g. -500..500) and feeds the centroid to `camera.animate({x,y})`. Sigma's camera operates in `framedGraph` space (graph min→0, max→1, aspect preserved). For the whole graph the raw centroid ≈ origin ≈ framed center, so it works by accident; for a single space with an off-center centroid the camera flies outside [0,1] and zooms in → empty canvas. Confirmed by: (1) Playwright screenshots (space focus → black screen), (2) sigma official docs on the `framedGraph` system, (3) A/B control — `focusNode` uses `getNodeDisplayData` (framed) and centers correctly on the same data.

**Testing strategy (Council, 3 rounds):** the **deterministic gate is the `fit.ts` arithmetic unit tests** (Task 3) — they verify the algebra of `fitToNodes` (framed-centroid selection, r0-cancellation, per-axis spans, floor, rAF defer) against a simple affine fake. They do NOT model sigma's real `matrixFromCamera`/`correctionRatio` pipeline. Task 4 is a **hardened manual real-sigma smoke check** — it drives the live app (real WebGL sigma) and asserts the focused space's node bbox actually lands inside the viewport. It is **not** a CI gate: a true CI gate would need a seeded-graph fixture + dev server wired into the pipeline (deferred follow-up). Across 3 rounds × 2 peers the fix (Tasks 1–3) was never challenged; the debate converged on Task 4's rigor. See `.council/council-result.md`.

---

### Task 1: Extract `fitToNodes` into a testable module (pure refactor)

**Files:**
- Create: `ui/src/components/fit.ts`
- Modify: `ui/src/components/GraphView.tsx` (remove inline `FIT_PADDING_RATIO` + `fitToNodes` at lines 56-82; import from `./fit`)

- [ ] **Step 1: Create `fit.ts` with the helper moved verbatim**

```typescript
import type Graph from "graphology";
import type Sigma from "sigma";

// ─── fitToNodes helper (Council A3) ──────────────────────────────────────────
// Mirrors cy.fit(collection, 120) + clamp logic using sigma camera + framed coords.
export const FIT_PADDING_RATIO = 0.15; // ~120px padding at default 900px viewport height

export function fitToNodes(renderer: Sigma, graph: Graph, ids: string[], forceFit = false): void {
  if (!ids.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const id of ids) {
    if (!graph.hasNode(id)) continue;
    const x = graph.getNodeAttribute(id, "x") as number;
    const y = graph.getNodeAttribute(id, "y") as number;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  if (!isFinite(minX)) return;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const camera = renderer.getCamera();
  const { width, height } = renderer.getDimensions();
  const spanX = Math.max(maxX - minX, 1e-6), spanY = Math.max(maxY - minY, 1e-6);
  const graphToView = Math.max(spanX / width, spanY / height);
  const fitRatio = graphToView * (1 + FIT_PADDING_RATIO);
  const ratio = forceFit ? Math.max(fitRatio, 0.25) : Math.min(camera.ratio, Math.max(fitRatio, 0.25));
  camera.animate({ x: cx, y: cy, ratio }, { duration: 400 });
}
```

- [ ] **Step 2: Remove the inline copy from `GraphView.tsx`**

Delete lines 56-82 (the `// ─── fitToNodes helper` block, `FIT_PADDING_RATIO`, and the function). Add to the import block near the top (next to `import { focusFitIds } from "./legendFit";`):

```typescript
import { fitToNodes } from "./fit";
```

- [ ] **Step 3: Typecheck + build to confirm the refactor is behavior-neutral**

Run: `cd ui && npx tsc --noEmit && npm run build`
Expected: PASS (no type errors; `fitToNodes` resolves from `./fit`; all call sites still compile).

- [ ] **Step 4: Run existing unit tests (no regressions)**

Run: `cd ui && npx vitest run`
Expected: PASS (same count as before).

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/fit.ts ui/src/components/GraphView.tsx
git commit -m "refactor(graph): extract fitToNodes into fit.ts (no behavior change)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Failing test — bbox center must come from framed display coords, not raw attributes

**Files:**
- Create: `ui/src/components/fit.test.ts`

This is the regression test. The fake renderer returns **framed** coords from `getNodeDisplayData`, but the graphology node attributes hold the **raw** coords. The current (Task 1) implementation reads raw attributes, animates to ~500, and the assertion that the camera centers on the framed centroid FAILS.

**These are arithmetic tests.** The fake's `viewportToFramedGraph` is a deliberately simple affine map whose scale is proportional to `camera.ratio` and whose offset is the pan, with separate per-axis scales (`kx`/`ky`). They assert the algebra of `fitToNodes` (chiefly that `r0` cancels). They are NOT a model of sigma's real `matrixFromCamera`/`correctionRatio` pipeline; that fidelity is the job of the Task 4 smoke check.

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi } from "vitest";
import Graph from "graphology";
import type Sigma from "sigma";
import { fitToNodes } from "./fit";

type Pt = { x: number; y: number };
type Framed = Record<string, Pt>;

interface FakeOpts {
  ratio?: number;   // camera.ratio (r0)
  width?: number;
  height?: number;
  camX?: number;    // camera pan, framed coords
  camY?: number;
  kx?: number;      // pixels-per-framed-unit at ratio 1, per axis
  ky?: number;
}

// ARITHMETIC fake (NOT a sigma model): viewport→framed is affine, scale ∝ ratio, offset = pan.
function fakeRenderer(framed: Framed, o: FakeOpts = {}) {
  const ratio = o.ratio ?? 1;
  const width = o.width ?? 1000, height = o.height ?? 1000;
  const camX = o.camX ?? 0, camY = o.camY ?? 0;
  const kx = o.kx ?? 1000, ky = o.ky ?? 1000;
  const animate = vi.fn();
  const renderer = {
    getNodeDisplayData: (id: string) => framed[id],
    getCamera: () => ({ ratio, animate }),
    getDimensions: () => ({ width, height }),
    viewportToFramedGraph: (p: Pt) => ({
      x: camX + ((p.x - width / 2) * ratio) / kx,
      y: camY + ((p.y - height / 2) * ratio) / ky,
    }),
  } as unknown as Sigma;
  return { renderer, animate };
}

function rawGraph(raw: Framed): Graph {
  const g = new Graph();
  for (const [id, { x, y }] of Object.entries(raw)) g.addNode(id, { x, y });
  return g;
}

describe("fitToNodes", () => {
  it("centers the camera on the FRAMED centroid, not the raw graphology centroid", () => {
    const framed = { a: { x: 0.2, y: 0.4 }, b: { x: 0.4, y: 0.6 } };
    const raw = { a: { x: 480, y: 510 }, b: { x: 520, y: 540 } };
    const { renderer, animate } = fakeRenderer(framed);
    fitToNodes(renderer, rawGraph(raw), ["a", "b"]);

    expect(animate).toHaveBeenCalledTimes(1);
    const target = animate.mock.calls[0][0] as { x: number; y: number; ratio: number };
    expect(target.x).toBeCloseTo(0.3, 5); // framed centroid; raw would be 500
    expect(target.y).toBeCloseTo(0.5, 5);
  });
});
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `cd ui && npx vitest run fit.test.ts`
Expected: FAIL — `target.x` is `500` (raw centroid), not `0.3`.

- [ ] **Step 3: Commit the failing test**

```bash
git add ui/src/components/fit.test.ts
git commit -m "test(graph): failing test — fitToNodes uses raw coords instead of framed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Fix `fitToNodes` — framed coords, fit-with-floor ratio, rAF defer, drop `forceFit`

**Files:**
- Modify: `ui/src/components/fit.ts`
- Modify: `ui/src/components/GraphView.tsx` (drop the `forceFit` argument at the legend-focus call site)
- Test: `ui/src/components/fit.test.ts`

**Design decisions (Council):** (1) fit the selection (zoom in or out) with a max-zoom-in floor, replacing the `Math.min(camera.ratio, …)` clamp that blocked zoom-out — this subsumes and removes `forceFit`. (2) If a legend click fires before nodes have display data, retry a few frames before giving up.

- [ ] **Step 1: Replace `fit.ts` with the framed-coordinate, fit-with-floor, rAF-defer version**

```typescript
import type Graph from "graphology";
import type Sigma from "sigma";

export const FIT_PADDING_RATIO = 0.15; // ~15% padding around the fitted bbox
export const MIN_FIT_RATIO = 0.25;     // max zoom-in cap (smallest camera ratio); preserves 0.25
const MAX_FIT_RETRIES = 3;             // retry frames when nodes aren't painted yet

// Frame the camera on a set of nodes, in sigma's FRAMED (normalized) coordinate space — the
// same space the camera and getNodeDisplayData use. Building the bbox from raw graphology x/y
// would send the camera outside [0,1] and blank the canvas; see fit.test.ts. Fits the selection
// (zooms in OR out) with a max-zoom-in floor.
//
// NOTE: the relative-ratio step assumes camera.angle === 0 (no rotation). This app exposes no
// camera-rotation control, so angle is always 0; under rotation the TL→BR span would skew.
export function fitToNodes(renderer: Sigma, graph: Graph, ids: string[], _retries = 0): void {
  if (!ids.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  let found = 0;
  for (const id of ids) {
    if (!graph.hasNode(id)) continue;
    const d = renderer.getNodeDisplayData(id); // framed coords; undefined if not rendered yet
    if (!d) continue;
    found++;
    minX = Math.min(minX, d.x); maxX = Math.max(maxX, d.x);
    minY = Math.min(minY, d.y); maxY = Math.max(maxY, d.y);
  }
  if (!found) {
    // Legend clicked before paint: retry a few frames, then give up.
    if (_retries < MAX_FIT_RETRIES && typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => fitToNodes(renderer, graph, ids, _retries + 1));
    }
    return;
  }
  if (!isFinite(minX)) return;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const camera = renderer.getCamera();
  const { width, height } = renderer.getDimensions();

  // The framed→viewport transform is linear in framed coords for a fixed camera, so the framed
  // span currently visible is proportional to camera.ratio and independent of the pan. Measure
  // it via sigma's own conversion at the current ratio (per-axis), then scale the ratio so the
  // target span fills the viewport.
  const tl = renderer.viewportToFramedGraph({ x: 0, y: 0 });
  const br = renderer.viewportToFramedGraph({ x: width, y: height });
  const shownX = Math.max(Math.abs(br.x - tl.x), 1e-9);
  const shownY = Math.max(Math.abs(br.y - tl.y), 1e-9);
  const r0 = camera.ratio;

  const spanX = Math.max(maxX - minX, 1e-6) * (1 + FIT_PADDING_RATIO);
  const spanY = Math.max(maxY - minY, 1e-6) * (1 + FIT_PADDING_RATIO);
  // r0 cancels (shownX ∝ r0) → absolute ratio that frames the bbox, correct at any starting zoom.
  const fitRatio = Math.max((spanX * r0) / shownX, (spanY * r0) / shownY);

  const ratio = Math.max(fitRatio, MIN_FIT_RATIO); // fit (in OR out), never zoom in past the floor
  camera.animate({ x: cx, y: cy, ratio }, { duration: 400 });
}
```

- [ ] **Step 2: Update the legend-focus call site in `GraphView.tsx`**

Drop the `forceFit` argument (find `fitToNodes(r, g, focusFitIds(g, next), next === null)` in `focusLegend`):

```typescript
          fitToNodes(r, g, focusFitIds(g, next));
```

`highlightNodes` already calls `fitToNodes(r, g, present)` with no extra arg. Update the nearby comment to: `// Fit on focus AND on clear: focusFitIds returns the whole graph when next === null.`

- [ ] **Step 3: Run the regression test to verify it PASSES**

Run: `cd ui && npx vitest run fit.test.ts`
Expected: PASS — `target.x` ≈ 0.3, `target.y` ≈ 0.5.

- [ ] **Step 4: Add arithmetic assertions (above-floor r0-cancel, zoom-out, pan, per-axis kx≠ky, floor, rAF defer)**

Append inside the `describe("fitToNodes", ...)` block:

```typescript
  it("computes the SAME absolute fitRatio above the floor regardless of starting zoom", () => {
    // Selection spans 0.5 framed (0.25..0.75). kx=ky=1000, width=1000 → shownX = r0.
    // fitRatio = spanX*1.15*r0 / r0 = 0.5*1.15 = 0.575 (ABOVE the 0.25 floor → not saturated).
    const sel = { a: { x: 0.25, y: 0.25 }, b: { x: 0.75, y: 0.75 } };
    const raw = { a: { x: 0, y: 0 }, b: { x: 1, y: 1 } };
    for (const r0 of [0.25, 1, 2]) {
      const { renderer, animate } = fakeRenderer(sel, { ratio: r0 });
      fitToNodes(renderer, rawGraph(raw), ["a", "b"]);
      const ratio = (animate.mock.calls[0][0] as { ratio: number }).ratio;
      expect(ratio).toBeCloseTo(0.575, 5); // identical across r0 → r0 truly cancels
    }
  });

  it("zooms OUT to fit a wide selection even when starting zoomed-in", () => {
    const sel = { a: { x: 0.1, y: 0.1 }, b: { x: 0.9, y: 0.9 } };
    const { renderer, animate } = fakeRenderer(sel, { ratio: 0.05 });
    fitToNodes(renderer, rawGraph({ a: { x: 0, y: 0 }, b: { x: 1, y: 1 } }), ["a", "b"]);
    const ratio = (animate.mock.calls[0][0] as { ratio: number }).ratio;
    expect(ratio).toBeCloseTo(0.92, 5); // 0.8*1.15; zoomed OUT from 0.05
    expect(ratio).toBeGreaterThan(0.05);
  });

  it("is independent of camera pan", () => {
    const sel = { a: { x: 0.25, y: 0.25 }, b: { x: 0.75, y: 0.75 } };
    const raw = { a: { x: 0, y: 0 }, b: { x: 1, y: 1 } };
    const centered = fakeRenderer(sel, { camX: 0, camY: 0 });
    const panned = fakeRenderer(sel, { camX: 5, camY: -3 });
    fitToNodes(centered.renderer, rawGraph(raw), ["a", "b"]);
    fitToNodes(panned.renderer, rawGraph(raw), ["a", "b"]);
    const c = centered.animate.mock.calls[0][0] as { x: number; ratio: number };
    const p = panned.animate.mock.calls[0][0] as { x: number; ratio: number };
    expect(p.x).toBeCloseTo(c.x, 6);       // center = framed centroid, pan-independent
    expect(p.ratio).toBeCloseTo(c.ratio, 6);
  });

  it("uses per-axis spans (different kx/ky → binding axis wins)", () => {
    // width=1600,height=900; kx=1000,ky=600. shownX = 1600/1000 = 1.6; shownY = 900/600 = 1.5.
    // spanX = 0.2*1.15 = 0.23; spanY = 0.8*1.15 = 0.92.
    // fitRatio = max(0.23/1.6, 0.92/1.5) = max(0.14375, 0.61333) = 0.61333 (Y binds).
    const sel = { a: { x: 0.4, y: 0.1 }, b: { x: 0.6, y: 0.9 } };
    const { renderer, animate } = fakeRenderer(sel, { width: 1600, height: 900, kx: 1000, ky: 600 });
    fitToNodes(renderer, rawGraph({ a: { x: 0, y: 0 }, b: { x: 1, y: 1 } }), ["a", "b"]);
    const ratio = (animate.mock.calls[0][0] as { ratio: number }).ratio;
    expect(ratio).toBeCloseTo(0.6133, 3);
  });

  it("clamps a single-node selection to the max-zoom-in floor", () => {
    const { renderer, animate } = fakeRenderer({ a: { x: 0.5, y: 0.5 } });
    fitToNodes(renderer, rawGraph({ a: { x: 0, y: 0 } }), ["a"]);
    const ratio = (animate.mock.calls[0][0] as { ratio: number }).ratio;
    expect(ratio).toBeCloseTo(0.25, 6); // MIN_FIT_RATIO
  });

  it("retries on the next frame(s) when no node has display data yet, then fits", () => {
    let cb: (() => void) | null = null;
    vi.stubGlobal("requestAnimationFrame", (fn: () => void) => { cb = fn; return 1; });
    const framed: Framed = {};
    const { renderer, animate } = fakeRenderer(framed);
    fitToNodes(renderer, rawGraph({ a: { x: 0, y: 0 } }), ["a"]);
    expect(animate).not.toHaveBeenCalled();
    expect(cb).toBeTypeOf("function");
    framed.a = { x: 0.5, y: 0.5 };  // nodes now rendered
    cb!();                          // next frame retry
    expect(animate).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("gives up after MAX_FIT_RETRIES without ever animating", () => {
    let cb: (() => void) | null = null;
    vi.stubGlobal("requestAnimationFrame", (fn: () => void) => { cb = fn; return 1; });
    const { renderer, animate } = fakeRenderer({}); // never any display data
    fitToNodes(renderer, rawGraph({ a: { x: 0, y: 0 } }), ["a"]);
    for (let i = 0; i < 5 && cb; i++) { const c = cb; cb = null; c(); } // drain retries
    expect(animate).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
```

- [ ] **Step 5: Run the full `fit.test.ts` suite**

Run: `cd ui && npx vitest run fit.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 6: Typecheck, build, and run the whole UI test suite**

Run: `cd ui && npx tsc --noEmit && npx vitest run && npm run build`
Expected: PASS across the board.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/fit.ts ui/src/components/fit.test.ts ui/src/components/GraphView.tsx
git commit -m "fix(graph): frame legend/space focus in framed coords so nodes stop vanishing

fitToNodes built its bbox from raw graphology coordinates and fed the
centroid to the sigma camera, which operates in framed (normalized) space.
For an off-center space the camera flew outside [0,1] and blanked the
canvas. Build the bbox from getNodeDisplayData (framed) and scale the ratio
via viewportToFramedGraph, matching the working focusNode handler. Fit the
selection (zoom in or out) with a max-zoom-in floor; retry a few frames when
nodes are not painted yet; drop the now-obsolete forceFit flag.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Hardened manual real-sigma smoke verification (NOT a CI gate)

**This is a MANUAL real-sigma smoke check, not a CI regression gate.** The deterministic gate is Task 3's `fit.test.ts`. A true CI gate would need a seeded-graph fixture + dev server in the pipeline — deferred follow-up (see Notes). This step verifies, against the live app (real WebGL sigma), that focusing a space frames it, using a **bbox-containment** oracle (not an arbitrary fraction).

**Files:**
- Create: `ui/playwright/test_graph_focus.py`
- Modify: `ui/src/components/GraphView.tsx` (add a scoped `data-testid` to the SPACES legend rows)

**Harness facts (verified, Council):**
- `GraphView.tsx:373-376` already exposes `window.__ormahSigma` only under `import.meta.env.DEV` (cleanup at `:470-472`). Do NOT re-add it. `make restart` runs `vite build` (production, DEV=false → no handle), so this runs against the **Vite dev server** (`make dev`, `:5173`).
- `getNodeDisplayData(id)` returns **framed** coords; convert with `framedGraphToViewport` (verified `sigma.d.ts:167`), relative to the container (full canvas) → no `getBoundingClientRect` needed. The existing `test_graph_drag.py` uses `graphToViewport` on display data — a latent inconsistency in that test; `framedGraphToViewport` is the documented-correct composition.
- `camera.isAnimated()` exists (`camera.d.ts:30`) → use it to wait, instead of fixed sleeps.

- [ ] **Step 1: Add a scoped test id to the SPACES legend rows in `GraphView.tsx`**

`get_by_text("council")` is ambiguous (search box, tooltips, node panels). Add a stable id to the space `LegendRow` so the e2e clicks the exact legend row:

```tsx
                          <LegendRow
                            key={sp.name}
                            data-testid={`legend-space-${sp.name}`}
                            active={!legendFocus || (legendFocus.kind === "space" && legendFocus.val === val)}
                            onClick={() => focusLegend("space", val)}
                          >
```

If `LegendRow` does not already forward arbitrary DOM props, thread `data-testid` through to its root element (e.g. add `"data-testid"?: string` to its props and spread it onto the rendered `<div>`).

- [ ] **Step 2: Write the hardened smoke test**

```python
"""Manual real-sigma smoke check: focusing a space frames it (no blank canvas).

NOT a CI gate (depends on the live dev server + the user's live graph). The
deterministic gate is ui/src/components/fit.test.ts. Oracle: the focused space's
node bounding box lands inside the viewport (with tolerance). Also exercises the
zoom-OUT path by zooming in first and asserting the camera ratio actually dropped.

Start the dev server first: `make dev` (backend :8787 + Vite :5173, DEV → __ormahSigma).
"""
import os
import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ORMAH_UI_URL", "http://localhost:5173")
TARGET_SPACE = os.environ.get("ORMAH_FOCUS_SPACE", "council")
TOL = 0.05  # 5% of viewport tolerance for bbox containment


def _space_bbox_in_viewport(page, space: str):
    # Returns {inside: bool, frac: float, count: int} for the target space after focus.
    return page.evaluate(
        """([space, tol]) => {
            const sig = window.__ormahSigma;
            if (!sig) return { inside: false, frac: -1, count: -1 };
            const g = sig.getGraph();
            const { width, height } = sig.getDimensions();
            const mx = width * tol, my = height * tol;
            let count = 0, inView = 0;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            g.forEachNode((id, attr) => {
                if ((attr.space || '') !== space) return;
                count++;
                const p = sig.framedGraphToViewport(sig.getNodeDisplayData(id));
                minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
                minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
                if (p.x >= 0 && p.x <= width && p.y >= 0 && p.y <= height) inView++;
            });
            if (!count) return { inside: false, frac: -1, count: 0 };
            const inside = minX >= -mx && maxX <= width + mx && minY >= -my && maxY <= height + my;
            return { inside, frac: inView / count, count };
        }""",
        [space, TOL],
    )


def _wait_settled(page):
    page.wait_for_function(
        "() => window.__ormahSigma && window.__ormahSigma.getGraph().order > 0", timeout=20000)
    page.wait_for_timeout(4500)  # FA2 settleMs=4000 + margin
    page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)


@pytest.mark.integration
def test_space_focus_frames_the_space():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=20000)
        _wait_settled(page)

        # State 1: focus at default zoom (scoped click on the exact legend row).
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()
        page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)
        s1 = _space_bbox_in_viewport(page, TARGET_SPACE)
        assert s1["count"] > 0, f"DEV handle missing or space '{TARGET_SPACE}' empty (count={s1['count']})"
        assert s1["inside"], f"[default] '{TARGET_SPACE}' bbox not contained (frac={s1['frac']:.0%})"

        # State 2: zoom IN, PROVE we zoomed in, then refocus and assert it zooms OUT to fit.
        ratio_focused = page.evaluate("() => window.__ormahSigma.getCamera().ratio")
        page.evaluate("() => window.__ormahSigma.getCamera().animatedZoom({ duration: 200 })")
        page.wait_for_function(
            f"() => {{ const c = window.__ormahSigma.getCamera(); return !c.isAnimated() && c.ratio < {ratio_focused} * 0.6; }}",
            timeout=10000,
        )
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()  # clear
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()  # focus again
        page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)
        s2 = _space_bbox_in_viewport(page, TARGET_SPACE)
        ratio_refocused = page.evaluate("() => window.__ormahSigma.getCamera().ratio")
        browser.close()

        assert s2["inside"], f"[after zoom-in] '{TARGET_SPACE}' bbox not contained (frac={s2['frac']:.0%})"
        assert ratio_refocused > ratio_focused * 0.6, "refocus did not zoom back out to fit the space"
```

- [ ] **Step 3: Start the dev server and run the smoke check**

Run:
```bash
make dev   # backend :8787 + Vite :5173 (DEV → __ormahSigma)
# in another shell:
cd ui && uv run --with pytest-playwright pytest playwright/test_graph_focus.py -m integration -v
```
Expected: PASS — `council` bbox contained at default AND after zoom-in; refocus zooms back out. (Pre-fix: blank / bbox far outside.)

- [ ] **Step 4: Confirm the production bundle does NOT leak the handle**

Run: `cd ui && npx vite build && grep -c "__ormahSigma = renderer" dist/assets/*.js || echo "0 (DEV-gated, not in prod)"`
Expected: 0 — the handle stays behind `import.meta.env.DEV`.

- [ ] **Step 5: Visual spot-check + dispersed-space honesty**

Re-run with `ORMAH_FOCUS_SPACE=files` → PASS. Then manually focus `AndreMartins` in the dev UI: confirm it is **no longer black** but frames ~the whole graph (perceptual focus for dispersed spaces awaits the cohesion work). Save a screenshot to `docs/superpowers/plans/`.

- [ ] **Step 6: Commit**

```bash
git add ui/playwright/test_graph_focus.py ui/src/components/GraphView.tsx
git commit -m "test(graph): manual real-sigma smoke — space focus frames the space (bbox containment)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Close-out

- [ ] **Step 1: Update memory**

Update `ormah-graph-space-cohesion-bug` memory: the "focus loses nodes" symptom is a `fitToNodes` coordinate-space bug (raw vs framed), now fixed — distinct from the (still-open, optional) per-space *cohesion* layout work. Note dispersed spaces (AndreMartins ~98%) still frame ~the whole graph until cohesion lands.

- [ ] **Step 2: Final verification summary**

Confirm and report: `fit.test.ts` 9/9 green, full UI suite green, `tsc --noEmit` clean, build clean, and the manual real-sigma smoke check green (bbox contained at both camera states) for two non-dispersed spaces.

---

## Notes / Out of scope

- **Per-space cohesion ("galaxies", approach-C):** explicitly NOT in scope. This plan fixes the camera/coordinate bug only. For a heavily-dispersed space the focus correctly frames its bbox, which is ~the whole graph — the *perceptual* "nothing focused" feeling there is the cohesion problem (26.8% cross-space edges, global FA2), tracked in `UPSTREAM_ISSUE_graph_space_layout_cohesion.md` and `[[ormah-graph-space-cohesion-bug]]`.
- **e2e is a manual smoke check, not a CI gate:** the deterministic gate is `fit.test.ts` (arithmetic). Wiring a real CI gate would need a **seeded-graph fixture** (deterministic data) + the dev server in the pipeline + a `make test-ui-e2e` target — a separate follow-up, deferred. The smoke check depends on the live dev server and the user's live graph.
- **Unit vs real-sigma split:** unit tests are arithmetic; real-sigma fidelity (`matrixFromCamera`/`correctionRatio`/padding) is exercised only by the Task 4 smoke check. Sigma is WebGL and does not run in jsdom (cf. `forceLayout` `NOOP_STATIC`); a browserless contract would have to import sigma's `matrixFromCamera`/`getCorrectionRatio` to compute expected spans — not attempted.
- **Camera rotation (`angle != 0`):** the relative-ratio step assumes `angle == 0`. This app has no rotation control; documented in `fit.ts`. If rotation is ever added, project all four bbox corners instead of the TL→BR span [Codex].
- **`forceFit` removed:** the redesigned fit zooms in OR out with a floor, so the legend-clear path no longer needs a flag — `focusFitIds` returning the whole graph already frames everything.
- **`focusNode` keeps `ratio: 0.4`:** single-node search-focus is unchanged; intentionally a fixed zoom, not a bbox fit.
- This UI lives only in `local-main` (Beta) and never goes upstream — see `[[ormah-local-main-beta-model]]`.

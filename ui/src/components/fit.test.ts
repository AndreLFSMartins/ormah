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
    for (let i = 0; i < 5 && cb; i++) { const c = cb as () => void; cb = null; c(); } // drain retries
    expect(animate).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

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

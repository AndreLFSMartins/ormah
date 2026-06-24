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

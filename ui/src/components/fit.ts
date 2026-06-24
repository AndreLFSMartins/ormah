import type Graph from "graphology";
import type Sigma from "sigma";

// ─── fitToNodes helper (Council A3) ──────────────────────────────────────────
// Mirrors cy.fit(collection, 120) + clamp logic using graphology positions and sigma camera.
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

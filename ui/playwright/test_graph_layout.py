"""Visual layout test: after FA2 settles, the layout is organic and NOT a grid.

Run the app first: `make dev` (backend :8787 + vite dev :5173 — DEV handle is exposed only on the dev build).
Then: uv run --with playwright python ui/playwright/test_graph_layout.py
"""
import math
import statistics
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def nearest_neighbor_dists(points):
    """For each point, the distance to its closest other point."""
    out = []
    for i, (x, y) in enumerate(points):
        best = math.inf
        for j, (ox, oy) in enumerate(points):
            if i == j:
                continue
            d = math.hypot(x - ox, y - oy)
            if d < best:
                best = d
        if math.isfinite(best):
            out.append(best)
    return out


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=30000)
        page.wait_for_timeout(6000)  # let FA2 settle past its window

        data = page.evaluate(
            """() => {
              const g = window.__ormahGraph;
              if (!g) return { error: 'no graph handle (run the DEV server)' };
              const pts = [];
              g.forEachNode((id, a) => { pts.push([a.x, a.y]); });
              return { pts, order: g.order };
            }"""
        )
        page.screenshot(path="/tmp/ormah_sigma_layout.png")
        browser.close()

    if data.get("error"):
        print("FAIL:", data["error"]); return 1
    pts = data["pts"]
    n = len(pts)
    if n == 0:
        print("FAIL: empty graph"); return 1

    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    # 1) Layout ran: finite, spread positions (not all stacked at origin).
    if not all(math.isfinite(v) for v in xs + ys):
        print("FAIL: non-finite positions"); return 1
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    if span_x <= 0 or span_y <= 0:
        print("FAIL: degenerate span", span_x, span_y); return 1

    # 2) NOT a regular grid. A packed grid has near-constant nearest-neighbor
    #    distance (coefficient of variation ~0) and an aspect ratio ~1 with
    #    evenly spaced lattice points. An organic force layout has variable NN
    #    distances (clusters dense, periphery sparse) -> CoV well above 0.
    if n >= 8:
        nn = nearest_neighbor_dists(pts)
        mean_nn = statistics.fmean(nn)
        cov = (statistics.pstdev(nn) / mean_nn) if mean_nn > 0 else 0.0
        print(f"nn_cov={cov:.3f} nodes={n} span=({span_x:.0f}x{span_y:.0f})")
        if cov < 0.25:
            print("FAIL: nearest-neighbor distances too uniform - looks like a grid")
            return 1
    else:
        print(f"INFO: <8 nodes; skipped grid check (nodes={n})")

    print(f"PASS: organic layout, span=({span_x:.0f}x{span_y:.0f}), nodes={n}")
    print("screenshot: /tmp/ormah_sigma_layout.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())

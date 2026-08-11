### Task 7: Playwright visual test (Python)

Proves the core spec claim: after the FA2 settle, the graph is an **organic, non-grid topological layout** in WebGL. Uses **Python Playwright** via the uv tool (per machine policy — never Node Playwright). Reads laid-out positions from a DEV-only debug handle on `window`.

> **Council H2:** the layout is **pure organic FA2 (option A)** — it separates by *topology* (edges), NOT by `space`. So the test must NOT assert per-space cluster separation (that would fail on a correct topological layout). It asserts: layout ran + spread, and the result is **not a regular grid** (the original losango defect). Per-space galaxies are deferred (option B); there is no space-separation success criterion.

**Files:**
- Modify: `ui/src/components/GraphView.tsx` (add the DEV-only debug handle)
- Create: `ui/playwright/test_graph_layout.py`

- [ ] **Step 1: Expose a read-only debug handle (DEV only)**

In the sigma mount effect (Task 6.1), right after `graphRef.current = graph;`, add a DEV-gated handle and remove it in the effect cleanup (Council L1 — never leak it into production):

```typescript
// Debug handle for the visual test — DEV only, removed on unmount.
if (import.meta.env.DEV) {
  (window as unknown as { __ormahGraph?: Graph }).__ormahGraph = graph;
}
```

In the effect's cleanup function (where the renderer/layout are killed), add:

```typescript
if (import.meta.env.DEV) {
  delete (window as unknown as { __ormahGraph?: Graph }).__ormahGraph;
}
```

> Because the handle is DEV-only, the visual test must run against the **Vite dev server** (`npm run dev`, port 5173), not the production build on :8787. The dev server proxies `/ui` to the backend (confirm `ui/vite.config.ts` `server.proxy`; if absent, run `make dev` so backend :8787 + vite :5173 are both up and the fetch resolves).

- [ ] **Step 2: Write the visual test (organic, non-grid)**

Create `ui/playwright/test_graph_layout.py`:

```python
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
        page.goto(URL, wait_until="networkidle")
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
    #    distances (clusters dense, periphery sparse) → CoV well above 0.
    if n >= 8:
        nn = nearest_neighbor_dists(pts)
        mean_nn = statistics.fmean(nn)
        cov = (statistics.pstdev(nn) / mean_nn) if mean_nn > 0 else 0.0
        print(f"nn_cov={cov:.3f} nodes={n} span=({span_x:.0f}x{span_y:.0f})")
        if cov < 0.25:
            print("FAIL: nearest-neighbor distances too uniform — looks like a grid")
            return 1
    else:
        print(f"INFO: <8 nodes; skipped grid check (nodes={n})")

    print(f"PASS: organic layout, span=({span_x:.0f}x{span_y:.0f}), nodes={n}")
    print("screenshot: /tmp/ormah_sigma_layout.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write the drag test (Council M5)**

Create `ui/playwright/test_graph_drag.py` — asserts a node moves under drag and the layout re-heats (settles) after release:

```python
"""Drag test: dragging a node moves it; releasing re-heats FA2 so the graph keeps settling.

Run `make dev` first. Then: uv run --with playwright python ui/playwright/test_graph_drag.py
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def first_node_screen_pos(page):
    return page.evaluate(
        """() => {
          const g = window.__ormahGraph;
          const s = window.__ormahSigma;          // exposed alongside the graph (DEV only)
          if (!g || !s) return null;
          const id = g.nodes()[0];
          const p = s.graphToViewport(s.getNodeDisplayData(id));
          return { id, x: p.x, y: p.y };
        }"""
    )


def graph_pos(page, node_id):
    return page.evaluate(
        "(id) => { const g = window.__ormahGraph; return { x: g.getNodeAttribute(id,'x'), y: g.getNodeAttribute(id,'y') }; }",
        node_id,
    )


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("canvas", timeout=30000)
        page.wait_for_timeout(6000)

        start = first_node_screen_pos(page)
        if not start:
            print("FAIL: no graph/sigma handle (run the DEV server)"); browser.close(); return 1
        before = graph_pos(page, start["id"])

        page.mouse.move(start["x"], start["y"])
        page.mouse.down()
        page.mouse.move(start["x"] + 180, start["y"] + 120, steps=10)
        page.mouse.up()
        page.wait_for_timeout(500)
        after_release = graph_pos(page, start["id"])
        page.wait_for_timeout(2500)          # reheat settle window
        settled = graph_pos(page, start["id"])
        browser.close()

    moved = abs(after_release["x"] - before["x"]) + abs(after_release["y"] - before["y"])
    if moved < 1.0:
        print(f"FAIL: node did not move under drag (delta={moved:.2f})"); return 1
    # Council A6: re-heat means the sim resumes after release, so positions keep
    # changing. If the post-settle position is identical to the immediate
    # post-release position, reheat did NOT fire — that is a FAILURE, not a warning.
    reheated = abs(settled["x"] - after_release["x"]) + abs(settled["y"] - after_release["y"])
    print(f"moved={moved:.1f} reheated_delta={reheated:.3f}")
    if reheated <= 0.001:
        print("FAIL: layout did not re-heat after release (reheat() did not resume the sim)")
        return 1
    print("PASS: node dragged and layout re-heated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> The drag test needs the sigma instance too. In the same DEV block (Step 1) also expose `(window as ...).__ormahSigma = renderer;` after the renderer is created, and delete it in cleanup.

- [ ] **Step 4: Run the app (dev), then both tests**

```bash
make dev   # backend :8787 + vite dev :5173 (DEV handle exposed)
uv run --with playwright python ui/playwright/test_graph_layout.py
uv run --with playwright python ui/playwright/test_graph_drag.py
```

Expected: layout test prints `PASS: organic layout …` with `nn_cov ≥ 0.25` (or INFO skip for tiny stores); drag test prints `PASS: node dragged and layout responded`. Inspect `/tmp/ormah_sigma_layout.png` — organic, no grid.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/GraphView.tsx ui/playwright/test_graph_layout.py ui/playwright/test_graph_drag.py
git commit -m "test(ui): Playwright organic-layout (non-grid) + node-drag tests"
```

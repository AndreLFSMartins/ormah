### Task 7: Playwright visual test (Python)

Proves the core spec claim: after the FA2 settle, the graph forms organic clusters (not a grid), in WebGL. Uses **Python Playwright** via the uv tool (per machine policy — never Node Playwright). Reads laid-out positions from a debug handle on `window`.

**Files:**
- Modify: `ui/src/components/GraphView.tsx` (add the debug handle)
- Create: `ui/playwright/test_graph_layout.py`

- [ ] **Step 1: Expose a read-only debug handle**

In the sigma mount effect (Task 6.1), right after `graphRef.current = graph;`, add:

```typescript
// Debug handle for the visual test (read-only reference to the laid-out graph).
(window as unknown as { __ormahGraph?: Graph }).__ormahGraph = graph;
```

Rebuild: `( cd ui && npm run build )`.

- [ ] **Step 2: Write the visual test**

Create `ui/playwright/test_graph_layout.py`:

```python
"""Visual layout test: after FA2 settles, nodes form organic clusters, not a grid.

Run the app first (single endpoint): `make restart` (serves built UI on :8787).
Then: uv run --with playwright python ui/playwright/test_graph_layout.py
"""
import math
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:8787"


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
              if (!g) return { error: 'no graph handle' };
              const pos = {};
              g.forEachNode((id, a) => { pos[id] = { x: a.x, y: a.y, space: a.space || '' }; });
              return { pos, order: g.order };
            }"""
        )
        page.screenshot(path="/tmp/ormah_sigma_layout.png")
        browser.close()

    if data.get("error"):
        print("FAIL:", data["error"]); return 1

    pos = data["pos"]
    n = len(pos)
    if n == 0:
        print("FAIL: empty graph"); return 1

    xs = [p["x"] for p in pos.values()]
    ys = [p["y"] for p in pos.values()]
    # 1) Layout actually ran: finite, spread positions (not all stacked at origin).
    if not all(math.isfinite(v) for v in xs + ys):
        print("FAIL: non-finite positions"); return 1
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= 0 or span_y <= 0:
        print("FAIL: degenerate span", span_x, span_y); return 1

    # 2) Cluster separation by space (only when there are >=2 multi-node spaces).
    groups: dict[str, list[dict]] = {}
    for pt in pos.values():
        groups.setdefault(pt["space"], []).append(pt)
    multi = {s: pts for s, pts in groups.items() if len(pts) >= 2}
    if len(multi) >= 2:
        centroids = []
        intra_sum = intra_n = 0.0
        for s, pts in multi.items():
            cx = sum(p["x"] for p in pts) / len(pts)
            cy = sum(p["y"] for p in pts) / len(pts)
            spread = sum(math.hypot(p["x"] - cx, p["y"] - cy) for p in pts) / len(pts)
            centroids.append((cx, cy))
            intra_sum += spread * len(pts); intra_n += len(pts)
        mean_intra = intra_sum / intra_n
        nn = []
        for i, (cx, cy) in enumerate(centroids):
            best = min(
                (math.hypot(cx - ox, cy - oy) for j, (ox, oy) in enumerate(centroids) if j != i),
                default=float("inf"),
            )
            if math.isfinite(best):
                nn.append(best)
        sep_ratio = (sum(nn) / len(nn)) / mean_intra if nn and mean_intra > 0 else 0
        print(f"separationRatio={sep_ratio:.2f} spaces={len(multi)} nodes={n}")
        if sep_ratio < 0.8:
            print("FAIL: spaces not separated (looks packed)"); return 1
    else:
        print(f"INFO: <2 multi-node spaces; skipped separation check (nodes={n})")

    print(f"PASS: layout ran, span=({span_x:.0f}x{span_y:.0f}), nodes={n}")
    print("screenshot: /tmp/ormah_sigma_layout.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the app, then the test**

```bash
make restart   # builds UI + serves on :8787
uv run --with playwright python ui/playwright/test_graph_layout.py
```

Expected: `PASS: layout ran ...` and a `separationRatio` ≥ 0.8 line (or the INFO skip line for stores with <2 multi-node spaces). Inspect `/tmp/ormah_sigma_layout.png` — organic clusters, no grid.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/GraphView.tsx ui/playwright/test_graph_layout.py
git commit -m "test(ui): Playwright visual test asserts organic FA2 clusters"
```

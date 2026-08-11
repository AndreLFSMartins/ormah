# Task 4: Size-gated layout wiring in GraphView

**Files:**
- Modify: `ui/src/graph/forceLayout.ts` (export the existing NOOP static layout)
- Modify: `ui/src/components/GraphView.tsx` (gate on largest space + DEV `__ormahLayoutMode` +
  immediate `layoutReady`)
- Modify: `ui/playwright/test_graph_drag.py` (force `clusterBySpace=false` before the reheat assertion)
- Create: `ui/playwright/test_graph_cluster.py` (asserts the cluster path is actually taken)

The mount effect uses cluster (static) layout ONLY when `clusterBySpace` is on AND the **largest
single space** is small (`largestSpaceSize(nodes) <= CLUSTER_LAYOUT_MAX_SPACE_NODES`); otherwise the
global FA2 worker — so neither the big default nor one huge space freezes (council R2). A DEV-exposed
`window.__ormahLayoutMode` lets Playwright assert which path ran (closes the coverage gap).

- [ ] **Step 1: Export the NOOP static layout from `forceLayout.ts`**

In `ui/src/graph/forceLayout.ts`, change the private `NOOP_STATIC` (line ~31) into an exported
`STATIC_LAYOUT`, and update the one reference in `createForceLayout`'s catch block to return it:

```typescript
// Exported so cluster mode (static, deterministic positions) can skip the FA2 worker.
export const STATIC_LAYOUT: ForceLayout = {
  start() {}, stop() {}, kill() {}, reheat() {}, isRunning: () => false, available: false,
};
```

Remove the old `const NOOP_STATIC = {...}` line; the catch block returns `STATIC_LAYOUT`.

- [ ] **Step 2: Add imports to `GraphView.tsx`**

Extend the import at line 14 and add the cluster import:

```typescript
import { createForceLayout, STATIC_LAYOUT, type ForceLayout } from "../graph/forceLayout";
import {
  CLUSTER_LAYOUT_MAX_SPACE_NODES,
  computeClusterLayout,
  largestSpaceSize,
} from "../graph/clusterLayout";
```

- [ ] **Step 3: Size-gate the layout in the mount effect**

Replace the current force-layout block (`GraphView.tsx:375-383`, the `const layout = ...; layout.start();`
plus the `layoutWatchdog` setTimeout) with:

```typescript
      // ── Layout: per-space clusters (static) for small graphs, else global FA2 ──
      // Council R1+R2: the default view loads the full incl-archival store, and FA2
      // cost is per-space, so cluster layout runs only when the LARGEST space is
      // small enough to lay out synchronously without blocking the main thread.
      // ponytail: a flat per-space cap; revisit if a mid-size vault still janks.
      const useCluster = clusterBySpace && largestSpaceSize(nodes) <= CLUSTER_LAYOUT_MAX_SPACE_NODES;
      if (import.meta.env.DEV) {
        (window as unknown as Record<string, unknown>).__ormahLayoutMode = useCluster ? "cluster" : "global";
      }
      let layout: ForceLayout;
      let layoutWatchdog: ReturnType<typeof setTimeout> | null = null;
      if (useCluster) {
        const pos = computeClusterLayout(nodes, edges);
        graph.forEachNode((id) => {
          const p = pos.get(id);
          if (p) {
            graph.setNodeAttribute(id, "x", p.x);
            graph.setNodeAttribute(id, "y", p.y);
          }
        });
        layout = STATIC_LAYOUT;
        setLayoutReady(true); // positions are final — no settle delay
      } else {
        layout = createForceLayout(graph);
        layout.start();
        layoutWatchdog = setTimeout(() => setLayoutReady(true), 800);
      }
      layoutRef.current = layout;
```

Guard the matching cleanup in the effect's return (the old `clearTimeout(layoutWatchdog)`):

```typescript
        if (layoutWatchdog !== null) clearTimeout(layoutWatchdog);
```

- [ ] **Step 4: Add `clusterBySpace` to the mount-effect deps**

In the dependency array closing the mount effect (the `}, [nodes, edges, userNodeId])` ending the
`useEffect` opened at `GraphView.tsx:321`), append `clusterBySpace`:

```typescript
    }, [nodes, edges, userNodeId, clusterBySpace]);
```

- [ ] **Step 5: Force the global-worker path in the drag E2E**

In `ui/playwright/test_graph_drag.py`, replace the `page.wait_for_selector("canvas", ...)` +
`page.wait_for_timeout(6000)` pair with (the `evaluate` disables clustering so reheat fires):

```python
        page.wait_for_selector("canvas", timeout=30000)
        # Slice B: drag-reheat only happens on the global-FA2 path; cluster mode is
        # static. Force cluster off (DEV hook from App.tsx) so this asserts the worker.
        page.evaluate("window.__ormahSetClusterBySpace && window.__ormahSetClusterBySpace(false)")
        page.wait_for_timeout(6000)
```

- [ ] **Step 6: Add a Playwright test that the cluster path is taken**

Create `ui/playwright/test_graph_cluster.py` (mirror the launch boilerplate of `test_graph_drag.py`:
same imports, `sync_playwright`, `chromium.launch`, `page.goto` of the dev URL):

The `__ormah*` hooks only exist under `import.meta.env.DEV`, so this test (like `test_graph_drag.py`)
targets the **Vite dev server** (`make ui-dev`, :5173), NOT the production build on :8787.

```python
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=30000)
        # Enable clustering via the DEV hook; the dev store is small, so the gate
        # admits the synchronous cluster path.
        page.evaluate("window.__ormahSetClusterBySpace && window.__ormahSetClusterBySpace(true)")
        page.wait_for_timeout(2000)
        mode = page.evaluate("window.__ormahLayoutMode")
        count = page.evaluate("window.__ormahGraph ? window.__ormahGraph.order : 0")
        browser.close()

    if mode != "cluster":
        print(f"FAIL: expected cluster layout mode, got {mode!r}")
        return 1
    if not count or count < 1:
        print(f"FAIL: graph has no nodes (order={count})")
        return 1
    print(f"PASS: cluster mode active over {count} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Type-check + build**

Run: `( cd ui && npm run build )`
Expected: `tsc -b` passes, `vite build` completes.

- [ ] **Step 8: Run the full frontend unit suite**

Run: `( cd ui && npm run test )`
Expected: all tests pass, including `clusterLayout.test.ts`.

- [ ] **Step 9: Commit**

```bash
git add ui/src/graph/forceLayout.ts ui/src/components/GraphView.tsx \
  ui/playwright/test_graph_drag.py ui/playwright/test_graph_cluster.py
git commit -m "feat(ui): size-gated cluster layout (largest-space gate, DEV mode hook) (#22 slice B)"
```

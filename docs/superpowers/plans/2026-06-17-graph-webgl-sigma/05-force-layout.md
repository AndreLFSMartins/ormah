### Task 5: Force layout (FA2 worker wrapper)

Thin wrapper around the graphology FA2 worker so `GraphView` never touches the worker API directly. Runs the simulation off the main thread, auto-stops after a settle window, and exposes re-heat (for drag). The worker uses a real `Worker`, which jsdom does not provide — so this module has **no unit test**; it is exercised by the Playwright visual test (Task 7). This is an intentional, logged gap, not a placeholder.

**Files:**
- Create: `ui/src/graph/forceLayout.ts`

- [ ] **Step 1: Write the implementation**

Create `ui/src/graph/forceLayout.ts`:

```typescript
import type Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";

export interface ForceLayout {
  start(): void;
  stop(): void;
  kill(): void;
  isRunning(): boolean;
  /** Re-heat for the given settle window (used after a drag). */
  reheat(): void;
}

export interface ForceLayoutOptions {
  /** Auto-stop after this many ms of running (default 4000). */
  settleMs?: number;
}

export function createForceLayout(graph: Graph, opts: ForceLayoutOptions = {}): ForceLayout {
  const settleMs = opts.settleMs ?? 4000;
  const inferred = forceAtlas2.inferSettings(graph);
  const layout = new FA2Layout(graph, {
    settings: {
      ...inferred,
      barnesHutOptimize: graph.order > 1000,
      adjustSizes: true,
      gravity: inferred.gravity ?? 1,
      slowDown: 1,
    },
  });

  let settleTimer: ReturnType<typeof setTimeout> | null = null;

  function clearTimer() {
    if (settleTimer !== null) {
      clearTimeout(settleTimer);
      settleTimer = null;
    }
  }

  function start() {
    if (layout.isRunning()) return;
    layout.start();
    clearTimer();
    settleTimer = setTimeout(() => layout.stop(), settleMs);
  }

  return {
    start,
    stop() {
      clearTimer();
      layout.stop();
    },
    kill() {
      clearTimer();
      layout.kill();
    },
    isRunning: () => layout.isRunning(),
    reheat() {
      start();
    },
  };
}
```

- [ ] **Step 2: Verify it type-checks**

Run: `( cd ui && npx tsc --noEmit )`
Expected: no errors from `forceLayout.ts`. (Errors elsewhere are addressed in their own tasks.)

- [ ] **Step 3: Commit**

```bash
git add ui/src/graph/forceLayout.ts
git commit -m "feat(ui): FA2 web-worker layout wrapper with auto-settle + reheat"
```

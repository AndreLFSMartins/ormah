### Task 5: Force layout (FA2 worker wrapper)

Thin wrapper around the graphology FA2 worker so `GraphView` never touches the worker API directly: runs the simulation off the main thread, auto-stops after a settle window, exposes re-heat (for drag), and reports whether layout is available.

**Council M5:** the FA2 worker constructor is made **injectable** (`layoutFactory`). Production defaults to the real `FA2Layout` (a real `Worker`, absent in jsdom); tests inject a fake so `start/stop/kill/reheat` and **construction failure → static fallback** are unit-tested. `createForceLayout` never throws: if the factory throws (worker unavailable), it returns an `available: false` layout whose methods are no-ops, and `GraphView` then renders the seed positions statically (no live force, but the graph still shows).

**Files:**
- Create: `ui/src/graph/forceLayout.ts`
- Test: `ui/src/graph/forceLayout.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ui/src/graph/forceLayout.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import Graph from "graphology";
import { createForceLayout } from "./forceLayout";

function tinyGraph(): Graph {
  const g = new Graph();
  g.addNode("a", { x: 0, y: 0 }); g.addNode("b", { x: 1, y: 1 });
  g.addEdge("a", "b");
  return g;
}

// Minimal fake matching the FA2Layout surface createForceLayout uses.
function fakeLayout() {
  let running = false;
  return {
    start: vi.fn(() => { running = true; }),
    stop: vi.fn(() => { running = false; }),
    kill: vi.fn(() => { running = false; }),
    isRunning: () => running,
  };
}

describe("createForceLayout", () => {
  it("starts, auto-stops after settleMs, and is killable", () => {
    vi.useFakeTimers();
    const fake = fakeLayout();
    const layout = createForceLayout(tinyGraph(), { settleMs: 1000, layoutFactory: () => fake });
    expect(layout.available).toBe(true);
    layout.start();
    expect(fake.start).toHaveBeenCalledOnce();
    expect(layout.isRunning()).toBe(true);
    vi.advanceTimersByTime(1000);
    expect(fake.stop).toHaveBeenCalledOnce();          // auto-settle fired
    layout.kill();
    expect(fake.kill).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("reheat restarts the simulation", () => {
    const fake = fakeLayout();
    const layout = createForceLayout(tinyGraph(), { settleMs: 9999, layoutFactory: () => fake });
    layout.start(); layout.stop();
    layout.reheat();
    expect(fake.start).toHaveBeenCalledTimes(2);
  });

  it("falls back to a no-op static layout when the worker cannot be created", () => {
    const layout = createForceLayout(tinyGraph(), {
      layoutFactory: () => { throw new Error("Worker unavailable"); },
    });
    expect(layout.available).toBe(false);
    expect(() => { layout.start(); layout.reheat(); layout.stop(); layout.kill(); }).not.toThrow();
    expect(layout.isRunning()).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `( cd ui && npx vitest run src/graph/forceLayout.test.ts )`
Expected: FAIL — cannot find module `./forceLayout`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/forceLayout.ts`:

```typescript
import type Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";

/** The subset of the FA2 worker surface this wrapper drives. */
export interface FA2Worker {
  start(): void;
  stop(): void;
  kill(): void;
  isRunning(): boolean;
}

export interface ForceLayout {
  start(): void;
  stop(): void;
  kill(): void;
  isRunning(): boolean;
  /** Re-heat the settle window (used after a drag). */
  reheat(): void;
  /** false when the worker could not be created — caller renders seed positions statically. */
  available: boolean;
}

export interface ForceLayoutOptions {
  /** Auto-stop after this many ms of running (default 4000). */
  settleMs?: number;
  /** Injectable for tests; defaults to the real FA2 web worker. */
  layoutFactory?: (graph: Graph, settings: Record<string, unknown>) => FA2Worker;
}

const NOOP_STATIC: ForceLayout = {
  start() {}, stop() {}, kill() {}, reheat() {}, isRunning: () => false, available: false,
};

export function createForceLayout(graph: Graph, opts: ForceLayoutOptions = {}): ForceLayout {
  const settleMs = opts.settleMs ?? 4000;
  const inferred = forceAtlas2.inferSettings(graph);
  const settings = {
    ...inferred,
    barnesHutOptimize: graph.order > 1000,
    adjustSizes: true,
    gravity: inferred.gravity ?? 1,
    slowDown: 1,
  };
  const factory = opts.layoutFactory ?? ((g, s) => new FA2Layout(g, { settings: s }) as unknown as FA2Worker);

  let worker: FA2Worker;
  try {
    worker = factory(graph, settings);
  } catch {
    // Worker unavailable (e.g. SSR/jsdom/blocked): fall back to a static render.
    return NOOP_STATIC;
  }

  let settleTimer: ReturnType<typeof setTimeout> | null = null;
  const clearTimer = () => { if (settleTimer !== null) { clearTimeout(settleTimer); settleTimer = null; } };

  function start() {
    if (worker.isRunning()) return;
    worker.start();
    clearTimer();
    settleTimer = setTimeout(() => worker.stop(), settleMs);
  }

  return {
    start,
    stop() { clearTimer(); worker.stop(); },
    kill() { clearTimer(); worker.kill(); },
    isRunning: () => worker.isRunning(),
    reheat() { start(); },
    available: true,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `( cd ui && npx vitest run src/graph/forceLayout.test.ts )`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/forceLayout.ts ui/src/graph/forceLayout.test.ts
git commit -m "feat(ui): injectable FA2 layout wrapper with settle/reheat + static fallback"
```

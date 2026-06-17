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

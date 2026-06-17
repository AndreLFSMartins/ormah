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

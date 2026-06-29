import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchGraph } from "./api";

afterEach(() => vi.unstubAllGlobals());

function mockFetch() {
  const fn = vi.fn(async () => ({
    ok: true,
    json: async () => ({ nodes: [], edges: [], user_node_id: null, all_spaces: [] }),
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("fetchGraph", () => {
  it("requests /ui/graph with no params by default", async () => {
    const fn = mockFetch();
    await fetchGraph();
    expect(fn).toHaveBeenCalledWith("/ui/graph");
  });

  it("adds ?space= when a space is provided", async () => {
    const fn = mockFetch();
    await fetchGraph({ space: "work" });
    expect(fn).toHaveBeenCalledWith("/ui/graph?space=work");
  });

  it("encodes the no-space group as ?space=", async () => {
    const fn = mockFetch();
    await fetchGraph({ space: "" });
    expect(fn).toHaveBeenCalledWith("/ui/graph?space=");
  });

  it("requests ?scope=all when all is set", async () => {
    const fn = mockFetch();
    await fetchGraph({ all: true });
    expect(fn).toHaveBeenCalledWith("/ui/graph?scope=all");
  });
});

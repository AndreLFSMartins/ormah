# Task 2 — Frontend: types + `fetchGraph(opts?)`

**Files:**
- Modify: `ui/src/types.ts` (`GraphData` + new `ViewScope`)
- Modify: `ui/src/api.ts:27-29` (`fetchGraph`)
- Test: `ui/src/api.test.ts` (create)

Rodar testes via `cd ui && npm run test`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/api.test.ts`:

```typescript
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
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npm run test -- api.test.ts`
Expected: FAIL — `fetchGraph` ignores `opts` and always calls `/ui/graph`.

- [ ] **Step 3: Add the `all_spaces` field and `ViewScope` type**

In `ui/src/types.ts`, add `all_spaces` to `GraphData` (optional — keeps `buildGraph`'s inline `{nodes,edges,user_node_id}` and the test helper valid):

```typescript
export interface GraphData {
  nodes: MemoryNode[];
  edges: Edge[];
  user_node_id: string | null;
  all_spaces?: string[];
  has_no_space?: boolean; // F1: a no-space group exists over ALL nodes (incl. archival)
}

export type ViewScope = { kind: "active" } | { kind: "space"; space: string };
```

- [ ] **Step 4: Implement `fetchGraph(opts?)`**

Replace `fetchGraph` in `ui/src/api.ts` (lines 27-29):

```typescript
export function fetchGraph(opts?: { space?: string }): Promise<GraphData> {
  if (opts && opts.space !== undefined) {
    return get(`/ui/graph?space=${encodeURIComponent(opts.space)}`);
  }
  return get("/ui/graph");
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ui && npm run test -- api.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add ui/src/types.ts ui/src/api.ts ui/src/api.test.ts
git commit -m "feat(ui): fetchGraph space param + GraphData.all_spaces + ViewScope type (#22)"
```

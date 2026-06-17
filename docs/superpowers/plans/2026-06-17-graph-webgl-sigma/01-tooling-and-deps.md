### Task 1: Tooling and dependencies

**Files:**
- Modify: `ui/package.json`
- Create: `ui/vitest.config.ts`

> Keep cytoscape* installed for now — `GraphView.tsx` still imports it until Task 6. They are removed in Task 8.

- [ ] **Step 1: Add runtime + test dependencies**

Run (from repo root):

```bash
( cd ui && npm install sigma graphology graphology-layout graphology-layout-forceatlas2 )
( cd ui && npm install -D vitest jsdom )
```

Expected: `package.json` gains `sigma`, `graphology`, `graphology-layout`, `graphology-layout-forceatlas2` under dependencies and `vitest`, `jsdom` under devDependencies.

- [ ] **Step 2: Add the test script**

Edit `ui/package.json` `"scripts"` to add a `test` entry (keep existing scripts):

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
```

- [ ] **Step 3: Create the vitest config**

Create `ui/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
```

- [ ] **Step 4: Add a throwaway sanity test and verify the runner works**

Create `ui/src/graph/_sanity.test.ts`:

```typescript
import { describe, it, expect } from "vitest";

describe("vitest", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

Run: `( cd ui && npm run test )`
Expected: PASS — 1 passed.

- [ ] **Step 5: Delete the sanity test**

```bash
rm ui/src/graph/_sanity.test.ts
```

- [ ] **Step 6: Verify the existing build still works**

Run: `( cd ui && npm run build )`
Expected: build succeeds (cytoscape GraphView still compiles).

- [ ] **Step 7: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/vitest.config.ts
git commit -m "build(ui): add sigma/graphology deps + vitest test runner"
```

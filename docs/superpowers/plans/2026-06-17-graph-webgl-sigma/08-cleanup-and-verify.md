### Task 8: Remove cytoscape + final verification

`GraphView.tsx` no longer imports cytoscape. Remove the dependencies and any code they left orphaned, then verify the whole UI is green.

**Files:**
- Modify: `ui/package.json`
- Modify/remove: any now-dead helper in `ui/src/components/GraphView.tsx` (zoom helpers, cola edge-length, `clusterBySpace` graph mutations) that nothing references after Task 6.

- [ ] **Step 1: Confirm nothing still imports cytoscape**

Run: `grep -rn "cytoscape\|cola\|fcose" ui/src`
Expected: no matches. If any remain, they are dead code from the old body — remove them (do not re-add a renderer).

- [ ] **Step 2: Remove the dependencies**

```bash
( cd ui && npm uninstall cytoscape cytoscape-cola cytoscape-fcose @types/cytoscape )
```

Expected: `package.json` no longer lists them.

- [ ] **Step 3: Typecheck, unit tests, build**

```bash
( cd ui && npx tsc --noEmit )
( cd ui && npm run test )
( cd ui && npm run build )
```

Expected: no type errors; all unit tests pass; build succeeds.

- [ ] **Step 4: Re-run the visual + drag tests (regression)**

> **Council A5:** the visual tests read the DEV-only `window.__ormahGraph` handle, so they MUST run against the Vite dev server (`:5173`), NOT the production build on `:8787`. Use `make dev`.

```bash
make dev   # backend :8787 + vite dev :5173 (DEV handle exposed)
uv run --with playwright python ui/playwright/test_graph_layout.py
uv run --with playwright python ui/playwright/test_graph_drag.py
```

Expected: both `PASS` (organic non-grid + node drag re-heats); inspect `/tmp/ormah_sigma_layout.png`.

- [ ] **Step 5: Manual parity pass against the spec success criteria**

Open http://localhost:5173 (dev) and confirm, citing what you see:
- Organic clusters, isolated nodes on the periphery, **no grid/losango**.
- Colors by tier/space/self; node size varies with access_count; edge colors by type.
- Labels appear (zoom-gated); zoom slider/buttons work; **mouse-hover** highlights node + neighbors and dims others; **search-hover (`highlightNode`) glows WITHOUT dimming** (Council A4).
- Legend click **focuses** that item (vivid + dim rest + camera fit) and clears on re-click (Council A1); App.tsx filters hide via the reducer **without remounting** (camera stays put — Council C2).
- `focusNodeId` from a caller centers the node; Insights/Review `highlightNodes` fits the matched set (Council H1).
- Main thread stays responsive while the layout settles; toggling a filter does NOT reset the layout.

- [ ] **Step 6: Keep the knowledge graph current**

```bash
graphify update .
```

- [ ] **Step 7: Commit**

```bash
git add -A ui/
git commit -m "chore(ui): remove cytoscape deps + dead code after sigma migration"
```

- [ ] **Step 8: Finish the branch**

Invoke `superpowers:finishing-a-development-branch` to decide merge/PR. The branch is `feat/graph-webgl-sigma`.

> **Known carry-over (surface in the PR, do not silently fix):** the spec commit `36f9091` is embedded in the pushed `fix/embedding-delta-backfill` (#32) history; those two doc files will ride along when #32 merges. Removing it would require rewriting a pushed branch — out of scope here. Flag it on #32 for an optional interactive rebase before merge.

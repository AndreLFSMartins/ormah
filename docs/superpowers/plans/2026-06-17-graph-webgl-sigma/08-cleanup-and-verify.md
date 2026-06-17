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

- [ ] **Step 4: Re-run the visual test (regression)**

```bash
make restart
uv run --with playwright python ui/playwright/test_graph_layout.py
```

Expected: `PASS` with organic clusters in `/tmp/ormah_sigma_layout.png`.

- [ ] **Step 5: Manual parity pass against the spec success criteria**

Open http://localhost:8787 and confirm, citing what you see:
- Organic clusters, isolated nodes on the periphery, **no grid/losango**.
- Colors by tier/space/self; node size varies with access_count; edge colors by type.
- Labels appear (zoom-gated); zoom/pan works; hover highlights node + neighbors and dims others.
- Legend space toggles dim/restore; selection opens the side panel.
- Main thread stays responsive while the layout settles.

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

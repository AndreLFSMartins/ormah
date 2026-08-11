# Task 5: Full verification

**Files:** none (verification only).

Confirm the slice ships green across all surfaces and that the council R1 findings are closed.

- [ ] **Step 1: Type-check + build**

Run: `( cd ui && npm run build )`
Expected: `tsc -b` clean, `vite build` completes with no errors.

- [ ] **Step 2: Full frontend unit suite**

Run: `( cd ui && npm run test )`
Expected: all test files pass, including the new `clusterLayout.test.ts` (Tasks 1–2). Note the
pre-task baseline is 70 passing; this slice only adds tests.

- [ ] **Step 3: Playwright E2E (against the Vite dev server)**

The `__ormah*` DEV hooks only exist under `import.meta.env.DEV`, so both tests target the Vite dev
server (:5173), NOT the production build on :8787. Start `make ui-dev`, then run both:

```bash
( cd ui && uv run --with playwright python playwright/test_graph_drag.py )
( cd ui && uv run --with playwright python playwright/test_graph_cluster.py )
```

Expected: `PASS: node dragged and layout re-heated` (drag forces the global-worker path so reheat
fires — Task 4 Step 5 regression fix) and `PASS: cluster mode active over N nodes` (cluster path is
actually taken — closes the council R2 coverage gap).

- [ ] **Step 4: Manual smoke — cluster cohesion + gate + toggle**

Open the graph view at http://localhost:8787 and verify each council finding is closed:

- **Cohesion (small graph):** drill into a space (or a vault under ~1500 nodes) with the cluster
  checkbox ON → spaces render as separate clusters on a ring, not one central blob; cross-space edges
  are long connectors. No overlap between a large cluster and an adjacent small one.
- **Gate (large default):** the default "All memories · incl. archival" view does NOT freeze on load
  — it animates via the global worker (cluster cohesion intentionally not attempted there).
- **Toggle:** open Settings → the new "layout · cluster by space" checkbox toggles; OFF reverts to the
  global force layout in any view; ON re-clusters where the gate allows.
- **No artificial delay:** in cluster mode the graph appears without the ~800ms post-settle pause.

- [ ] **Step 5: Restart the working-tree server (deploy the change)**

```bash
launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8787
```

Expected: `200`.

# Task 3: clusterBySpace toggle (FilterDrawer checkbox + App setter)

**Files:**
- Modify: `ui/src/components/FilterDrawer.tsx` (new "layout" section with a cluster checkbox + prop)
- Modify: `ui/src/App.tsx` (`toggleClusterBySpace` setter; DEV-only `window.__ormahSetClusterBySpace`)

`clusterBySpace` is a boolean (not a `Set`), so the existing `onToggle`/`toggleFilter` (which mutate
Sets) cannot drive it. This task adds a dedicated boolean setter + a checkbox, making the OFF path
user-reachable and the GraphView effect dep (Task 4) live. No vitest unit test (no RTL) — verified by
`tsc`/`build`; the DEV hook also lets the Playwright drag test force the mode (Task 4).

- [ ] **Step 1: Add the prop + checkbox to FilterDrawer**

In `ui/src/components/FilterDrawer.tsx`, add to the `Props` interface (after `onToggle`):

```typescript
  onToggleClusterBySpace: () => void;
```

Add `onToggleClusterBySpace` to the destructured params in the component signature (the
`export default function FilterDrawer({ ... }: Props)` list).

Then add a new section as the FIRST `filter-section` in the returned JSX (immediately after the
opening of the filter body, before the `tier` section):

```tsx
      <div className="filter-section">
        <div className="filter-section-title">layout</div>
        <div className="filter-option" onClick={onToggleClusterBySpace}>
          <div className={`filter-checkbox ${filters.clusterBySpace ? "checked" : ""}`} />
          <span>cluster by space</span>
        </div>
      </div>
```

- [ ] **Step 2: Add the setter + DEV hook in App.tsx**

In `ui/src/App.tsx`, after the existing `toggleFilter` `useCallback` (ends ~line 206), add:

```typescript
  const toggleClusterBySpace = useCallback(
    () => setFilters((f) => ({ ...f, clusterBySpace: !f.clusterBySpace })),
    [],
  );

  // DEV-only: lets the Playwright drag E2E force the global-worker path
  // (cluster mode uses a static layout that never re-heats). See test_graph_drag.py.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    (window as unknown as Record<string, unknown>).__ormahSetClusterBySpace = (v: boolean) =>
      setFilters((f) => ({ ...f, clusterBySpace: v }));
  }, []);
```

(If `useEffect`/`useCallback` are not already imported from `react` in App.tsx, they are — App uses
both extensively. Verify the import line includes them.)

- [ ] **Step 3: Pass the setter into FilterDrawer**

In the `<FilterDrawer ... />` usage in `ui/src/App.tsx` (~line 318), add the prop alongside
`onToggle={toggleFilter}`:

```tsx
        onToggle={toggleFilter}
        onToggleClusterBySpace={toggleClusterBySpace}
```

- [ ] **Step 4: Type-check + build**

Run: `( cd ui && npm run build )`
Expected: `tsc -b` passes (no missing-prop error on `FilterDrawer`), `vite build` completes.

- [ ] **Step 5: Run the frontend suite (no regressions)**

Run: `( cd ui && npm run test )`
Expected: all existing + new tests pass (this task adds no unit test, but must not break any).

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/FilterDrawer.tsx ui/src/App.tsx
git commit -m "feat(ui): cluster-by-space toggle checkbox + setter (#22 slice B)"
```

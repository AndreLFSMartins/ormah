# Task 8 — Land the fix on the live Beta (unfreeze the watermark)

Read [00-overview.md](00-overview.md) first.

**This is the only task that fixes production.** PRs A/B/C target `upstream/main`; the live server runs the Beta's `local-main`, which carries the not-yet-merged K-window rewrite from PR #95. Merging PR A into `local-main` **will conflict in `auto_linker.py`, by design** — the two sides changed the same function for different reasons.

The Beta is what the launchd server executes (editable install). Do not experiment here.

---

### Task 8: merge PR A into `local-main` and adapt the call-site guard

**Files:**
- Modify (via merge + conflict resolution): `src/ormah/background/auto_linker.py`, `src/ormah/background/conflict_detector.py`
- Test: `tests/test_background/test_auto_linker.py`

- [ ] **Step 1: Back up the live index before touching anything**

The store is 236 MB and the server is running. Use SQLite's own backup (a `cp` of a live DB can copy a torn page):

```bash
launchctl bootout gui/$(id -u)/com.ormah.server.dev 2>/dev/null || true
sqlite3 /Users/andre/.local/share/ormah/memory/index.db \
  ".backup '/Users/andre/.local/share/ormah/backups/index.db.pre-117-$(date +%Y%m%d-%H%M)'"
sqlite3 /Users/andre/.local/share/ormah/memory/index.db "PRAGMA integrity_check;"
# Expected: ok
```

- [ ] **Step 2: Merge the PR A branch into `local-main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git checkout local-main
git merge fix/117-auto-linker-idempotent-edges
# Expected: CONFLICT in src/ormah/background/auto_linker.py
```

- [ ] **Step 3: Resolve the conflict — keep the Beta's K-window, take the fix**

Two hunks conflict. Resolve each as follows.

**Hunk 1 — `_apply_edge`:** the function body is identical on both sides apart from PR A's change, so **take PR A's version wholesale** (`INSERT OR IGNORE`, plus the idempotent/self-healing markdown append that adds the `Connection` only when it is not already in the file). Nothing from the Beta side is lost.

**Hunk 2 — the `_apply_edge` call site:** PR A guards the call in the upstream's single-pair loop (`node_resolved = False`). The Beta has no such loop — the call lives in `_flush()`, inside `for slot, v in zip(window, verdicts):`. **Discard PR A's version of this hunk and write the equivalent against `_flush`:**

```python
                try:
                    _apply_edge(engine, state["node"]["id"], slot["pair"]["match_id"],
                                relationship, v.get("reason", ""), slot["pair"]["similarity"])
                except Exception as e:
                    # Same guard as the upstream fix, adapted to the K-window flush:
                    # a single unwritable pair must not abort the run (#117).
                    logger.warning(
                        "auto_linker: edge apply failed for %s -> %s (%s): %s",
                        state["node"]["id"][:8], slot["pair"]["match_id"][:8], relationship, e,
                    )
                    apply_failures += 1
                    state["resolved"] = False   # fail closed: don't advance past this node
                    continue
```

The Beta's `run_auto_linker` returns a stats dict, so wire the counter in as well — next to `created = 0` / `pairs_attempted = 0`:

```python
        apply_failures = 0
```

widen `_flush`'s `nonlocal`:

```python
            nonlocal created, pairs_attempted, pairs_evaluated, apply_failures
```

and add it to the stats dict (the one starting with `"nodes_scanned": len(nodes),`):

```python
            "edge_apply_failures": apply_failures,
```

`conflict_detector.py` should merge cleanly (the edge-write block is identical on both sides). If it conflicts, take PR A's version.

- [ ] **Step 4: Add the Beta-only test for the stats counter**

Append to `tests/test_background/test_auto_linker.py`:

```python
def test_run_survives_an_edge_apply_failure_and_counts_it(engine, monkeypatch):
    """Beta-only: run_auto_linker returns a stats dict, so the failure is countable."""
    import json
    from unittest.mock import patch
    from ormah.background import auto_linker as al

    _create_pair(engine)
    engine.settings.llm_enabled = True

    def boom(*_args, **_kwargs):
        raise RuntimeError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(al, "_apply_edge", boom)

    llm_response = json.dumps({"relationship": "supports", "reason": "r"})
    _reset_adapter()
    with patch(_LLM_PATCH, return_value=llm_response):
        stats = al.run_auto_linker(engine)

    assert stats is not None
    assert "error" not in stats          # the run completed instead of aborting
    assert stats["edge_apply_failures"] >= 1
```

- [ ] **Step 5: Verify against the live source tree**

Here the editable install points at this very tree, so **no `PYTHONPATH` is needed** — but confirm it anyway:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python -c "import ormah; print(ormah.__file__)"
# MUST print /Users/andre/Documents/GitHub/Tools/ormah/src/ormah/__init__.py

.venv/bin/python -m pytest tests/test_background/test_auto_linker.py \
  tests/test_background/test_conflict_detector.py -v
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_cloud 2>&1 | tail -3
.venv/bin/ruff check src/ tests/
```

Expected: the auto_linker/conflict suites PASS; the full run shows the same ~9 pre-existing environmental failures `local-main` had before the merge — **no new ones**.

- [ ] **Step 6: Commit the merge and restart the server**

```bash
git add src/ormah/background/auto_linker.py src/ormah/background/conflict_detector.py \
        tests/test_background/test_auto_linker.py
git commit -m "merge: idempotent edge writes (#117) — call-site guard adapted to the K-window flush

Merges fix/117-auto-linker-idempotent-edges. _apply_edge is taken as-is from the
fix; the per-pair guard is re-expressed against _flush() (the Beta's K-window
rewrite from PR #95, which the upstream branch does not have) and its failures are
surfaced in the run stats as edge_apply_failures."

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ormah.server.dev.plist
sleep 5 && curl -s localhost:8787/admin/health | head -5
```

- [ ] **Step 7: Prove the watermark actually moves**

This is the acceptance test for the whole plan. Record the frozen watermark, run the job once, and confirm it advanced.

```bash
sqlite3 "file:/Users/andre/.local/share/ormah/memory/index.db?mode=ro" \
  "SELECT value FROM meta WHERE key = 'auto_link_watermark';"
# Expected before: 333726
```

Trigger one run and watch it (it takes ~10 minutes on the current backlog — do NOT trigger a second one while it runs; that is what caused the collision in the first place):

```bash
curl -s -X POST localhost:8787/admin/tasks/auto_linker/run
```

```bash
sqlite3 "file:/Users/andre/.local/share/ormah/memory/index.db?mode=ro" \
  "SELECT value FROM meta WHERE key = 'auto_link_watermark';"
# Expected after: > 333726
grep -c "UNIQUE constraint failed: edges" /Users/andre/.local/share/ormah/logs/ormah.log
# Expected: no NEW occurrences with a timestamp after the restart
```

**If the watermark still does not move**, the run is being blocked by something else — most likely a permanently vectorless node parking the cursor (the deferred follow-up recorded on issue #109). Read the run's WARNINGs before drawing any conclusion; do not assume this fix failed.

- [ ] **Step 8: Drain the backlog (expect several nights)**

`auto_link_max_nodes_per_run` defaults to **500**, so a ~13k backlog needs ~27 successful runs, and the job's interval is `auto_link_interval_minutes = 1440` (once a day). Read the effective value before promising a drain window:

```bash
grep -E "AUTO_LINK_(MAX_NODES_PER_RUN|INTERVAL_MINUTES)" /Users/andre/.config/ormah/.env || echo "using defaults: 500 nodes/run, 1440 min"
```

Raising the cap or the frequency is a **config change on the live server** — do not do it without asking André. State the numbers and let him decide.

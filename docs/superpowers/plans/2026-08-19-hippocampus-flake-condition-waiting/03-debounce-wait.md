### Task 3: The debounce wait (line 169)

**Files:**
- Modify: `tests/test_background/test_hippocampus.py` — `test_debounce_prevents_duplicate_ingestion`

**Interfaces:**
- Consumes: `_wait_until` from Task 2.

- [ ] **Step 1: Measure the real margin before changing anything**

The arithmetic read off the code says this test is far tighter than the one that failed on CI: `debounce_seconds=0.3`, five writes at 0.05s intervals end at t≈0.25s, the surviving timer fires at t≈0.55s, and the `time.sleep(0.5)` expires at t≈0.75s — leaving ~0.2s minus ingestion. Confirm it, do not trust it:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest \
  tests/test_background/test_hippocampus.py::test_debounce_prevents_duplicate_ingestion \
  -v --durations=1
```

Record the duration. If the measured margin contradicts the arithmetic above, stop and report it — the conversion is still correct, but the spec's framing would need updating.

- [ ] **Step 2: Convert the wait**

Replace:

```python
        # Wait for debounce
        time.sleep(0.5)

    assert call_count == 1
```

with:

```python
        # The debounced timer must fire at all — poll rather than budget for it.
        _wait_until(lambda: call_count >= 1)
        # Proving no SECOND call arrives inherently needs a window. A slow runner
        # makes this half fail toward a false pass, never a false failure.
        time.sleep(handler.debounce_seconds * 2)

    assert call_count == 1
```

- [ ] **Step 3: Run the test**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest \
  tests/test_background/test_hippocampus.py::test_debounce_prevents_duplicate_ingestion -v
```

Expected: PASS.

- [ ] **Step 4: Prove it still catches a broken debounce**

Temporarily change `HippocampusHandler(engine, watch_dir, debounce_seconds=0.3)` to `debounce_seconds=0.01`, so each write's timer fires before the next write cancels it. Re-run Step 3 and confirm it FAILS with `assert 5 == 1` (or another count above 1). Revert to `0.3`. Do not commit the temporary edit.

- [ ] **Step 5: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
git add tests/test_background/test_hippocampus.py
git commit -m "test(hippocampus): poll for the debounced call instead of budgeting for it

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

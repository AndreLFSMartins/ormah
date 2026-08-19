### Task 2: `_wait_until` and the ingestion wait (line 83)

**Files:**
- Modify: `tests/test_background/test_hippocampus.py` — add helper after the module constants; rewrite `test_new_file_triggers_ingestion`

**Interfaces:**
- Produces: `_wait_until(predicate, timeout=10.0, interval=0.01)` — returns the last value of `predicate()`, truthy on success, falsy on timeout. Task 3 consumes it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_background/test_hippocampus.py`. It injects the latency a loaded runner produces, deterministically:

```python
def test_new_file_ingestion_survives_a_slow_pipeline(engine, tmp_path, monkeypatch):
    """A pipeline slower than any fixed budget must still be observed."""
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()

    engine.settings.hippocampus_watch_dirs = [watch_dir]
    engine.settings.hippocampus_enabled = True
    engine.settings.hippocampus_debounce_seconds = 0.1

    real_ingest = hippocampus._ingest_file

    def slow_ingest(*args, **kwargs):
        time.sleep(1.5)          # exceeds the old 0.5s budget by 3x
        return real_ingest(*args, **kwargs)

    monkeypatch.setattr(hippocampus, "_ingest_file", slow_ingest)

    with patch(_LLM_PATCH, return_value=_LLM_RESPONSE):
        observers = start_hippocampus(engine)
        try:
            (watch_dir / "new_session.md").write_text(_SAMPLE_MD)
            state = _wait_until(lambda: _load_state(watch_dir)) or {}
            assert "new_session.md" in state
        finally:
            stop_hippocampus(observers)
```

This needs `from ormah.background import hippocampus` added to the imports.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest \
  tests/test_background/test_hippocampus.py::test_new_file_ingestion_survives_a_slow_pipeline -v
```

Expected: FAIL with `NameError: name '_wait_until' is not defined`.

- [ ] **Step 3: Add the helper**

Insert after `_SAMPLE_MD`:

```python
def _wait_until(predicate, timeout=10.0, interval=0.01):
    """Poll until predicate() is truthy. Returns its last value.

    Returns rather than raises so the caller's own assertion is the one that
    fails, keeping the failure message specific to the behaviour under test.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()
```

- [ ] **Step 4: Run it to verify it passes**

Same command as Step 2. Expected: PASS, in roughly 1.6s.

- [ ] **Step 5: Prove the helper does not mask a real regression**

Temporarily change `slow_ingest` to `return False` without calling `real_ingest`, re-run Step 2's command, and confirm it FAILS with `assert 'new_session.md' in {}` after ~10s. Then revert to the Step 1 body. Do not commit the temporary edit.

- [ ] **Step 6: Convert the original test**

In `test_new_file_triggers_ingestion`, replace these two lines:

```python
            # Wait for debounce + processing
            time.sleep(0.5)
            state = _load_state(watch_dir)
```

with:

```python
            state = _wait_until(lambda: _load_state(watch_dir)) or {}
```

- [ ] **Step 7: Run the whole file**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m pytest \
  tests/test_background/test_hippocampus.py -v > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
tail -20 out.txt
```

Expected: all tests pass, `PYTEST_EXIT=0`. Never pipe pytest straight into `tail` — the exit code becomes `tail`'s.

- [ ] **Step 8: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-hippocampus-flake
git add tests/test_background/test_hippocampus.py
git commit -m "test(hippocampus): wait on the condition, not on a fixed budget

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

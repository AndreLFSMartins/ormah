# Task 3: Verify no regression against the baseline

**Files:** none modified — verification only.

**Interfaces:**
- Consumes: the fix committed in Task 2.
- Produces: the evidence required before the change reaches the running Beta.

- [ ] **Step 1: Run the full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: **7 failures**, exactly the known baseline (`test_cloud_settings` 1, `test_setup` 6), with
the new deadlock test passing. Any 8th failure blocks this task — investigate before proceeding.

Record the actual tail output. A claim of "tests pass" without the output pasted is not verification.

- [ ] **Step 2: Run ruff**

```bash
ruff check src/ tests/
```

Expected: the finding set is identical to `local-main`'s over tracked files. Any new finding in
`builder.py` or `test_builder.py` must be fixed before committing further.

- [ ] **Step 3: Confirm the 7 failures are genuinely pre-existing**

The baseline is recall until a run proves it. On a tree where only `builder.py` and
`test_builder.py` changed:

```bash
python -m pytest tests/test_cloud_settings.py tests/test_setup.py -q 2>&1 | tail -5
```

Expected: the same 7 failures, all in cloud-settings and setup. If any failure here touches
indexing, locking, or the file store, it is **not** pre-existing — stop and investigate.

- [ ] **Step 4: Confirm the fix under repetition**

A deadlock is a race; one green run is weak evidence. Run the new test 20 times:

```bash
python -m pytest tests/test_index/test_builder.py::test_incremental_update_does_not_deadlock_against_a_memory_job \
  --count=20 -q 2>&1 | tail -5
```

If `pytest-repeat` is not installed (`--count` unrecognised), use the shell instead:

```bash
for i in $(seq 1 20); do
  python -m pytest tests/test_index/test_builder.py::test_incremental_update_does_not_deadlock_against_a_memory_job -q \
    2>&1 | tail -1
done
```

Expected: 20 passes. A single hang means the inversion is not fully closed — return to diagnosis
rather than re-running until it goes green.

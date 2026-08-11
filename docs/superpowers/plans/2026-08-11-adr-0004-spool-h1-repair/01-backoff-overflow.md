# Task 01 — The backoff saturates instead of overflowing

Read `00-overview.md` first: it carries the global constraints and the shell prefix
(`$WT`, `$PY`) every command here assumes, plus Task 0, which must pass before you start.

**Files:**
- Modify: `src/ormah/background/ingest_spool.py:36-37` (new constant), `:247` (the clamp)
- Test: `tests/test_background/test_ingest_spool.py`

**Interfaces:**
- Consumes: `IngestSpool.enqueue`, `.claim_next`, `.requeue`, `.root`, `.pending_count` — all existing, unchanged.
- Produces: `_BACKOFF_MAX_SHIFT` (module-level `int`), read only inside `requeue`.

## Why

`delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_MAX_SECONDS)` caps the
**product**. `2 ** (attempts - 1)` is an arbitrary-precision `int`, so past attempt 1024 the
float multiplication raises *before* `min()` can cap anything — and before
`self._write_job(...)` (`:272`) persists the retry. The job is left with neither progress nor
a dead-letter record. At the 300 s ceiling that point arrives after ~3.5 days of continuous
retry, so any outage of that length hits it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_ingest_spool.py`. `json`, `time`, `Path` and
`IngestSpool` are already imported at the top of that file:

```python
def test_requeue_external_backoff_saturates_instead_of_overflowing(tmp_path):
    """H1: a long outage must keep retrying. The cap was applied to the PRODUCT, not the
    exponent, so attempt 1025 raised OverflowError before _write_job persisted the retry --
    stranding the job with neither progress nor a dead-letter record."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=1, reason="nudge")
    job = spool.claim_next()
    assert job is not None
    spool.requeue(job, failure_class="external")

    # Fast-forward the PERSISTED state to attempt 1024 -- the last one whose backoff still
    # computed -- instead of sleeping through 3.5 days of real retries.
    pending_file = next((spool.root / "pending").glob("*.json"))
    data = json.loads(pending_file.read_text())
    data["attempts"] = 1024
    data["not_before"] = 0.0
    pending_file.write_text(json.dumps(data))

    job2 = spool.claim_next()
    assert job2 is not None and job2.attempts == 1024

    before = time.time()
    spool.requeue(job2, failure_class="external")   # attempt 1025 -- this used to raise

    pending_files = list((spool.root / "pending").glob("*.json"))
    assert len(pending_files) == 1, "the retry must be persisted, not lost to an exception"
    data2 = json.loads(pending_files[0].read_text())
    assert data2["attempts"] == 1025, "attempts must keep counting past the old break"
    # not_before is stamped with a time.time() taken AFTER `before`, so the observed gap is
    # 300.0 + epsilon -- never <= 300.0. Same tolerance shape as the ~2s assertion above.
    assert 299.5 < data2["not_before"] - before <= 301.0, "delay saturates at the 300s cap"
    assert list((spool.root / "failed").glob("*.json")) == [], (
        "an external failure must never be dead-lettered, no matter how many attempts (H1)"
    )
    assert list((spool.root / "running").iterdir()) == []
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
PYTHONPATH=$WT/src $PY -m pytest \
  tests/test_background/test_ingest_spool.py::test_requeue_external_backoff_saturates_instead_of_overflowing -v
```

Expected: FAIL with `OverflowError: int too large to convert to float`.

A failure with any other message means the test is not reaching the defect. Fix the test
before touching `src/` — a red test that is red for the wrong reason proves nothing.

- [ ] **Step 3: Add the constant**

In `src/ormah/background/ingest_spool.py`, immediately after `_BACKOFF_MAX_SECONDS = 300.0`
(`:37`):

```python
# Clamp the SHIFT, not just the product: `2 ** (attempts - 1)` is an arbitrary-precision
# int, so a long enough outage overflows the float multiplication before min() can cap it.
# The delay already saturates at shift 8 (2.0 * 2**8 = 512 > 300), so any clamp at or above
# that returns an identical delay for every attempt count that used to compute -- while
# keeping the product far below the float ceiling. min() stays the authority on the value.
_BACKOFF_MAX_SHIFT = 62
```

- [ ] **Step 4: Apply the clamp**

In the `failure_class == "external"` branch of `requeue`, replace line 247:

```python
            delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_MAX_SECONDS)
```

with:

```python
            shift = min(attempts - 1, _BACKOFF_MAX_SHIFT)
            delay = min(_BACKOFF_BASE_SECONDS * (2 ** shift), _BACKOFF_MAX_SECONDS)
```

- [ ] **Step 5: Run the whole spool suite**

```bash
PYTHONPATH=$WT/src $PY -m pytest tests/test_background/test_ingest_spool.py -v
```

Expected: all pass. `test_requeue_external_retries_forever_with_persisted_growing_backoff`
(the growing-backoff contract) and `test_requeue_deterministic_failure_dead_letters_with_original_bytes`
must both still be green — quote the summary line in your report.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/ingest_spool.py tests/test_background/test_ingest_spool.py
git commit -m "fix(spool): clamp the backoff exponent so a long outage cannot strand a job

The cap was applied to the product, so 2 ** (attempts - 1) overflowed the float
multiplication at attempt 1025 -- and it raised BEFORE _write_job persisted the
retry, leaving the job with neither progress nor a dead-letter record. That is
the H1 failure the spool exists to prevent, reachable by any ~3.5 day outage."
```

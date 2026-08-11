# Task 02 — A deleted transcript is dead-lettered, not retried forever

Read `00-overview.md` first: it carries the global constraints and the shell prefix
(`$WT`, `$PY`) every command here assumes. **Task 01 must be committed before this one** —
without its clamp, the behaviour this task changes still ends in an `OverflowError`.

**Files:**
- Modify: `src/ormah/background/session_watcher.py:44-49` (enum), `:876-885` (classification), `:1458` (drain branch)
- Test: `tests/test_background/test_session_watcher.py`

**Interfaces:**
- Consumes: `IngestResult` (existing enum), `SessionHandler._run_job`, `IngestSpool.requeue` — all unchanged signatures.
- Produces: `IngestResult.GONE` (value `"gone"`), returned by `_ingest_session` and consumed only at the drain branch added in Step 4.

## Why

`FileNotFoundError` is an `OSError`, so a permanently deleted transcript is indistinguishable
from `EIO`/`EACCES` and becomes `TRANSIENT` → `requeue(job, failure_class="external")` →
retried forever. `requeue`'s own docstring says the opposite in as many words: *"deterministic
(malformed job, **transcript deleted**, path no longer under any watch root): a retry cannot
change the outcome, so the job is dead-lettered immediately"* (`ingest_spool.py:241-242`).
This is what fed 8 jobs to the overflow on 2026-08-11.

`NO_PROGRESS` is **not** a usable substitute: its drain path falls through to
`self.spool.complete(job)` (`:1499`), so the job would vanish with no record at all.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_background/test_session_watcher.py`. The helpers `_handler_with_spool`
(`:206`) and `_drain_all` (`:195`) and the `engine` fixture already exist in that file:

```python
def test_deleted_transcript_is_dead_lettered_not_retried_forever(engine, tmp_path):
    """requeue's contract names this case: "transcript deleted ... a retry cannot change
    the outcome, so the job is dead-lettered immediately". FileNotFoundError is an OSError,
    so it fell into the generic handler, was classed "external", and retried forever --
    which is what fed 8 jobs to the backoff overflow on 2026-08-11."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "gone.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")
    jsonl.unlink()                       # the transcript is gone before the drain claims it

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, "a deleted transcript must be dead-lettered, not retried"
    assert handler.spool.pending_count() == 0, (
        "it must not go back to pending as an external failure"
    )
    assert list((handler.spool.root / "running").iterdir()) == []
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
PYTHONPATH=$WT/src $PY -m pytest \
  tests/test_background/test_session_watcher.py::test_deleted_transcript_is_dead_lettered_not_retried_forever -v
```

Expected: FAIL on `len(failed) == 1` — `failed/` is empty because the job went back to
`pending/` classed `external`.

If it fails on a different assertion, **read the output before proceeding**: the job took a
path this plan did not predict, and that changes the fix.

- [ ] **Step 3: Add the enum member**

In `src/ormah/background/session_watcher.py`, after the `TRANSIENT` line (`:49`):

```python
    GONE = "gone"                # the transcript no longer exists -> deterministic, dead-letter
```

- [ ] **Step 4: Classify `FileNotFoundError` and route it**

In `_ingest_session`, replace lines 876-885:

```python
    try:
        h = _file_hash(path)
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return IngestResult.TRANSIENT
    try:
        size = path.stat().st_size
    except OSError as e:
        logger.warning("Cannot stat %s: %s", path, e)
        return IngestResult.TRANSIENT
```

with this — the `FileNotFoundError` clause **must come first**, since it is a subclass of
`OSError` and the generic clause would otherwise swallow it:

```python
    try:
        h = _file_hash(path)
    except FileNotFoundError:
        # Deterministic, not external: no retry can bring a deleted transcript back, and
        # classing it "external" is what retried 8 jobs into the backoff overflow.
        logger.info("Transcript no longer exists, dead-lettering: %s", path)
        return IngestResult.GONE
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return IngestResult.TRANSIENT
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        logger.info("Transcript no longer exists, dead-lettering: %s", path)
        return IngestResult.GONE
    except OSError as e:
        logger.warning("Cannot stat %s: %s", path, e)
        return IngestResult.TRANSIENT
```

Then add the drain branch in `_run_job`, immediately **before** the `TRANSIENT` check at
`:1458` (`if result is IngestResult.TRANSIENT:`):

```python
        if result is IngestResult.GONE:
            # Deterministic failure class -> requeue dead-letters it at once, keeping the
            # job payload in failed/ as a record. Never retried: the file is gone.
            self.spool.requeue(job, failure_class="transcript_deleted")
            return
```

- [ ] **Step 5: Run the new test and the surrounding suite**

```bash
PYTHONPATH=$WT/src $PY -m pytest tests/test_background/test_session_watcher.py -v 2>&1 | tail -15
```

Expected: all pass. `test_idle_file_with_no_safe_boundary_is_dead_lettered` and
`test_unexpected_exception_requeues_instead_of_stranding_in_running` must both stay green —
they pin the neighbouring drain paths. Quote the summary line in your report.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): dead-letter a deleted transcript instead of retrying it forever

FileNotFoundError is an OSError, so a permanently deleted transcript was
indistinguishable from EIO/EACCES and became TRANSIENT -> failure_class
\"external\" -> retried forever, contradicting requeue's own documented
contract. EIO/EACCES keep retrying; only ENOENT becomes deterministic."
```

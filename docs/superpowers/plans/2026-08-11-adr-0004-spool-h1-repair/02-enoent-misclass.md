# Task 02 — A deleted transcript is dead-lettered, not retried forever

Read `00-overview.md` first: it carries the global constraints and the shell prefix
(`$WT`, `$PY`) every command here assumes. **Task 01 must be committed before this one** —
without its clamp, the behaviour this task changes still ends in an `OverflowError`.

**Files:**
- Modify: `src/ormah/background/session_watcher.py:44-49` (enum), `:876-885` (pre-parse classification), `:1045` (parse-block classification), `:1458` (drain branch), `:1499` (drain guard)
- Test: `tests/test_background/test_session_watcher.py`

There are **three** classification sites plus **one final guard**, not two sites. Steps 3-4 cover
the pre-parse `ENOENT`; steps 5-7 the parser's own re-read; steps 8-9 everything that vanishes
*after* `_ingest_session` returns. The guard is deliberately last and deliberately broad: it is
the backstop for any route that reaches `complete()` with the transcript gone.

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

- [ ] **Step 5: Write the failing TOCTOU test (council finding 1 — the silent-loss path)**

Steps 3-4 only cover a transcript already gone when the job is claimed. The parser **re-reads**
the file on its own (`parser.py:261` `path.stat()`, then `:320` `open()`), so a transcript deleted
*between* the watcher's hash/stat and the parser's own access
takes a different route: the `try` at `session_watcher.py:982` has exactly one handler — the
generic `except Exception` at `:1045` — which returns `NO_PROGRESS`. The drain then finds
`_idle_with_unsafe_tail` false (its `stat` fails, `:1512`) and falls through to
`complete(job)` (`:1499`). The job is **erased with no `failed/` record at all** — a silent
loss, worse than the retry-forever it replaces, and exactly what `NO_PROGRESS` was rejected for.

Append to `tests/test_background/test_session_watcher.py` (`Path` is imported at `:10`,
`pytest` at `:13`, so the `monkeypatch` fixture is available):

```python
def test_transcript_deleted_mid_drain_is_dead_lettered_not_completed(engine, tmp_path, monkeypatch):
    """TOCTOU: _file_hash and stat both succeed, then the parser reopens the file and finds it
    gone. That FileNotFoundError lands in the generic `except Exception` -> NO_PROGRESS ->
    complete(job): the job is erased with NO dead-letter record. Silent loss is the one thing
    H1 forbids outright."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "vanishes.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    import ormah.background.session_watcher as sw
    real_parse = sw.parse_transcript

    def _delete_then_parse(path, *args, **kwargs):
        # Gone before the parser touches it at all, so the ENOENT surfaces from the parser's
        # own path.stat() (parser.py:261) rather than its open() (:320). Either raises
        # FileNotFoundError into the same handler, which is what this test pins.
        Path(path).unlink(missing_ok=True)
        return real_parse(path, *args, **kwargs)

    monkeypatch.setattr(sw, "parse_transcript", _delete_then_parse)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, (
        "a transcript deleted mid-drain must leave a dead-letter record, never be completed"
    )
    assert handler.spool.pending_count() == 0
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()
```

- [ ] **Step 6: Run it and confirm it fails for the right reason**

```bash
set -o pipefail
PYTHONPATH=$WT/src $PY -m pytest \
  tests/test_background/test_session_watcher.py::test_transcript_deleted_mid_drain_is_dead_lettered_not_completed -v
```

Expected: FAIL on `len(failed) == 1` — `failed/` is empty because the job was silently
completed. If it instead fails because the job is in `pending/`, the deletion happened earlier
than intended; fix the test before touching `src/`.

- [ ] **Step 7: Classify `FileNotFoundError` in the parse block**

In `_ingest_session`, add a clause **before** the generic handler at `:1045` (it must come
first — `FileNotFoundError` is a subclass of `Exception`):

```python
    except FileNotFoundError:
        # The parser reopens the file, so it can vanish after the hash/stat above. Without
        # this clause the generic handler below returns NO_PROGRESS, and the drain COMPLETES
        # the job -- erasing it with no dead-letter record at all.
        logger.info("Transcript vanished mid-parse, dead-lettering: %s", path)
        return IngestResult.GONE
    except Exception as e:  # noqa: BLE001 - transcript parsers can raise provider-specific errors
        logger.warning("Session transcript parse error for %s: %s", path, e)
        return IngestResult.NO_PROGRESS
```

No change is needed at the drain: the `GONE` branch added in Step 4 already routes it.

- [ ] **Step 8: Write the failing post-ingest test (council round 2 — the last ENOENT window)**

Steps 5-7 close the window *inside* `_ingest_session`. One remains **after** it returns: the
transcript can vanish between that return and the drain's own decision. `_idle_with_unsafe_tail`
swallows the `ENOENT` in **both** its `stat` (`:1512`) and its `parse` (`:1521`), returning
`False` either way — so the drain falls through to `complete(job)` (`:1499`) and erases the job
with no record.

```python
def test_transcript_deleted_after_ingest_returns_is_dead_lettered(engine, tmp_path, monkeypatch):
    """The transcript survives _ingest_session (which returns NO_PROGRESS on its own merits)
    and is deleted before the drain decides. _idle_with_unsafe_tail swallows the ENOENT in both
    its stat and its parse, returning False, so the drain would complete(job) -- erasing it with
    no dead-letter record."""
    watch_dir = tmp_path / "projects"
    proj = watch_dir / "-Users-alice-Code-myproject"
    proj.mkdir(parents=True)
    jsonl = proj / "late.jsonl"
    jsonl.write_text('{"type":"user"}\n', encoding="utf-8")

    import ormah.background.session_watcher as sw

    def _no_progress_then_delete(*args, **kwargs):
        jsonl.unlink(missing_ok=True)          # gone AFTER the ingest decision, before the drain's
        return sw.IngestResult.NO_PROGRESS

    monkeypatch.setattr(sw, "_ingest_session", _no_progress_then_delete)

    handler = _handler_with_spool(engine, watch_dir, tmp_path / "spool")
    handler.spool.enqueue(jsonl, boundary=jsonl.stat().st_size, reason="nudge")

    _drain_all(handler)

    failed = list((handler.spool.root / "failed").glob("*.json"))
    assert len(failed) == 1, "a transcript gone by decision time must leave a dead-letter record"
    errs = list((handler.spool.root / "failed").glob("*.error"))
    assert errs and "transcript_deleted" in errs[0].read_text()
```

```bash
set -o pipefail
PYTHONPATH=$WT/src $PY -m pytest \
  tests/test_background/test_session_watcher.py::test_transcript_deleted_after_ingest_returns_is_dead_lettered -v
```

Expected: FAIL on `len(failed) == 1` — the job was silently completed.

- [ ] **Step 9: Add the drain guard (a class-level backstop, not another instance patch)**

In `_run_job`, replace the final `self.spool.complete(job)` at `:1499` — the `NO_PROGRESS`
fallthrough, **not** the one in the `OK` branch at `:1473` — with:

```python
        if not path.exists():
            # A transcript that vanished after _ingest_session returned still arrives here as
            # NO_PROGRESS: _idle_with_unsafe_tail swallows the ENOENT in both its stat (:1512)
            # and its parse (:1521) and returns False. Completing would erase the job with no
            # record. Deliberately a guard on the FINAL disposition rather than a classifier
            # inside the predicate: it catches ANY route that reaches complete() with the
            # transcript gone, including interleavings nobody has enumerated yet.
            self.spool.requeue(job, failure_class="transcript_deleted")
            return
        self.spool.complete(job)
```

Do **not** make `_idle_with_unsafe_tail` classify `ENOENT` (Codex's proposed shape, declined):
it is a predicate, and giving it a second responsibility spreads the decision across more sites.

- [ ] **Step 10: Run the new tests and the surrounding suite**

```bash
set -o pipefail
PYTHONPATH=$WT/src $PY -m pytest tests/test_background/test_session_watcher.py -v; echo "pytest rc=$?"
```

Expected: all pass, `pytest rc=0`. `test_idle_file_with_no_safe_boundary_is_dead_lettered` and
`test_unexpected_exception_requeues_instead_of_stranding_in_running` must both stay green —
they pin the neighbouring drain paths. Quote the summary line **and the rc** in your report;
piping to `tail` without `pipefail` hides a red suite behind a green exit code.

- [ ] **Step 11: Commit**

```bash
git add src/ormah/background/session_watcher.py tests/test_background/test_session_watcher.py
git commit -m "fix(watcher): dead-letter a deleted transcript instead of losing it

Two routes, both against requeue's documented contract. Before the parse,
FileNotFoundError is an OSError, so a deleted transcript was indistinguishable
from EIO/EACCES and became TRANSIENT -> \"external\" -> retried forever. After
it, the parser reopens the file, so a transcript deleted mid-drain raised into
the generic except -> NO_PROGRESS -> complete(job), erasing the job with no
dead-letter record at all -- a silent loss, which H1 forbids outright.

EIO/EACCES keep retrying; only ENOENT becomes deterministic."
```

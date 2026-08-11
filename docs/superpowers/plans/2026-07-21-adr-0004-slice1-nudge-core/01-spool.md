# Task 1: The ingest spool — a durable queue made of files

**Files:**
- Create: `src/ormah/background/ingest_spool.py`
- Create: `tests/test_background/test_ingest_spool.py`

**Interfaces:**
- Consumes: nothing. This module imports no ormah code — it is pure filesystem + stdlib,
  which is what makes it exhaustively testable without an engine, a server, or a provider.
- Produces the whole public surface the rest of the slice builds on:

```python
class IngestSpool:
    def __init__(self, root: Path) -> None: ...
    def enqueue(self, path: Path, boundary: int, reason: str) -> None: ...
    def claim_next(self) -> SpoolJob | None: ...
    def complete(self, job: SpoolJob) -> None: ...
    def requeue(self, job: SpoolJob, failure_class: str) -> None: ...  # keep the intent
    def recover(self) -> int: ...          # running/ -> pending/, returns how many
    def pending_count(self) -> int: ...
```

`requeue(job, failure_class)` — ⚠️ **read this before implementing; an earlier draft of
this plan got it backwards** (council R12, codex). The first version capped every retry at
`MAX_JOB_ATTEMPTS` and dead-lettered the rest, to stop a permanently-failing job from
spinning. That cap sends a **provider outage** to the dead-letter queue, which is exactly
the H1 rule ADR-0004 exists to protect: *an outage must never discard real data*. A long
outage would silently exhaust the attempts of perfectly good work.

So the disposition keys on the **class of failure**, not on a counter:

| Class | Example | Policy |
|-------|---------|--------|
| **External transient** | provider down, connection refused, timeout, `EIO` | **Retry indefinitely** with persisted exponential backoff (`attempts` drives the delay, never a cap). Never dead-lettered. |
| **Deterministic** | malformed job JSON, transcript deleted, path no longer under any root | Dead-letter to `failed/` immediately — a retry cannot change the outcome. |

The backoff must be **persisted in the job payload** (`attempts`, `not_before`), not held in
memory: a restart during an outage would otherwise reset every backoff to zero and stampede
the provider. `claim_next` skips jobs whose `not_before` is in the future.

`_dead_letter(file, raw_bytes, error)` writes the job to `failed/` **with its original bytes
and the error string** — never `unlink`. An accepted nudge must stay recoverable by hand;
this is the same principle as the existing `skipped_slices` quarantine record.

The full extraction-failure policy (quarantine, shrink ladder, health gate) is slice 3's
job. What slice 1 owes is only this: **never lose an accepted job, and never spin hot.**

Also expose two module-level helpers so no caller has to reconstruct a path:
`spool_root(settings) -> Path` returning `settings.memory_dir / "ingest_queue"` (the
same-filesystem rule holds only under `memory_dir`), and `root_key(watch_dir) -> str`, a
short stable hash used to give **one spool per watch root** — roots must not share a queue,
or a nudge for one root could be claimed by another root's worker and resolve against the
wrong cursor.

**Why this exists** (ADR-0004 Amendment 2026-07-22): the nudge needs a durable record of
*which boundary was accepted* before answering 202. The Cursor cannot hold it — it is a
progress record, shared per watch dir, rewritten whole from four call sites. A SQLite job
table was measured and rejected (`synchronous=NORMAL` gives no power-loss durability
anyway, and `busy_timeout=5000` would let a maintenance transaction stall a nudge for 5s).
The spool is a directory. Read the amendment before implementing.

## The five rules, each with a measurement behind it

Every one of these came out of a prototype run, not from taste. Violating any of them
reintroduces a failure that was actually observed.

| Rule | Why — measured |
|------|----------------|
| The **boundary goes in the filename**: `pending/<path-hash>.<boundary:020d>.json` | One file per path with overwrite lost the higher boundary in **135/300 races** (45%) when a slower producer that measured an earlier EOF landed last. With the boundary in the name: **0/300**. |
| Every write is **`tmp` + `os.replace`**, never a direct write | Direct `write_text` of a 400 KB file with a concurrent reader: **7081 torn reads** vs 664 clean over 1.5 s. Via `os.replace`: 6210 clean, **0** torn. |
| The claim **is** the `os.rename` — no lock, no flag | 40 rounds × 8 racing **processes**: always exactly one winner. `FileNotFoundError` on the loser is the mechanism, not an error. |
| `tmp/` lives **inside** the spool root | `os.rename` is atomic per filesystem. A staging dir on another mount silently degrades to copy+unlink. Never `/tmp`. |
| **No fsync by default** | Threat model is process restart, not power loss — the same guarantee the store gives under `synchronous=NORMAL`. On APFS `os.fsync` does not even reach the media; real durability is `fcntl(F_FULLFSYNC)` at p50 **6.9 ms** per nudge vs 0.13 ms without. Affordable if ever wanted; not the default, and named as a decision. |

⚠️ **Known limitation, deliberately not fixed here.** Claim-by-rename excludes per **job**,
not per **transcript** — and the boundary-in-name rule puts several files under one path.
Measured: 0 overlapping ingests with 1 worker, **14 with 2 workers, 21 with 4**. The worker
is serial (issue #150), so this is latent. Do not add concurrency without also claiming the
*path* via `os.mkdir(running/<path-hash>)` (atomic; `FileExistsError` = taken), which
measured 0 overlaps at 4 workers. Encode this as a docstring warning on `claim_next`, so
whoever implements #150 meets it.

- [ ] **Step 1: Write the failing tests**

`tests/test_background/test_ingest_spool.py` — no fixtures from the rest of the suite are
needed; `tmp_path` is enough.

```python
import json
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

import pytest

from ormah.background.ingest_spool import IngestSpool


def test_enqueue_then_claim_roundtrip(tmp_path):
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/proj/s.jsonl"), boundary=900, reason="nudge")
    job = spool.claim_next()
    assert job is not None
    assert job.path == Path("/x/proj/s.jsonl")
    assert job.boundary == 900
    assert job.reason == "nudge"
    assert spool.claim_next() is None, "a claimed job must not be claimable twice"
    spool.complete(job)
    assert spool.pending_count() == 0


def test_second_nudge_never_lowers_the_boundary(tmp_path):
    """PROTOTYPE S2: overwrite-in-place lost the higher boundary in 45% of races.
    Two nudges for the same path must both survive as files."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=900, reason="nudge")
    spool.enqueue(Path("/x/s.jsonl"), boundary=500, reason="nudge")   # slower producer
    seen = []
    while (job := spool.claim_next()) is not None:
        seen.append(job.boundary)
        spool.complete(job)
    assert max(seen) == 900, "the accepted boundary must never be lost to a later, lower one"


def test_claim_is_exclusive_across_threads(tmp_path):
    """PROTOTYPE S1: the rename IS the mutual exclusion."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=1, reason="nudge")
    winners, barrier = [], threading.Barrier(8)

    def race():
        barrier.wait()
        if spool.claim_next() is not None:
            winners.append(1)

    ts = [threading.Thread(target=race) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(winners) == 1


def test_recover_returns_in_flight_jobs_to_pending(tmp_path):
    """A crash mid-ingest leaves the job in running/. Startup must re-queue it."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/a.jsonl"), boundary=10, reason="nudge")
    spool.enqueue(Path("/x/b.jsonl"), boundary=20, reason="nudge")
    assert spool.claim_next() is not None and spool.claim_next() is not None
    assert spool.pending_count() == 0
    # ---- process dies here ----
    assert spool.recover() == 2
    assert spool.pending_count() == 2


def test_nudge_during_an_in_flight_job_survives_its_completion(tmp_path):
    """PROTOTYPE S3: completing job N must not delete a nudge that arrived while it ran."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=500, reason="nudge")
    job = spool.claim_next()
    spool.enqueue(Path("/x/s.jsonl"), boundary=900, reason="nudge")   # user appended + nudged
    spool.complete(job)
    survivor = spool.claim_next()
    assert survivor is not None and survivor.boundary == 900


def test_a_reader_never_sees_a_partial_job_file(tmp_path):
    """PROTOTYPE S5: direct writes gave 7081 torn reads; os.replace gave 0.
    Enqueue a large payload in a loop while a reader parses every pending file."""
    spool = IngestSpool(tmp_path / "queue")
    torn, stop = [0], threading.Event()

    def writer():
        while not stop.is_set():
            spool.enqueue(Path("/x/" + "d" * 3000 + ".jsonl"), boundary=1, reason="nudge")

    def reader():
        while not stop.is_set():
            for f in list((spool.root / "pending").glob("*.json")):
                try:
                    json.loads(f.read_text())
                except json.JSONDecodeError:
                    torn[0] += 1
                except FileNotFoundError:
                    pass          # claimed/completed between glob and read — not torn
    ts = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in ts:
        t.start()
    time.sleep(1.0)
    stop.set()
    for t in ts:
        t.join()
    assert torn[0] == 0


def test_staging_dir_is_inside_the_root(tmp_path):
    """Rename atomicity is per-filesystem. Staging outside the root silently degrades."""
    spool = IngestSpool(tmp_path / "queue")
    assert (spool.root / "tmp").is_dir()
    assert (spool.root / "tmp").resolve().is_relative_to(spool.root.resolve())


def test_corrupt_job_file_is_quarantined_not_fatal(tmp_path):
    """A hand-edited or half-written-by-an-older-version file must not wedge the worker."""
    spool = IngestSpool(tmp_path / "queue")
    (spool.root / "pending" / "deadbeef.00000000000000000001.json").write_text("{not json")
    assert spool.claim_next() is None      # skipped, not raised
    assert spool.pending_count() == 0      # and not retried forever
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_background/test_ingest_spool.py -v
```

Expected: collection error — the module does not exist.

- [ ] **Step 3: Implement `ingest_spool.py`**

Shape it like this; the details that matter are marked.

```python
"""Durable ingest queue built from directory entries (ADR-0004 Amendment 2026-07-22).

The queue is files, not a table: the server's SQLite runs synchronous=NORMAL (so a
committed INSERT is no more power-loss-durable than a rename) and serializes writes behind
busy_timeout=5000, which would let a maintenance transaction stall the one request path
whose entire purpose is that nobody waits.
"""

_PENDING, _RUNNING, _TMP, _FAILED = "pending", "running", "tmp", "failed"


@dataclass(frozen=True)
class SpoolJob:
    path: Path
    boundary: int
    reason: str
    attempts: int      # drives the persisted backoff -- NEVER a dead-letter cap
    _file: Path        # the claimed file under running/, for complete()


class IngestSpool:
    def __init__(self, root: Path) -> None:
        self.root = root
        for sub in (_PENDING, _RUNNING, _TMP, _FAILED):
            (root / sub).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(path: Path) -> str:
        # realpath: two symlinked spellings of one transcript must collide, not double-ingest
        return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:16]

    def enqueue(self, path: Path, boundary: int, reason: str) -> None:
        payload = json.dumps({"path": str(path), "boundary": int(boundary),
                              "reason": reason, "at": _utcnow_iso(),
                              "attempts": attempts, "not_before": not_before}).encode()
        fd, tmp = tempfile.mkstemp(dir=self.root / _TMP)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            # boundary in the NAME: a second nudge must never overwrite a higher one
            name = f"{self._key(path)}.{int(boundary):020d}.json"
            os.replace(tmp, self.root / _PENDING / name)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
```

`claim_next` — the whole concurrency story lives in six lines:

```python
    def claim_next(self) -> SpoolJob | None:
        """Claim the oldest pending job. The rename IS the mutual exclusion.

        ⚠️ This excludes per JOB, not per TRANSCRIPT. Because a path can have several
        queued boundaries, TWO WORKERS CAN INGEST THE SAME TRANSCRIPT CONCURRENTLY
        (measured: 0 overlaps at 1 worker, 14 at 2, 21 at 4). The worker is serial today
        (issue #150). Before adding concurrency, claim the PATH with
        os.mkdir(running/<key>) -- atomic, FileExistsError means taken -- and sweep that
        path's files into it (measured: 0 overlaps at 4 workers).
        """
        for name in sorted(os.listdir(self.root / _PENDING)):
            try:
                os.rename(self.root / _PENDING / name, self.root / _RUNNING / name)
            except FileNotFoundError:
                continue                     # lost the claim race -- expected, silent
            except OSError as e:
                # council R12 (codex): a blanket `except OSError: continue` hides EIO,
                # EACCES and ENOSPC behind the same silence as a lost race, so a failing
                # filesystem looks like an empty queue.
                logger.error("Spool claim failed on %s: %s", name, e)
                return None                  # back off; do NOT spin over a broken FS
            claimed = self.root / _RUNNING / name
            try:
                raw = claimed.read_text(encoding="utf-8")
            except OSError as e:
                # council R12 (codex): a TRANSIENT read error must never destroy a job the
                # server already answered 202 for. Put it back and surface the error.
                logger.error("Spool read failed on %s: %s -- requeueing", name, e)
                with contextlib.suppress(OSError):
                    os.rename(claimed, self.root / _PENDING / name)
                return None
            try:
                data = json.loads(raw)
                return SpoolJob(Path(data["path"]), int(data["boundary"]),
                                str(data.get("reason", "unknown")),
                                int(data.get("attempts", 0)), claimed)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                # DETERMINISTIC corruption: re-reading will never help. Move to failed/
                # WITH the original bytes plus the error, never unlink -- an accepted
                # nudge must stay recoverable by hand.
                self._dead_letter(claimed, raw, f"{type(e).__name__}: {e}")
        return None
```

⚠️ **The distinction in those three `except` blocks is the finding, not decoration.**
Deleting a job is only ever correct when re-reading it could not possibly help. A lost claim
race is silent; a filesystem error is loud and reversible; only malformed content is
terminal, and even then the bytes are preserved.

`complete` unlinks `job._file` (suppressing `FileNotFoundError` — completion must be
idempotent). `recover` renames every entry under `running/` back to `pending/` and returns
the count; it is called once at startup, before any worker claims. `pending_count` is
`len(os.listdir(...))`.

Also add a **module-level `spool_root(settings) -> Path`** returning
`settings.memory_dir / "ingest_queue"` — the same-filesystem rule is only guaranteed if the
spool lives under `memory_dir`, and centralising it stops a later caller reaching for
`/tmp`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_background/test_ingest_spool.py -v
```

Expected: PASS, all nine.

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/background/ingest_spool.py tests/test_background/test_ingest_spool.py
git commit -m "feat(ingest): durable file-based ingest spool with claim-by-rename (ADR-0004)"
```

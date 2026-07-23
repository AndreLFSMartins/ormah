"""Durable ingest queue built from directory entries (ADR-0004 Amendment 2026-07-22).

The queue is files, not a table: the server's SQLite runs synchronous=NORMAL (so a
committed INSERT is no more power-loss-durable than a rename) and serializes writes behind
busy_timeout=5000, which would let a maintenance transaction stall the one request path
whose entire purpose is that nobody waits.

Five rules, each measured by a prototype run (see the slice-1 plan for the numbers):
  - the boundary lives in the pending filename, never overwritten in place;
  - every write is tmp + os.replace, never a direct write;
  - the claim IS the os.rename -- no lock, no flag;
  - tmp/ lives inside the spool root (rename atomicity is per-filesystem);
  - no fsync by default (the threat model is process restart, not power loss).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PENDING, _RUNNING, _TMP, _FAILED = "pending", "running", "tmp", "failed"

# Backoff for "external" (transient) failures: attempts drive a growing delay, persisted
# in the job payload -- never a cap. A long provider outage must never dead-letter real
# work (ADR-0004 H1: an outage must never discard real data).
_BACKOFF_BASE_SECONDS = 2.0
_BACKOFF_MAX_SECONDS = 300.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SpoolJob:
    path: Path
    boundary: int
    reason: str
    attempts: int      # drives the persisted backoff -- NEVER a dead-letter cap
    _file: Path        # the claimed file under running/, for complete()/requeue()


class IngestSpool:
    """A durable, crash-safe ingest queue made of directory entries.

    Layout under `root`: `pending/`, `running/`, `tmp/`, `failed/`. A job is a small JSON
    file named `<path-hash>.<boundary:020d>.json` -- the boundary lives in the name so a
    second, slower nudge for the same path can never overwrite a higher one already queued.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        for sub in (_PENDING, _RUNNING, _TMP, _FAILED):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(path: Path) -> str:
        # realpath: two symlinked spellings of one transcript must collide, not double-ingest
        return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:16]

    def _write_job(self, name: str, payload: dict, dest_dir: str) -> None:
        """Write `payload` as JSON atomically: stage in tmp/, then os.replace into
        `dest_dir`. Never a direct write -- a direct write of a 400 KB file racing a
        reader measured 7081 torn reads vs 0 via this path."""
        data = json.dumps(payload).encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=self.root / _TMP)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, self.root / dest_dir / name)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def enqueue(self, path: Path, boundary: int, reason: str) -> None:
        """Enqueue a job. The boundary lives in the filename: a second, slower nudge for
        the same path must never overwrite a higher boundary already queued (measured:
        45% loss rate with overwrite-in-place, 0% with the boundary in the name)."""
        payload = {
            "path": str(path),
            "boundary": int(boundary),
            "reason": reason,
            "at": _utcnow_iso(),
            "attempts": 0,
            "not_before": 0.0,
        }
        name = f"{self._key(path)}.{int(boundary):020d}.json"
        self._write_job(name, payload, _PENDING)

    def claim_next(self) -> SpoolJob | None:
        """Claim the oldest due pending job. The rename IS the mutual exclusion.

        ⚠️ This excludes per JOB, not per TRANSCRIPT. Because a path can have several
        queued boundaries, TWO WORKERS CAN INGEST THE SAME TRANSCRIPT CONCURRENTLY
        (measured: 0 overlaps at 1 worker, 14 at 2, 21 at 4). The worker is serial today
        (issue #150). Before adding concurrency, claim the PATH with
        os.mkdir(running/<key>) -- atomic, FileExistsError means taken -- and sweep that
        path's files into it (measured: 0 overlaps at 4 workers).
        """
        now = time.time()
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
                not_before = float(data.get("not_before", 0.0) or 0.0)
                if not_before > now:
                    # backoff not elapsed yet -- put back and keep scanning for other work
                    with contextlib.suppress(OSError):
                        os.rename(claimed, self.root / _PENDING / name)
                    continue
                return SpoolJob(
                    Path(data["path"]),
                    int(data["boundary"]),
                    str(data.get("reason", "unknown")),
                    int(data.get("attempts", 0)),
                    claimed,
                )
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                # DETERMINISTIC corruption: re-reading will never help. Move to failed/
                # WITH the original bytes plus the error, never unlink -- an accepted
                # nudge must stay recoverable by hand.
                self._dead_letter(claimed, raw, f"{type(e).__name__}: {e}")
        return None

    def complete(self, job: SpoolJob) -> None:
        """Mark a job done. Idempotent: completing an already-completed job must not
        raise, since a caller may retry the completion step itself."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(job._file)

    def requeue(self, job: SpoolJob, failure_class: str) -> None:
        """Return a claimed job to pending/, or dead-letter it, keyed on failure CLASS
        -- never on an attempt counter.

        failure_class="external" (provider down, connection refused, timeout, EIO, ...):
        retried FOREVER with exponential backoff persisted in the job payload
        (`attempts`, `not_before`) -- never a cap. Capping retries would send a provider
        outage to the dead-letter queue, which is exactly the H1 rule ADR-0004 exists to
        protect: an outage must never discard real data. The backoff is persisted, not
        held in memory, so a restart mid-outage does not reset every backoff to zero and
        stampede the provider.

        Any other failure_class is treated as deterministic (malformed job, transcript
        deleted, path no longer under any watch root): a retry cannot change the outcome,
        so the job is dead-lettered immediately.
        """
        if failure_class == "external":
            attempts = job.attempts + 1
            delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_MAX_SECONDS)
            payload = {
                "path": str(job.path),
                "boundary": int(job.boundary),
                "reason": job.reason,
                "at": _utcnow_iso(),
                "attempts": attempts,
                "not_before": time.time() + delay,
            }
            name = f"{self._key(job.path)}.{int(job.boundary):020d}.json"
            # write the requeued job to pending/ BEFORE removing it from running/ -- the
            # job must never be lost between the two steps.
            self._write_job(name, payload, _PENDING)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(job._file)
        else:
            try:
                raw = job._file.read_bytes()
            except OSError:
                raw = b""
            self._dead_letter(job._file, raw, f"deterministic failure: {failure_class}")

    def _dead_letter(self, file: Path, raw: str | bytes, error: str) -> None:
        """Move a job to failed/ WITH its original bytes -- never unlink without first
        making that copy durable. An accepted nudge must stay recoverable by hand; this is
        the same principle as the existing skipped_slices quarantine record. The error is
        recorded alongside as a `<name>.error` sidecar, best-effort."""
        raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
        name = file.name
        dest = self.root / _FAILED / name
        fd, tmp = tempfile.mkstemp(dir=self.root / _TMP)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw_bytes)
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        # only now, with a durable copy in failed/, remove the original from running/.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(file)
        with contextlib.suppress(OSError):
            (self.root / _FAILED / f"{name}.error").write_text(error, encoding="utf-8")

    def recover(self) -> int:
        """Return every job left in running/ (a crash mid-ingest) back to pending/.
        Call once at startup, before any worker claims. Returns the count recovered."""
        count = 0
        for name in os.listdir(self.root / _RUNNING):
            try:
                os.rename(self.root / _RUNNING / name, self.root / _PENDING / name)
            except FileNotFoundError:
                continue
            count += 1
        return count

    def pending_count(self) -> int:
        return len(os.listdir(self.root / _PENDING))


def spool_root(settings) -> Path:
    """The one spool-root path every caller must use -- never reach for /tmp. The
    same-filesystem guarantee behind os.rename only holds under `memory_dir`."""
    return Path(settings.memory_dir) / "ingest_queue"


def root_key(watch_dir: Path) -> str:
    """A short stable hash identifying one watch root's spool.

    Roots must not share a queue: a nudge for one root claimed by another root's worker
    would resolve against the wrong cursor."""
    return hashlib.sha256(os.path.realpath(watch_dir).encode()).hexdigest()[:16]

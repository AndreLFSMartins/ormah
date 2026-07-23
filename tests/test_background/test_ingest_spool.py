import json
import threading
import time
from pathlib import Path

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

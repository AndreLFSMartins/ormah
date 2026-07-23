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


def test_stray_non_json_file_in_pending_is_ignored(tmp_path):
    """An editor swap file or sidecar dropped in pending/ must never be scanned or
    claimed -- claim_next and pending_count only look at *.json entries, matching the
    corrupt-.json dead-letter path which must still fire for a malformed FILE THAT ENDS
    IN .json."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=1, reason="nudge")
    (spool.root / "pending" / ".s.jsonl.swp").write_text("not a job")

    assert spool.pending_count() == 1, "the stray non-.json file must not be counted"
    job = spool.claim_next()
    assert job is not None and job.boundary == 1
    # untouched: never claimed, never dead-lettered
    assert (spool.root / "pending" / ".s.jsonl.swp").exists()


def test_claim_next_gates_on_not_before_even_when_only_pending_job(tmp_path):
    """A job whose not_before is in the future must be skipped by claim_next() even
    when it is the only pending job -- this guards against provider-stampede on
    restart mid-outage. Once not_before has elapsed the same job becomes claimable."""
    spool = IngestSpool(tmp_path / "queue")
    future = time.time() + 100
    payload = {
        "path": "/x/s.jsonl",
        "boundary": 1,
        "reason": "nudge",
        "at": "2026-01-01T00:00:00+00:00",
        "attempts": 3,
        "not_before": future,
    }
    job_file = spool.root / "pending" / "abc123.00000000000000000001.json"
    job_file.write_text(json.dumps(payload))

    assert spool.claim_next() is None, "not_before in the future must gate the claim"
    assert spool.pending_count() == 1, "the gated job must remain pending, not lost"

    # elapse the backoff by rewriting not_before into the past -- now claimable
    payload["not_before"] = time.time() - 1
    job_file.write_text(json.dumps(payload))
    job = spool.claim_next()
    assert job is not None
    assert job.boundary == 1
    assert job.attempts == 3


def test_requeue_external_retries_forever_with_persisted_growing_backoff(tmp_path):
    """H1: an external (transient) failure must retry forever with an ever-growing
    backoff persisted in the job payload -- never a cap, never a dead-letter. The
    persistence (not an in-memory counter) is what stops a restart mid-outage from
    resetting every backoff to zero and stampeding the provider."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/s.jsonl"), boundary=1, reason="nudge")
    job = spool.claim_next()
    assert job is not None and job.attempts == 0

    before = time.time()
    spool.requeue(job, failure_class="external")

    # back in pending/, not lost, not dead-lettered
    assert spool.pending_count() == 1
    assert list((spool.root / "running").iterdir()) == []
    assert list((spool.root / "failed").glob("*.json")) == []

    # not immediately claimable right after requeue -- the persisted not_before gates it
    assert spool.claim_next() is None

    pending_files = list((spool.root / "pending").glob("*.json"))
    assert len(pending_files) == 1
    data1 = json.loads(pending_files[0].read_text())
    assert data1["attempts"] == 1, "attempts must be persisted on disk, not just in memory"
    first_delay = data1["not_before"] - before
    assert 1.5 < first_delay <= 2.5, "first backoff must be ~_BACKOFF_BASE_SECONDS (2s)"

    # elapse the backoff by rewriting not_before, without sleeping, and requeue again
    data1["not_before"] = 0.0
    pending_files[0].write_text(json.dumps(data1))
    job2 = spool.claim_next()
    assert job2 is not None and job2.attempts == 1

    before2 = time.time()
    spool.requeue(job2, failure_class="external")
    pending_files2 = list((spool.root / "pending").glob("*.json"))
    assert len(pending_files2) == 1
    data2 = json.loads(pending_files2[0].read_text())
    assert data2["attempts"] == 2
    second_delay = data2["not_before"] - before2
    assert second_delay > first_delay, "backoff must grow monotonically with attempts"
    assert list((spool.root / "failed").glob("*.json")) == [], (
        "an external failure must never be dead-lettered, no matter how many attempts"
    )


def test_requeue_deterministic_failure_dead_letters_with_original_bytes(tmp_path):
    """Any failure_class other than 'external' is deterministic: a retry cannot change
    the outcome, so the job is dead-lettered immediately, with its original bytes plus
    the error class recorded -- and it must never simply be unlinked."""
    spool = IngestSpool(tmp_path / "queue")
    spool.enqueue(Path("/x/gone.jsonl"), boundary=42, reason="nudge")
    job = spool.claim_next()
    assert job is not None
    original_bytes = job._file.read_bytes()

    spool.requeue(job, failure_class="path_not_watched")

    assert spool.pending_count() == 0
    assert list((spool.root / "running").iterdir()) == []
    failed_files = list((spool.root / "failed").glob("*.json"))
    assert len(failed_files) == 1
    assert failed_files[0].read_bytes() == original_bytes, (
        "the dead-lettered job must keep its original bytes, never re-serialized"
    )
    error_sidecar = spool.root / "failed" / f"{failed_files[0].name}.error"
    assert error_sidecar.exists()
    assert "path_not_watched" in error_sidecar.read_text()

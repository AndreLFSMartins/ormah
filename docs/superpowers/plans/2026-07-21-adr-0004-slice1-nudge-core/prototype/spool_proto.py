#!/usr/bin/env python3
"""PROTOTYPE — THROWAWAY. Do not merge.

Question: does a directory spool with claim-by-rename close the ADR-0004 ingest
queue design WITHOUT extra state?

Nothing here imports ormah. It tests OS semantics + the state model only.
Run: python3 spool_proto.py
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import tempfile
import threading
import time
from pathlib import Path

random.seed(7)

# ---------------------------------------------------------------- spool basics


def key_for(path: str) -> str:
    return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:16]


def enqueue_overwrite(root: Path, path: str, boundary: int) -> None:
    """VARIANT A: one file per path; a second nudge OVERWRITES it."""
    payload = json.dumps({"path": path, "boundary": boundary}).encode()
    fd, tmp = tempfile.mkstemp(dir=root / "tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, root / "pending" / f"{key_for(path)}.json")


def enqueue_boundary_in_name(root: Path, path: str, boundary: int) -> None:
    """VARIANT B: boundary is part of the filename; nudges never overwrite."""
    payload = json.dumps({"path": path, "boundary": boundary}).encode()
    fd, tmp = tempfile.mkstemp(dir=root / "tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, root / "pending" / f"{key_for(path)}.{boundary:020d}.json")


def claim(root: Path, name: str) -> Path | None:
    """The claim IS the rename. Winner gets the path, everyone else gets None."""
    src = root / "pending" / name
    dst = root / "running" / name
    try:
        os.rename(src, dst)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return dst


def fresh_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="PROTOTYPE-spool-WIPE-ME-"))
    for sub in ("pending", "running", "tmp"):
        (root / sub).mkdir()
    return root


def show(title: str, verdict: str, detail: str) -> None:
    mark = "PASS" if verdict == "PASS" else ("FAIL" if verdict == "FAIL" else "····")
    print(f"[{mark}] {title}\n       {detail}")


# ------------------------------------------------- S1: claim exclusivity (procs)


def _racer(root_s: str, name: str, out) -> None:
    # spin so the processes actually overlap on the rename
    time.sleep(0.05)
    won = claim(Path(root_s), name) is not None
    out.put(won)


def s1_claim_exclusivity(rounds: int = 40, racers: int = 8) -> None:
    winners_seen = []
    for _ in range(rounds):
        root = fresh_root()
        enqueue_overwrite(root, "/x/session.jsonl", 100)
        name = os.listdir(root / "pending")[0]
        q = mp.Queue()
        procs = [mp.Process(target=_racer, args=(str(root), name, q)) for _ in range(racers)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        winners = sum(q.get() for _ in range(racers))
        winners_seen.append(winners)
        shutil.rmtree(root)
    ok = set(winners_seen) == {1}
    show(
        "S1  claim-by-rename is exclusive across PROCESSES",
        "PASS" if ok else "FAIL",
        f"{rounds} rounds x {racers} processes -> winners per round: {sorted(set(winners_seen))} "
        f"(expected exactly {{1}})",
    )


# ------------------------------------------ S2: boundary regression under nudges


def s2_boundary_regression() -> None:
    """Two nudges for the same path race. The LOWER boundary must never win."""
    for variant, enq in (("A overwrite", enqueue_overwrite), ("B boundary-in-name", enqueue_boundary_in_name)):
        regressions = 0
        lost = 0
        rounds = 300
        for _ in range(rounds):
            root = fresh_root()
            # slow producer measured EOF earlier (lower boundary) but lands later
            def slow():
                time.sleep(random.uniform(0, 0.002))
                enq(root, "/x/s.jsonl", 500)

            def fast():
                time.sleep(random.uniform(0, 0.002))
                enq(root, "/x/s.jsonl", 900)

            t1, t2 = threading.Thread(target=slow), threading.Thread(target=fast)
            t1.start(), t2.start(), t1.join(), t2.join()

            names = sorted(os.listdir(root / "pending"))
            boundaries = [
                json.loads((root / "pending" / n).read_text())["boundary"] for n in names
            ]
            # what the worker would actually ingest up to, draining everything queued
            reachable = max(boundaries)
            if reachable < 900:
                regressions += 1
            if 900 not in boundaries:
                lost += 1
            shutil.rmtree(root)
        show(
            f"S2  no boundary regression  [variant {variant}]",
            "PASS" if regressions == 0 else "FAIL",
            f"{rounds} races: {regressions} rounds where the queue's max boundary was "
            f"BELOW the real EOF (900); the 900-nudge was absent in {lost}",
        )


# --------------------------------------- S3: nudge arriving while job is running


def s3_nudge_during_run() -> None:
    root = fresh_root()
    enqueue_boundary_in_name(root, "/x/s.jsonl", 500)
    name = os.listdir(root / "pending")[0]
    claimed = claim(root, name)          # worker starts ingesting up to 500
    enqueue_boundary_in_name(root, "/x/s.jsonl", 900)   # user appends + nudges again
    still_pending = os.listdir(root / "pending")
    os.unlink(claimed)                   # worker finishes and deletes ITS file
    after = os.listdir(root / "pending")
    ok = len(still_pending) == 1 and len(after) == 1
    show(
        "S3  nudge during an in-flight job survives",
        "PASS" if ok else "FAIL",
        f"queued while running: {still_pending} | after worker cleanup: {after} "
        f"(the 900 job must outlive the 500 job's completion)",
    )
    shutil.rmtree(root)


# ------------------------------------------------------- S4: crash recovery


def s4_crash_recovery() -> None:
    root = fresh_root()
    for b in (100, 200):
        enqueue_boundary_in_name(root, f"/x/s{b}.jsonl", b)
    for n in list(os.listdir(root / "pending")):
        claim(root, n)                    # two jobs in flight
    # ---- process dies here ----
    swept = 0
    for n in list(os.listdir(root / "running")):
        os.rename(root / "running" / n, root / "pending" / n)
        swept += 1
    ok = swept == 2 and len(os.listdir(root / "pending")) == 2 and not os.listdir(root / "running")
    show(
        "S4  startup sweep returns in-flight jobs to pending",
        "PASS" if ok else "FAIL",
        f"swept {swept}; pending={sorted(os.listdir(root / 'pending'))}; "
        f"running={os.listdir(root / 'running')}",
    )
    shutil.rmtree(root)


# ------------------------------------------- S5: torn write, direct vs rename


def s5_torn_write() -> None:
    payload = json.dumps({"path": "/x/s.jsonl", "boundary": 1, "pad": "z" * 400_000})
    for label, use_rename in (("direct write_text", False), ("tmp + os.replace", True)):
        root = fresh_root()
        target = root / "pending" / "j.json"
        target.write_text(payload)
        stop = threading.Event()
        torn = [0]
        reads = [0]

        def writer():
            while not stop.is_set():
                if use_rename:
                    fd, tmp = tempfile.mkstemp(dir=root / "tmp")
                    with os.fdopen(fd, "w") as fh:
                        fh.write(payload)
                    os.replace(tmp, target)
                else:
                    target.write_text(payload)

        def reader():
            while not stop.is_set():
                try:
                    json.loads(target.read_text())
                    reads[0] += 1
                except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError):
                    torn[0] += 1

        ts = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in ts:
            t.start()
        time.sleep(1.5)
        stop.set()
        for t in ts:
            t.join()
        show(
            f"S5  reader never sees a partial file  [{label}]",
            "PASS" if torn[0] == 0 else "FAIL",
            f"{reads[0]} clean reads, {torn[0]} TORN reads over 1.5s of 400KB rewrites",
        )
        shutil.rmtree(root)


# ------------------------------------- S6: realistic 3-producer / 2-worker drain


def s6_full_drain() -> None:
    root = fresh_root()
    paths = [f"/x/proj/s{i}.jsonl" for i in range(12)]
    truth: dict[str, int] = {}
    lock = threading.Lock()
    stop = threading.Event()
    overlap = []
    inflight: set[str] = set()
    ingested: dict[str, int] = {}

    def producer(tag: str, n: int):
        for _ in range(n):
            p = random.choice(paths)
            with lock:
                truth[p] = truth.get(p, 0) + random.randint(50, 500)
                b = truth[p]
            enqueue_boundary_in_name(root, p, b)
            time.sleep(random.uniform(0, 0.004))

    def worker():
        idle = 0
        while idle < 40:
            names = sorted(os.listdir(root / "pending"))
            if not names:
                idle += 1
                time.sleep(0.005)
                continue
            idle = 0
            got = claim(root, names[0])
            if got is None:
                continue
            job = json.loads(got.read_text())
            p, b = job["path"], job["boundary"]
            with lock:
                if p in inflight:
                    overlap.append(p)      # two workers on the same transcript = bug
                inflight.add(p)
            time.sleep(random.uniform(0, 0.006))   # "extraction"
            with lock:
                ingested[p] = max(ingested.get(p, 0), b)
                inflight.discard(p)
            os.unlink(got)

    prods = [threading.Thread(target=producer, args=(t, 25)) for t in ("nudge", "observer", "reconcile")]
    works = [threading.Thread(target=worker) for _ in range(2)]
    for t in prods + works:
        t.start()
    for t in prods:
        t.join()
    for t in works:
        t.join()

    behind = {p: (truth[p], ingested.get(p, 0)) for p in truth if ingested.get(p, 0) < truth[p]}
    leftovers = os.listdir(root / "pending") + os.listdir(root / "running")
    ok = not overlap and not behind and not leftovers
    show(
        "S6  3 producers / 2 workers: no overlap, nothing stranded",
        "PASS" if ok else "FAIL",
        f"same-path overlaps={len(overlap)}; paths ingested below their real EOF={len(behind)} "
        f"{list(behind.items())[:3]}; queue leftovers={len(leftovers)}",
    )
    shutil.rmtree(root)


if __name__ == "__main__":
    print("PROTOTYPE — directory spool with claim-by-rename (ADR-0004 ingest queue)\n")
    s1_claim_exclusivity()
    s2_boundary_regression()
    s3_nudge_during_run()
    s4_crash_recovery()
    s5_torn_write()
    s6_full_drain()

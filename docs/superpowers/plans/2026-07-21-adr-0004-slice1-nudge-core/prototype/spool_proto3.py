#!/usr/bin/env python3
"""PROTOTYPE part 3 — THROWAWAY. Two questions the ADR must answer with numbers:
   A) what does power-loss durability (fsync file + dir) actually cost per nudge?
   B) is the flock-on-the-inode trap real, and does a stable lockfile fix it?
"""
import fcntl, json, os, shutil, statistics, tempfile, threading, time
from pathlib import Path

# ---- A: fsync cost -----------------------------------------------------------
root = Path(tempfile.mkdtemp(prefix="PROTOTYPE-fsync-WIPE-ME-"))
(root / "pending").mkdir(); (root / "tmp").mkdir()
payload = json.dumps({"path": "/x/s.jsonl", "boundary": 91234}).encode()

def enqueue(sync: bool) -> float:
    t0 = time.perf_counter()
    fd, tmp = tempfile.mkstemp(dir=root / "tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        if sync:
            fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, root / "pending" / "j.json")
    if sync:
        dfd = os.open(root / "pending", os.O_RDONLY)
        os.fsync(dfd); os.close(dfd)
    return (time.perf_counter() - t0) * 1000

for sync in (False, True):
    for _ in range(20): enqueue(sync)              # warm
    xs = sorted(enqueue(sync) for _ in range(300))
    print(f"[····] A  enqueue {'COM fsync (file+dir)' if sync else 'SEM fsync':24s} "
          f"p50={statistics.median(xs):6.3f}ms  p95={xs[int(.95*len(xs))]:6.3f}ms  max={xs[-1]:6.3f}ms")
shutil.rmtree(root)

# ---- B: flock inode trap -----------------------------------------------------
def outbox_run(stable_lockfile: bool):
    d = Path(tempfile.mkdtemp(prefix="PROTOTYPE-flock-WIPE-ME-"))
    outbox = d / "outbox.jsonl"; outbox.touch()
    lockpath = d / "outbox.lock" if stable_lockfile else outbox
    if stable_lockfile: lockpath.touch()
    drained, appended = [], []
    stop = threading.Event()

    def lock_fd():
        fd = os.open(lockpath, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def appender():
        i = 0
        while not stop.is_set():
            fd = lock_fd()
            try:
                with open(outbox, "a") as fh:
                    fh.write(json.dumps({"n": i}) + "\n")
                appended.append(i); i += 1
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
            time.sleep(0.0002)

    def drainer():
        while not stop.is_set():
            fd = lock_fd()
            try:
                lines = outbox.read_text().splitlines() if outbox.exists() else []
                for ln in lines:
                    if ln.strip(): drained.append(json.loads(ln)["n"])
                # rotate: the classic "drain then truncate by replacing the file"
                tmp = d / "outbox.tmp"; tmp.write_text("")
                os.replace(tmp, outbox)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
            time.sleep(0.003)

    ts = [threading.Thread(target=appender), threading.Thread(target=drainer)]
    for t in ts: t.start()
    time.sleep(2.0); stop.set()
    for t in ts: t.join()
    # anything appended but never drained (and not still sitting in the file) is LOST
    tail = [json.loads(l)["n"] for l in outbox.read_text().splitlines() if l.strip()]
    lost = sorted(set(appended) - set(drained) - set(tail))
    shutil.rmtree(d)
    return len(appended), len(lost)

for stable in (False, True):
    n, lost = outbox_run(stable)
    label = "lock no LOCKFILE estável" if stable else "lock no PRÓPRIO outbox (inode)"
    mark = "PASS" if lost == 0 else "FAIL"
    print(f"[{mark}] B  outbox: {label:32s} {n} appends, {lost} eventos PERDIDOS")

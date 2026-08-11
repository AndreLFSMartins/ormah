#!/usr/bin/env python3
"""PROTOTYPE part 2 — isolate the S6 overlap. THROWAWAY."""
import json, os, random, shutil, threading, time
from pathlib import Path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spool_proto import fresh_root, enqueue_boundary_in_name, claim, key_for, show

random.seed(11)

def run_drain(n_workers: int, path_claim: bool):
    root = fresh_root()
    paths = [f"/x/proj/s{i}.jsonl" for i in range(12)]
    truth, ingested, inflight, overlap = {}, {}, set(), []
    lock = threading.Lock()

    def producer(n):
        for _ in range(n):
            p = random.choice(paths)
            with lock:
                truth[p] = truth.get(p, 0) + random.randint(50, 500)
                b = truth[p]
            enqueue_boundary_in_name(root, p, b)
            time.sleep(random.uniform(0, 0.004))

    def claim_path(name):
        """Claim the whole PATH via mkdir (atomic, EEXIST = taken), then sweep its files."""
        h = name.split(".")[0]
        d = root / "running" / h
        try:
            os.mkdir(d)
        except FileExistsError:
            return None
        moved = []
        for n in sorted(os.listdir(root / "pending")):
            if n.startswith(h + "."):
                try:
                    os.rename(root / "pending" / n, d / n)
                    moved.append(d / n)
                except FileNotFoundError:
                    pass
        if not moved:
            os.rmdir(d)
            return None
        return moved

    def worker():
        idle = 0
        while idle < 40:
            names = sorted(os.listdir(root / "pending"))
            if not names:
                idle += 1; time.sleep(0.005); continue
            idle = 0
            if path_claim:
                got = claim_path(names[0])
                if got is None: continue
                jobs = [json.loads(Path(f).read_text()) for f in got]
                p = jobs[0]["path"]; b = max(j["boundary"] for j in jobs)
            else:
                f = claim(root, names[0])
                if f is None: continue
                j = json.loads(f.read_text()); p, b, got = j["path"], j["boundary"], [f]
            with lock:
                if p in inflight: overlap.append(p)
                inflight.add(p)
            time.sleep(random.uniform(0, 0.006))
            with lock:
                ingested[p] = max(ingested.get(p, 0), b)
                inflight.discard(p)
            for f in got: os.unlink(f)
            if path_claim: os.rmdir(Path(got[0]).parent)

    prods = [threading.Thread(target=producer, args=(25,)) for _ in range(3)]
    works = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in prods + works: t.start()
    for t in prods: t.join()
    for t in works: t.join()
    behind = {p: (truth[p], ingested.get(p, 0)) for p in truth if ingested.get(p, 0) < truth[p]}
    left = os.listdir(root / "pending") + os.listdir(root / "running")
    shutil.rmtree(root)
    return len(overlap), len(behind), len(left)

for label, nw, pc in (("1 worker, file-claim (design atual, #150 serial)", 1, False),
                      ("2 workers, file-claim", 2, False),
                      ("4 workers, file-claim", 4, False),
                      ("4 workers, PATH-claim via mkdir", 4, True)):
    ov, bh, lf = run_drain(nw, pc)
    show(label, "PASS" if ov == 0 and bh == 0 and lf == 0 else "FAIL",
         f"overlaps={ov}  paths abaixo do EOF real={bh}  sobras na fila={lf}")

#!/usr/bin/env python3
"""PROTOTYPE part 4 — THROWAWAY. Corrige dois erros do part 3:
   A) no macOS, os.fsync NAO garante durabilidade contra queda de energia;
      o real e fcntl(F_FULLFSYNC). Medir os dois.
   B) o trap do inode so aparece com >=2 appenders E com o fd aberto ANTES do
      replace. Detectar VIOLACAO DE EXCLUSAO, nao perda de bytes.
"""
import fcntl, json, os, shutil, statistics, tempfile, threading, time
from pathlib import Path

F_FULLFSYNC = 51  # <sys/fcntl.h>, macOS

root = Path(tempfile.mkdtemp(prefix="PROTOTYPE-fsync-WIPE-ME-"))
(root / "pending").mkdir(); (root / "tmp").mkdir()
payload = json.dumps({"path": "/x/s.jsonl", "boundary": 91234}).encode()

def enqueue(mode: str) -> float:
    t0 = time.perf_counter()
    fd, tmp = tempfile.mkstemp(dir=root / "tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload); fh.flush()
        if mode == "fsync": os.fsync(fh.fileno())
        elif mode == "fullfsync": fcntl.fcntl(fh.fileno(), F_FULLFSYNC)
    os.replace(tmp, root / "pending" / "j.json")
    if mode != "none":
        dfd = os.open(root / "pending", os.O_RDONLY)
        os.fsync(dfd) if mode == "fsync" else fcntl.fcntl(dfd, F_FULLFSYNC)
        os.close(dfd)
    return (time.perf_counter() - t0) * 1000

for mode, label in (("none", "SEM sync"), ("fsync", "os.fsync (NAO e durable no APFS)"),
                    ("fullfsync", "F_FULLFSYNC (durabilidade real)")):
    for _ in range(10): enqueue(mode)
    n = 300 if mode != "fullfsync" else 60
    xs = sorted(enqueue(mode) for _ in range(n))
    print(f"[····] A  enqueue {label:34s} p50={statistics.median(xs):7.3f}ms  "
          f"p95={xs[int(.95*len(xs))]:7.3f}ms  max={xs[-1]:7.3f}ms   (n={n})")
shutil.rmtree(root)

def outbox_run(stable_lockfile: bool, appenders: int = 3, secs: float = 2.0):
    d = Path(tempfile.mkdtemp(prefix="PROTOTYPE-flock-WIPE-ME-"))
    outbox = d / "outbox.jsonl"; outbox.touch()
    lockfile = d / "outbox.lock"; lockfile.touch()
    stop = threading.Event()
    in_cs = []          # quem esta na secao critica agora
    violations = [0]
    guard = threading.Lock()

    def acquire():
        # ESTE e o ponto: o fd e aberto UMA vez e reusado (o caso real de um
        # processo de longa duracao), e o flock trava o INODE desse fd.
        path = lockfile if stable_lockfile else outbox
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def enter(who):
        with guard:
            if in_cs: violations[0] += 1
            in_cs.append(who)
    def leave(who):
        with guard: in_cs.remove(who)

    def appender(i):
        n = 0
        while not stop.is_set():
            fd = acquire()
            enter(f"app{i}")
            with open(outbox, "a") as fh: fh.write(json.dumps({"a": i, "n": n}) + "\n")
            n += 1
            time.sleep(0.0005)
            leave(f"app{i}")
            fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

    def drainer():
        while not stop.is_set():
            fd = acquire()
            enter("drain")
            tmp = d / "outbox.tmp"; tmp.write_text("")
            os.replace(tmp, outbox)          # <-- troca o inode do outbox
            time.sleep(0.0005)
            leave("drain")
            fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
            time.sleep(0.002)

    ts = [threading.Thread(target=appender, args=(i,)) for i in range(appenders)]
    ts.append(threading.Thread(target=drainer))
    for t in ts: t.start()
    time.sleep(secs); stop.set()
    for t in ts: t.join()
    shutil.rmtree(d)
    return violations[0]

for stable in (False, True):
    v = outbox_run(stable)
    label = "lock no LOCKFILE estavel" if stable else "lock no PROPRIO outbox (inode)"
    print(f"[{'PASS' if v == 0 else 'FAIL'}] B  {label:32s} {v} violacoes de exclusao mutua")

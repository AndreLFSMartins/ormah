# Task 5: Standalone FSEvents leak monitor (Part B, diagnostic)

A standalone script that proves *why* FSEvents misses events, without touching production.
It logs events by type (including `on_moved`, which the production handler does NOT implement),
enables watchdog's own native-flag DEBUG line (`is_coalesced` / `must_scan_subdirs` / `*_dropped`),
and every N seconds diffs disk truth vs. events seen to name the leaked files.

**Files:**
- Create: `scripts/diag/fsevents_monitor.py`

- [ ] **Step 1: Create the script**

Create `scripts/diag/fsevents_monitor.py`:

```python
#!/usr/bin/env python3
"""Standalone FSEvents leak monitor (diagnostic for r-spade/ormah#59).

Proves WHY the session-watcher's live path misses some transcripts, WITHOUT touching
production code. Run it alongside the server across a sleep/wake cycle and a heavy day,
then read the log. It:
  1. Logs every watchdog event by TYPE (created/modified/MOVED/deleted). The production
     handler implements only on_created/on_modified — a transcript written via
     rename/atomic-replace arrives as on_moved and is missed deterministically.
  2. Enables watchdog's FSEvents DEBUG line: the raw native flags per event
     (is_coalesced / must_scan_subdirs / *_dropped) — the kernel saying it dropped events.
  3. Every --poll seconds, diffs disk truth vs. events: files whose mtime advanced but for
     which NO event fired in the window = the leaks.

Usage:
  uv run --with watchdog python scripts/diag/fsevents_monitor.py \
      --dir ~/.claude/projects --poll 30 --log /tmp/fsevents_monitor.log
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger("fsevents_monitor")


class LoggingHandler(FileSystemEventHandler):
    def __init__(self, seen: set[str], lock: threading.Lock) -> None:
        self._seen = seen
        self._lock = lock

    def _record(self, kind: str, path: str) -> None:
        if not path.endswith(".jsonl"):
            return
        with self._lock:
            self._seen.add(path)
        log.info("EVENT %-9s %s", kind, path)

    def on_created(self, event):
        if not event.is_directory:
            self._record("created", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._record("modified", event.src_path)

    def on_moved(self, event):
        # The production handler does NOT implement this — a leak if it fires for .jsonl.
        if not event.is_directory:
            self._record("MOVED", getattr(event, "dest_path", event.src_path))

    def on_deleted(self, event):
        if not event.is_directory:
            self._record("deleted", event.src_path)


def poll_disk_truth(root: Path, seen: set[str], lock: threading.Lock,
                    interval: float, stop: threading.Event) -> None:
    last_mtimes: dict[str, float] = {}
    while not stop.wait(interval):
        with lock:
            events_this_window = set(seen)
            seen.clear()
        leaks = []
        for f in root.rglob("*.jsonl"):
            if "subagents" in f.parts:
                continue
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            key = str(f)
            advanced = key not in last_mtimes or m > last_mtimes[key]
            last_mtimes[key] = m
            if advanced and key not in events_this_window:
                leaks.append(key)
        if leaks:
            log.warning("LEAK %d file(s) advanced on disk with NO fsevent this window:", len(leaks))
            for k in leaks:
                log.warning("  LEAK %s", k)
        else:
            log.info("poll ok: every advanced file had an event")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="~/.claude/projects")
    ap.add_argument("--poll", type=float, default=30.0)
    ap.add_argument("--log", default="/tmp/fsevents_monitor.log")
    ap.add_argument("--duration", type=float, default=0.0, help="seconds; 0 = until Ctrl-C")
    args = ap.parse_args()

    logging.basicConfig(
        filename=args.log, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().addHandler(logging.StreamHandler())
    # Raw native FSEvents flags (is_coalesced / must_scan_subdirs / *_dropped):
    logging.getLogger("watchdog.observers.fsevents").setLevel(logging.DEBUG)

    root = Path(args.dir).expanduser().resolve()
    seen: set[str] = set()
    lock = threading.Lock()
    stop = threading.Event()

    observer = Observer()
    observer.schedule(LoggingHandler(seen, lock), str(root), recursive=True)
    observer.start()
    log.info("fsevents_monitor watching %s (poll=%ss, log=%s)", root, args.poll, args.log)

    poller = threading.Thread(
        target=poll_disk_truth, args=(root, seen, lock, args.poll, stop), daemon=True,
    )
    poller.start()

    deadline = time.time() + args.duration if args.duration else None
    try:
        while True:
            time.sleep(5)
            log.info("observer.is_alive=%s", observer.is_alive())
            if deadline and time.time() >= deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        observer.stop()
        observer.join(timeout=5)
        log.info("fsevents_monitor stopped")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test it (35s) against a synthetic write**

```bash
mkdir -p /tmp/fsmon_test
( sleep 8; printf '{"x":1}\n' >> /tmp/fsmon_test/probe.jsonl; \
  sleep 5; printf '{"x":2}\n' >> /tmp/fsmon_test/probe.jsonl ) &
uv run --with watchdog python scripts/diag/fsevents_monitor.py \
    --dir /tmp/fsmon_test --poll 10 --duration 35 --log /tmp/fsmon_test.log
```

Expected (in `/tmp/fsmon_test.log`): at least one `EVENT created`/`EVENT modified probe.jsonl`,
periodic `observer.is_alive=True`, and `poll ok` lines. Clean up: `rm -rf /tmp/fsmon_test /tmp/fsmon_test.log`.

- [ ] **Step 3: Commit**

```bash
git add scripts/diag/fsevents_monitor.py
git commit -m "feat(diag): standalone FSEvents leak monitor for session-watcher (#59)"
```

## After the plan: real run

Run the monitor ~1 day alongside the server (across a sleep/wake cycle):

```bash
nohup uv run --with watchdog python scripts/diag/fsevents_monitor.py \
    --dir ~/.claude/projects --poll 60 --log /tmp/fsevents_monitor.log >/dev/null 2>&1 &
```

Read `/tmp/fsevents_monitor.log` for `LEAK` lines + the native flags that accompanied them, and
fold the evidence into r-spade/ormah#59.

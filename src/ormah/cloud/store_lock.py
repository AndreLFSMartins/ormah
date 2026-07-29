"""Cross-process lock for operations that act on one local memory store."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading

from filelock import FileLock, Timeout as FileLockTimeout


DEFAULT_STORE_LOCK_TIMEOUT = 30.0


class StoreLockTimeout(TimeoutError):
    """Raised when another process keeps a memory store busy past the timeout."""


@dataclass
class _LockEntry:
    thread_lock: threading.RLock
    process_lock: FileLock


_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: dict[Path, _LockEntry] = {}


def canonical_memory_dir(memory_dir: Path) -> Path:
    """Return the stable local identity used for locking one memory directory."""
    return Path(memory_dir).expanduser().resolve(strict=False)


def store_lock_path(memory_dir: Path) -> Path:
    """Return the lock path without consulting cloud enrollment or ``store_id``."""
    return canonical_memory_dir(memory_dir) / ".ormah" / "store.lock"


def _entry_for(path: Path) -> _LockEntry:
    with _REGISTRY_GUARD:
        entry = _LOCK_REGISTRY.get(path)
        if entry is None:
            entry = _LockEntry(threading.RLock(), FileLock(str(path)))
            _LOCK_REGISTRY[path] = entry
        return entry


class StoreLock:
    """A re-entrant, cross-process exclusive lock for a canonical memory path.

    All callers derive the lock from the resolved memory directory. Cloud store IDs are
    deliberately irrelevant so local-only, enrolled, and future sync operations cannot split
    into different lock domains.
    """

    def __init__(
        self,
        memory_dir: Path,
        *,
        timeout: float = DEFAULT_STORE_LOCK_TIMEOUT,
    ) -> None:
        self.memory_dir = canonical_memory_dir(memory_dir)
        self.path = store_lock_path(self.memory_dir)
        self.timeout = timeout
        self._entry = _entry_for(self.path)
        self._depth = 0

    def acquire(self) -> StoreLock:
        self._entry.thread_lock.acquire()
        process_acquired = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._entry.process_lock.acquire(timeout=self.timeout)
                process_acquired = True
            except FileLockTimeout as exc:
                raise StoreLockTimeout(
                    f"Memory store is busy; timed out waiting for {self.path}."
                ) from exc
            os.chmod(self.path, 0o600)
        except BaseException:
            if process_acquired:
                self._entry.process_lock.release()
            self._entry.thread_lock.release()
            raise
        self._depth += 1
        return self

    def release(self) -> None:
        if self._depth == 0:
            raise RuntimeError("StoreLock is not held")
        self._depth -= 1
        try:
            self._entry.process_lock.release()
        finally:
            self._entry.thread_lock.release()

    def __enter__(self) -> StoreLock:
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

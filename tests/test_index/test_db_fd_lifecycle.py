"""Ephemeral threads must not leak their per-thread SQLite connection (FD-leak regression)."""
from __future__ import annotations

import gc
import threading
import weakref

from ormah.index.db import Database


def test_ephemeral_thread_connection_is_retired(tmp_path):
    db = Database(tmp_path / "t.db")
    db.init_schema()  # opens the main-thread connection
    baseline = len(db._all_conns)

    def worker():
        db.conn.execute("SELECT 1").fetchone()  # forces a new per-thread connection

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # `t` still holds a strong ref to the last thread after the loop above (the loop
    # variable outlives the loop) — drop it explicitly, or that one thread never dies.
    del threads, t
    gc.collect()  # run the weakref finalizers for the now-dead threads

    assert len(db._all_conns) <= baseline


def test_close_releases_the_database_for_gc(tmp_path):
    """close() must detach the per-thread finalizers.

    A finalizer holds strong refs to its callback and args, so a bound
    `_retire_connection` pins the whole Database until the OWNING thread dies. On a
    long-lived thread (the main thread, a pool worker) that is never — every closed
    temporary Database would stay resident for the process lifetime.
    """
    db = Database(tmp_path / "t.db")
    db.init_schema()  # opens a connection on this (long-lived) thread
    db.close()

    ref = weakref.ref(db)
    del db
    gc.collect()

    assert ref() is None

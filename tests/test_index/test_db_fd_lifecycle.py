"""Ephemeral threads must not leak their per-thread SQLite connection (FD-leak regression)."""
from __future__ import annotations

import gc
import threading
import weakref

from ormah.index.db import Database


def test_ephemeral_thread_connection_is_retired(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
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
    finally:
        db.close()


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


def test_retire_connection_is_reentrant_under_the_conns_lock(tmp_path):
    """A finalizer can fire while the same thread already holds the registry lock.

    CPython runs weakref callbacks from the generational GC, which triggers on
    allocation — including an allocation inside `_new_connection`'s own critical
    section. If a dead thread is collected right there, `_retire_connection` re-enters
    the lock on the very thread that holds it. With a plain Lock that is a hard deadlock,
    and it does not end with the test: the finalizers still registered run at interpreter
    exit and hang there too.

    Probed non-blockingly rather than by actually deadlocking, precisely because a real
    deadlock here takes the whole test process down with it.
    """
    db = Database(tmp_path / "t.db")
    try:
        conn = db.conn

        with db._conns_lock:
            reentrant = db._conns_lock.acquire(blocking=False)
            if reentrant:
                db._conns_lock.release()
                db._retire_connection(conn)  # the real callback path, now provably safe

        assert reentrant, "_retire_connection would deadlock: _conns_lock is not re-entrant"
    finally:
        db.close()

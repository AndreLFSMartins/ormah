from __future__ import annotations

from dataclasses import replace
from multiprocessing import get_context
import os
from pathlib import Path
import stat
import time
import uuid

import pytest

from ormah.cloud import store_lock
from ormah.cloud.state import CloudState, load_state, mutate_state, update_state
from ormah.cloud.store_lock import StoreLock, StoreLockTimeout, store_lock_path


def _hold_store_lock(memory_dir: str, acquired, release) -> None:
    with StoreLock(Path(memory_dir), timeout=5):
        acquired.set()
        if not release.wait(5):
            raise RuntimeError("test did not release store lock")


def _slow_upload_update(
    store_id: str,
    state_dir: str,
    memory_dir: str,
    entered,
    release,
) -> None:
    def transform(state: CloudState) -> CloudState:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test did not release state transform")
        return replace(state, last_upload_snapshot_id="01UPLOAD")

    mutate_state(
        store_id,
        transform,
        state_dir=Path(state_dir),
        memory_dir=Path(memory_dir),
        lock_timeout=5,
    )


def _verify_update(store_id: str, state_dir: str, memory_dir: str) -> None:
    update_state(
        store_id,
        state_dir=Path(state_dir),
        memory_dir=Path(memory_dir),
        lock_timeout=5,
        last_verify_error="verification pending",
    )


def test_lock_identity_uses_canonical_memory_path_and_not_store_id(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    alias = tmp_path / "memory-alias"
    alias.symlink_to(memory_dir, target_is_directory=True)

    before_enrollment = store_lock_path(memory_dir)
    (memory_dir / ".store_id").write_text(str(uuid.uuid4()) + "\n", encoding="utf-8")

    assert store_lock_path(memory_dir) == before_enrollment
    assert store_lock_path(alias) == before_enrollment
    assert before_enrollment == memory_dir.resolve() / ".ormah" / "store.lock"


def test_store_lock_is_owner_only_and_blocks_another_process(tmp_path):
    memory_dir = tmp_path / "memory"
    context = get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_store_lock,
        args=(str(memory_dir), acquired, release),
    )
    holder.start()
    try:
        assert acquired.wait(5)
        assert stat.S_IMODE(store_lock_path(memory_dir).stat().st_mode) == 0o600
        with pytest.raises(StoreLockTimeout, match="Memory store is busy"):
            with StoreLock(memory_dir, timeout=0.1):
                pass
    finally:
        release.set()
        holder.join(5)

    assert holder.exitcode == 0


def test_two_process_state_updates_preserve_both_writers(tmp_path):
    memory_dir = tmp_path / "memory"
    state_dir = tmp_path / "state"
    store_id = str(uuid.uuid4())
    context = get_context("spawn")
    entered = context.Event()
    release = context.Event()
    first = context.Process(
        target=_slow_upload_update,
        args=(store_id, str(state_dir), str(memory_dir), entered, release),
    )
    second = context.Process(
        target=_verify_update,
        args=(store_id, str(state_dir), str(memory_dir)),
    )

    first.start()
    try:
        assert entered.wait(5)
        second.start()
        time.sleep(0.2)
        assert second.is_alive(), "second writer did not wait for the store lock"
    finally:
        release.set()
        first.join(5)
        if second.pid is not None:
            second.join(5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    state = load_state(store_id, state_dir=state_dir)
    assert state.last_upload_snapshot_id == "01UPLOAD"
    assert state.last_verify_error == "verification pending"


def test_store_lock_is_reentrant_in_one_thread(tmp_path):
    memory_dir = tmp_path / "memory"
    first = StoreLock(memory_dir)
    second = StoreLock(memory_dir)

    with first, second:
        assert os.path.samefile(first.path, second.path)


def test_permission_failure_does_not_leave_store_locked(tmp_path, monkeypatch):
    memory_dir = tmp_path / "memory"
    real_chmod = store_lock.os.chmod

    def fail_chmod(path, mode):
        raise PermissionError("read-only lock directory")

    monkeypatch.setattr(store_lock.os, "chmod", fail_chmod)
    with pytest.raises(PermissionError, match="read-only"):
        with StoreLock(memory_dir, timeout=0.1):
            pass

    monkeypatch.setattr(store_lock.os, "chmod", real_chmod)
    with StoreLock(memory_dir, timeout=0.1):
        pass

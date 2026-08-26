"""The restore epoch: apply steps are valid only against the graph they were computed on."""

from __future__ import annotations

import pytest

from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job


def test_memory_operation_at_yields_while_the_epoch_holds(engine):
    epoch = engine.restore_epoch
    with engine.memory_operation_at(epoch):
        pass  # no raise


def test_memory_operation_at_raises_once_the_epoch_moves(engine):
    epoch = engine.restore_epoch
    engine._restore_epoch += 1
    with pytest.raises(RestoredUnderfoot):
        with engine.memory_operation_at(epoch):
            pass


def test_memory_operation_at_holds_l_mem_while_it_yields(engine):
    """The check and the mutation must be atomic w.r.t. the restore (spec §2)."""
    epoch = engine.restore_epoch
    with engine.memory_operation_at(epoch):
        assert engine._memory_operation_lock.acquire(blocking=False) is True
        engine._memory_operation_lock.release()


def test_reload_restored_graph_bumps_the_epoch(engine):
    before = engine.restore_epoch
    engine.reload_restored_graph()
    assert engine.restore_epoch == before + 1


def test_restore_aware_job_passes_the_entry_epoch_to_the_job(engine):
    seen = []

    @restore_aware_job
    def job(eng, epoch):
        seen.append(epoch)

    job(engine)
    assert seen == [engine.restore_epoch]


def test_restore_aware_job_ends_the_run_instead_of_raising(engine, caplog):
    """APScheduler must not see the abort as a job crash."""

    @restore_aware_job
    def job(eng, epoch):
        eng._restore_epoch += 1
        with eng.memory_operation_at(epoch):
            pass

    with caplog.at_level("INFO"):
        assert job(engine) is None
    assert "restore" in caplog.text.lower()


def test_restore_aware_job_forwards_extra_arguments(engine):
    seen = {}

    @restore_aware_job
    def job(eng, epoch, limit, *, dry_run=False):
        seen.update(limit=limit, dry_run=dry_run)

    job(engine, 7, dry_run=True)
    assert seen == {"limit": 7, "dry_run": True}

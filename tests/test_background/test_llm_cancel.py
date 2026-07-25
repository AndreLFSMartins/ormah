"""Epoch semantics for LLM cancellation (ADR-0004 slice 2 redesign).

These tests encode the invariant that seven council rounds failed to hold: the cancel
state is written AND read atomically, and no interleaving of transitions produces a
state that no single transition could have produced.
"""
import threading

import pytest

from ormah.background import llm_cancel


@pytest.fixture(autouse=True)
def _clean_epoch():
    llm_cancel.begin_lifespan()
    yield
    llm_cancel.begin_lifespan()


def test_begin_cancel_bumps_the_epoch_and_marks_cancelled():
    gen, cancelled = llm_cancel.snapshot()
    assert cancelled is False
    llm_cancel.begin_cancel(final=False)
    new_gen, new_cancelled = llm_cancel.snapshot()
    assert new_gen != gen
    assert new_cancelled is True


def test_resume_bumps_the_epoch_so_an_in_flight_call_stays_cancelled():
    """R4 regression. A resume() re-admits NEW calls; it must never un-cancel a call
    already in flight."""
    gen, _ = llm_cancel.snapshot()
    llm_cancel.begin_cancel(final=False)
    llm_cancel.resume()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is False          # new calls are admitted again
    assert llm_cancel.epoch_changed(gen) is True   # the in-flight call still aborts


def test_resume_is_a_noop_after_a_final_cancel():
    llm_cancel.begin_cancel(final=True)
    llm_cancel.resume()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is True


def test_begin_lifespan_clears_final():
    """A final cancel must not outlive its lifespan: the llm_client adapter caches are
    module-level and a second lifespan runs in the same process."""
    llm_cancel.begin_cancel(final=True)
    llm_cancel.begin_lifespan()
    _, cancelled = llm_cancel.snapshot()
    assert cancelled is False


def test_a_final_cancel_is_never_reopened_by_a_concurrent_resume():
    """R7 HIGH-1 regression — the linearizability assertion.

    Whichever order the two transitions take, the settled state is the same:
      * resume first  -> it succeeds (final not yet set), then the final cancel lands;
      * cancel first  -> resume sees `final` and is a no-op.
    The old model could settle on "gate open + adapter cancelled" because the state was
    mutated under a lock but APPLIED outside it. Here there is nothing outside the lock.
    """
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def cancel():
        try:
            barrier.wait(timeout=5)
            llm_cancel.begin_cancel(final=True)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def resume():
        try:
            barrier.wait(timeout=5)
            llm_cancel.resume()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=cancel), threading.Thread(target=resume)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive()
    assert not errors

    _, cancelled = llm_cancel.snapshot()
    assert cancelled is True, "a final cancel was reopened by a concurrent resume"


def test_aborted_is_one_atomic_read_of_both_questions():
    """R5 regression. `aborted` answers "is the world cancelled NOW, or was THIS call's
    era superseded?" — it must be one read, never two."""
    gen, _ = llm_cancel.snapshot()
    assert llm_cancel.aborted(gen) is False
    llm_cancel.begin_cancel(final=False)
    assert llm_cancel.aborted(gen) is True
    llm_cancel.resume()
    assert llm_cancel.aborted(gen) is True      # (b): our era is over
    fresh, _ = llm_cancel.snapshot()
    assert llm_cancel.aborted(fresh) is False   # a NEW call is admitted


def test_begin_cancel_reports_how_many_calls_it_invalidated():
    """The watcher logs this count; it replaces the old "processes terminated" number."""
    assert llm_cancel.in_flight() == 0
    llm_cancel.note_call_started()
    llm_cancel.note_call_started()
    assert llm_cancel.begin_cancel(final=False) == 2
    llm_cancel.note_call_finished()
    llm_cancel.note_call_finished()
    assert llm_cancel.in_flight() == 0

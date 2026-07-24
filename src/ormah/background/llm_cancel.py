"""Single authority for LLM call cancellation (ADR-0004 slice 2 redesign).

Cancellation is a monotonic EPOCH, not a flag. Every transition bumps it inside ONE
critical section that writes every field, and performs NO work outside the lock — so
concurrent transitions serialise into a total order and no mixed state is observable.

That constraint is the whole design. The previous model split each transition into
"mutate state under a lock" + "apply it outside the lock", because applying it meant
killing child processes (`p.wait(timeout=5)` each) and that cannot hold a lock every
caller needs. Seven council rounds each found a different way for those two phases to
disagree.

Here the epoch is the STATE and killing a child is a separate EFFECT, performed by the
thread that owns the call (see ``ClaudeCliAdapter.generate``). Nothing in this module
does I/O, which is what lets every transition stay atomic.

Two distinct readings, both single atomic reads:
  * ``aborted(gen)``       — "is the world cancelled NOW, or was THIS call's era superseded?"
  * ``epoch_changed(gen)`` — "was THIS call's era superseded?" — immune to a later resume()
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_epoch: int = 0
_cancelled: bool = False
_final: bool = False
_in_flight: int = 0


def begin_cancel(*, final: bool) -> int:
    """Cancel the current epoch. Returns how many calls were in flight when it landed.

    ``final=True`` marks a shutdown cancel that ``resume()`` must not undo; only
    ``begin_lifespan()`` clears it.
    """
    global _epoch, _cancelled, _final
    with _lock:
        _epoch += 1
        _cancelled = True
        _final = _final or final
        return _in_flight


def resume() -> int:
    """Re-admit NEW calls after a RECOVERABLE cancel (the watcher's startup rollback).

    Bumps the epoch, so a call already in flight keeps observing the cancel that hit it —
    only the admission policy for new calls changes. A no-op after a final cancel.
    """
    global _epoch, _cancelled
    with _lock:
        if _final:
            return _epoch
        _epoch += 1
        _cancelled = False
        return _epoch


def begin_lifespan() -> int:
    """Start a clean era. The ONLY verb that clears ``final``.

    The llm_client adapter caches are module-level and outlive a single lifespan (the repo
    exercises consecutive lifespans in-process), so a final cancel that only ``resume()``
    could clear would leave the SECOND lifespan raising LlmCancelledError on every call for
    the life of the process.
    """
    global _epoch, _cancelled, _final
    with _lock:
        _epoch += 1
        _cancelled = False
        _final = False
        return _epoch


def snapshot() -> tuple[int, bool]:
    """This call's era AND whether the world is cancelled — from ONE critical section."""
    with _lock:
        return _epoch, _cancelled


def epoch_changed(gen: int) -> bool:
    """Was THIS call's era superseded? Immune to a later resume(), unlike ``snapshot()[1]``."""
    with _lock:
        return _epoch != gen


def aborted(gen: int) -> bool:
    """``epoch_changed(gen) or cancelled`` — as one atomic read, never two."""
    with _lock:
        return _epoch != gen or _cancelled


def note_call_started() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def note_call_finished() -> None:
    global _in_flight
    with _lock:
        _in_flight = max(0, _in_flight - 1)


def in_flight() -> int:
    with _lock:
        return _in_flight

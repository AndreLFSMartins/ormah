# Task 2: `LockProbe` — the depth-0 acquisition counter

Read `00-overview.md` first.

**Files:**
- Create: `tests/test_background/lock_probe.py`
- Test: `tests/test_background/test_lock_probe.py` (create)

**Interfaces:**
- Consumes: nothing (Task 1 is not required to build this, but the plan runs it second so Tasks 3–8 have both).
- Produces, consumed by Tasks 3–10:
  - `LockProbe(real_lock)` — context-manager-compatible wrapper. Attributes: `acquisitions` (`int`, depth-0 entries across all threads), `held` (`bool`, is *this* thread inside it).
  - `install_probe(engine) -> LockProbe` — swaps the probe into both places that hold a reference to `L_mem` and returns it.

## Why depth-0

`L_mem` is an `RLock`. A job that takes it and then calls `engine.remember()` — itself `@_serialized_memory_operation` — re-enters the same lock. Counting raw `__enter__` calls therefore reports re-entries as separate holds and yields the wrong number, in the direction that hides the bug: today's whole-run hold would count as *many* acquisitions and look already-fixed. Only a 0→1 transition is a real acquisition, and depth is **per thread**.

`MemoryEngine.__init__` passes the same lock object into `FileStore(nodes_dir, self._memory_operation_lock)`, so `FileStore` keeps its own reference in `_operation_lock`. Reassigning only `engine._memory_operation_lock` would leave every `file_store.save()` going through the unprobed original.

- [ ] **Step 1: Write the failing test**

Create `tests/test_background/test_lock_probe.py`:

```python
"""The probe itself: re-entrancy must not inflate the count."""

from __future__ import annotations

import threading

from ormah.models.node import CreateNodeRequest, NodeType

from tests.test_background.lock_probe import install_probe


def test_reentrant_acquisition_counts_once(engine):
    probe = install_probe(engine)
    with engine.memory_operation():
        with engine.memory_operation():
            pass
    assert probe.acquisitions == 1


def test_sequential_acquisitions_count_separately(engine):
    probe = install_probe(engine)
    with engine.memory_operation():
        pass
    with engine.memory_operation():
        pass
    assert probe.acquisitions == 2


def test_held_reports_the_calling_thread_only(engine):
    probe = install_probe(engine)
    inside = threading.Event()
    other_thread_saw = []

    def observer():
        inside.wait(timeout=5.0)
        other_thread_saw.append(probe.held)

    t = threading.Thread(target=observer, daemon=True)
    t.start()
    with engine.memory_operation():
        assert probe.held is True
        inside.set()
        t.join(timeout=5.0)
    assert probe.held is False
    assert other_thread_saw == [False]


def test_probe_covers_file_store_writes(engine):
    """FileStore keeps its own reference to L_mem; the probe must reach it."""
    probe = install_probe(engine)
    engine.remember(CreateNodeRequest(
        content="probe reaches the file store", type=NodeType.fact, title="probe"))
    assert probe.acquisitions >= 1
    assert probe.held is False
```

- [ ] **Step 2: Run it to verify it fails**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_lock_probe.py -q
```

Expected: `ModuleNotFoundError: No module named 'tests.test_background.lock_probe'`.

- [ ] **Step 3: Write `tests/test_background/lock_probe.py`**

```python
"""Count real L_mem acquisitions, ignoring RLock re-entries.

L_mem is an RLock and every engine mutator is decorated with it, so a job that
holds it and calls engine.remember() re-enters. Only a per-thread 0 -> 1
transition is a hold a foreground writer would have waited on.
"""

from __future__ import annotations

import threading


class LockProbe:
    """Drop-in wrapper around the engine's L_mem RLock."""

    def __init__(self, real_lock) -> None:
        self._real = real_lock
        self._local = threading.local()
        self._counter_lock = threading.Lock()
        self.acquisitions = 0

    @property
    def _depth(self) -> int:
        return getattr(self._local, "depth", 0)

    @_depth.setter
    def _depth(self, value: int) -> None:
        self._local.depth = value

    @property
    def held(self) -> bool:
        """Is the calling thread currently inside L_mem?"""
        return self._depth > 0

    def __enter__(self):
        if self._depth == 0:
            with self._counter_lock:
                self.acquisitions += 1
        self._depth += 1
        return self._real.__enter__()

    def __exit__(self, *args):
        self._depth -= 1
        return self._real.__exit__(*args)

    # FileStore and the engine only ever use `with`, but keep the RLock surface
    # intact so an unexpected direct call does not silently bypass the probe.
    def acquire(self, *args, **kwargs):
        acquired = self._real.acquire(*args, **kwargs)
        if acquired:
            if self._depth == 0:
                with self._counter_lock:
                    self.acquisitions += 1
            self._depth += 1
        return acquired

    def release(self):
        self._depth -= 1
        return self._real.release()


def install_probe(engine) -> LockProbe:
    """Swap a LockProbe into both references to L_mem and return it."""
    probe = LockProbe(engine._memory_operation_lock)
    engine._memory_operation_lock = probe
    engine.file_store._operation_lock = probe
    return probe
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_lock_probe.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check tests/
```

Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_background/lock_probe.py tests/test_background/test_lock_probe.py
git commit -m "test(background): add depth-0 L_mem acquisition probe (#240)"
```

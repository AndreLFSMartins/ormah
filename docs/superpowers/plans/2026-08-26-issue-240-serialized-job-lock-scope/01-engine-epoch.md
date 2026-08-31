# Task 1: Restore epoch and the restore-aware job decorator

Read `00-overview.md` first, especially **Global Constraints**.

**Files:**
- Modify: `src/ormah/background/memory_lock.py` (whole file replaced — it is 14 lines today)
- Modify: `src/ormah/engine/memory_engine.py` — `__init__` (~:103), `memory_operation` (:549), `reload_restored_graph` (:1329)
- Test: `tests/test_background/test_memory_lock.py` (create)

**Interfaces:**
- Produces, and every later task consumes:
  - `ormah.background.memory_lock.RestoredUnderfoot` — `Exception` subclass.
  - `ormah.background.memory_lock.restore_aware_job(job)` — decorator. The decorated function keeps the public signature `run_x(engine, *args, **kwargs)`; the **undecorated** body must accept `(engine, epoch, *args, **kwargs)`.
  - `MemoryEngine.restore_epoch` — read-only `int` property.
  - `MemoryEngine.memory_operation_at(epoch: int)` — context manager. Takes `L_mem`; raises `RestoredUnderfoot` if `self._restore_epoch != epoch`.
- Consumes: nothing.

## Why the exception lives in `background/`, and the check you must run

The spec puts `RestoredUnderfoot` in `memory_lock.py` because `background` owns the job-side vocabulary. That requires a **top-level** import of `ormah.background.memory_lock` from `memory_engine.py`. Verified during planning: `memory_lock.py` imports nothing from `ormah`, `background/__init__.py` is empty, and every existing `memory_engine → background` import is inside a function body. So no cycle. Step 1 re-checks it anyway, because if it did cycle the fix is to move the exception into `memory_engine.py` and have `memory_lock.py` import it instead.

- [ ] **Step 1: Prove the import does not cycle**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "
import ormah.background.memory_lock as m, ormah.engine.memory_engine as e
print('memory_lock file:', m.__file__)
print('engine file:', e.__file__)
"
```

Expected: both paths contain `ormah-wt-240/`, no `ImportError`. (This is the baseline — the real check is that Step 5 still passes it after the import is added.)

- [ ] **Step 2: Write the failing tests**

Create `tests/test_background/test_memory_lock.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_memory_lock.py -q
```

Expected: collection error — `ImportError: cannot import name 'RestoredUnderfoot'`.

- [ ] **Step 4: Replace `src/ormah/background/memory_lock.py`**

```python
"""Restore-awareness for jobs that mutate the live memory graph.

``L_mem`` buys background jobs exactly one thing: a mutation must not interleave
with a full graph restore. It does *not* provide per-operation atomicity — every
primitive a job mutates through already locks at its own granularity
(``engine.remember``/``connect``/``update_node``/``execute_merge`` and
``engine.file_store.save`` take ``L_mem`` per call; ``engine.db.transaction()``
takes ``L_db`` with ``BEGIN IMMEDIATE``).

So a job reads the restore epoch once, on entry, and takes ``L_mem`` only around
each apply step, via ``engine.memory_operation_at(epoch)``. If a restore lands
mid-run the job's whole snapshot is stale, not one row of it: the next apply step
raises :class:`RestoredUnderfoot`, the run ends, and the job returns at its next
interval.
"""

from __future__ import annotations

import logging
from functools import wraps

logger = logging.getLogger(__name__)


class RestoredUnderfoot(Exception):
    """A full graph restore landed while this run was computing its snapshot."""


def restore_aware_job(job):
    """Supply the entry-time restore epoch; end the run cleanly if it moves.

    The wrapped job body takes ``(engine, epoch, *args, **kwargs)``. Callers keep
    calling ``run_x(engine)``.
    """

    @wraps(job)
    def wrapper(engine, *args, **kwargs):
        epoch = engine.restore_epoch
        try:
            return job(engine, epoch, *args, **kwargs)
        except RestoredUnderfoot:
            logger.info(
                "%s aborted: a graph restore landed mid-run; it will retry next interval",
                job.__name__,
            )
            return None

    return wrapper
```

Note: `serialized_memory_job` is **still referenced** by all seven jobs at this point. Do **not** delete it yet — Task 10 does, once every job is converted. Keep it in the file, unchanged, below `restore_aware_job`:

```python
def serialized_memory_job(job):
    """Deprecated: whole-run exclusion. Being replaced by restore_aware_job (#240)."""

    @wraps(job)
    def locked(engine, *args, **kwargs):
        with engine.memory_operation():
            return job(engine, *args, **kwargs)

    return locked
```

- [ ] **Step 5: Add the engine side**

In `src/ormah/engine/memory_engine.py`, add to the top-level imports (alongside the other `from ormah...` imports):

```python
from ormah.background.memory_lock import RestoredUnderfoot
```

In `__init__`, immediately after the lock (currently line 103–104):

```python
        self._memory_operation_lock = threading.RLock()
        self._restore_epoch = 0
        self.file_store = FileStore(settings.nodes_dir, self._memory_operation_lock)
```

Right after `memory_operation` (currently ends at :553), add:

```python
    @property
    def restore_epoch(self) -> int:
        """Monotonic counter; every completed full restore bumps it."""
        return self._restore_epoch

    @contextmanager
    def memory_operation_at(self, epoch: int):
        """One exclusive apply step, valid only if no restore landed since *epoch*.

        The epoch check happens *inside* ``L_mem`` on purpose: a loose ``if``
        before the mutation would let a restore land between the check and the
        write, and a write landing between the file swap and
        ``rebuild_index()`` is silently overwritten, not corrupted (spec §2).
        """

        with self._memory_operation_lock:
            if self._restore_epoch != epoch:
                raise RestoredUnderfoot(
                    f"restore epoch moved {epoch} -> {self._restore_epoch}"
                )
            yield
```

In `reload_restored_graph`, bump **first**, before anything else in the body:

```python
    @_serialized_memory_operation
    def reload_restored_graph(self) -> int:
        """Reload file, identity, and search state after a full memory restore."""

        # Bump first: this method is exclusive under L_mem, and the file swap has
        # already happened. Any job that computed against the pre-swap graph must
        # abort even if the rebuild below raises.
        self._restore_epoch += 1

        self.file_store = FileStore(self.settings.nodes_dir, self._memory_operation_lock)
```

- [ ] **Step 6: Run the tests and the import check**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_memory_lock.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah.engine.memory_engine; print('no cycle')"
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: 7 passed; `no cycle`; ruff clean.

If the import **does** cycle: move `class RestoredUnderfoot` into `memory_engine.py` (just above `_serialized_memory_operation`), and in `memory_lock.py` import it with `from ormah.engine.memory_engine import RestoredUnderfoot` **inside** `restore_aware_job`'s `except` clause is not possible — instead import it at the top of `memory_lock.py` and drop the engine-side import. Re-run this step.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/background/memory_lock.py src/ormah/engine/memory_engine.py \
        tests/test_background/test_memory_lock.py
git commit -m "feat(engine): add restore epoch and per-apply-step memory_operation_at (#240)"
```

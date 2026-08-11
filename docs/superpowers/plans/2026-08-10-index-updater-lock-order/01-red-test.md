# Task 1: Reproduce the deadlock with a failing test

**Files:**
- Modify: `tests/test_index/test_builder.py` (append at end of file)

**Interfaces:**
- Consumes: the `engine` fixture from `tests/conftest.py:148`; `engine.builder.incremental_update()`,
  `engine.file_store.list_paths`, `engine._memory_operation_lock`, `engine.db.transaction()`.
- Produces: `test_incremental_update_does_not_deadlock_against_a_memory_job` — the regression gate
  Task 2 turns green.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_index/test_builder.py`. Check the file's existing imports first; add whichever
of these are missing:

```python
import threading

from ormah.models.node import CreateNodeRequest, NodeType
```

Then append:

```python
# --- lock order (upstream 0.14.8 restore-exclusion lock) ---


def test_incremental_update_does_not_deadlock_against_a_memory_job(engine):
    """incremental_update must take L_mem BEFORE L_db, like every memory job.

    Upstream's restore-exclusion lock decorates 8 FileStore methods with the engine's own
    RLock (L_mem) -- memory_engine passes it in: FileStore(nodes_dir, self._memory_operation_lock).
    incremental_update opens the write txn (L_db) and only then calls file_store.list_paths /
    file_hash: L_db -> L_mem. Every @serialized_memory_job background job goes L_mem -> L_db.
    Opposite orders on two locks = deadlock, and index_updater runs every 60s.

    f7ac305 fixed this same class for the forgetting sweep but audited only the background jobs
    and the MemoryEngine writers; IndexBuilder is a third class and was missed.
    """
    engine.remember(CreateNodeRequest(
        content="indexed content", type=NodeType.fact, title="indexed content"))

    builder_reached_file_store = threading.Event()
    job_holds_mem = threading.Event()
    real_list_paths = engine.file_store.list_paths

    def instrumented_list_paths():
        # Before the fix this runs INSIDE the write txn: this thread holds L_db and is one call
        # away from taking L_mem. Let the memory job grab L_mem first, then reach for it.
        # After the fix this runs BEFORE the txn, so no L_db is held and nothing can cycle.
        builder_reached_file_store.set()
        job_holds_mem.wait(timeout=1.0)  # times out once this thread already holds L_mem
        return real_list_paths()

    engine.file_store.list_paths = instrumented_list_paths

    def memory_job():
        """What @serialized_memory_job + a write txn do on every background job: L_mem, L_db."""
        builder_reached_file_store.wait(timeout=5.0)
        with engine._memory_operation_lock:
            job_holds_mem.set()
            with engine.db.transaction():
                pass

    builder_thread = threading.Thread(target=engine.builder.incremental_update, daemon=True)
    job_thread = threading.Thread(target=memory_job, daemon=True)
    builder_thread.start()
    job_thread.start()
    builder_thread.join(timeout=10.0)
    job_thread.join(timeout=10.0)

    assert not builder_thread.is_alive(), "incremental_update held L_db while waiting for L_mem"
    assert not job_thread.is_alive(), "memory job held L_mem while waiting for L_db"
```

- [ ] **Step 2: Run the test to verify it fails — and fails by HANGING**

```bash
python -m pytest tests/test_index/test_builder.py::test_incremental_update_does_not_deadlock_against_a_memory_job -v
```

Expected: **FAIL** on `incremental_update held L_db while waiting for L_mem`, after the run visibly
stalls ~10 s at the `join`.

**This is a gate.** The test must fail for the right reason. Confirm both:

- Wall-clock ≥10 s — the `join` timeout actually elapsed, not an instant failure.
- The failure is the `assert not builder_thread.is_alive()` — not `ImportError`, `NameError`,
  or a fixture error.

An instant failure means the interleaving was never reached: the test would then pass after Task 2
for the wrong reason and prove nothing. Fix the test and re-run before going further.

If the red does not reproduce, the most likely causes, in order:
1. `engine.file_store.list_paths` was rebound after the builder captured a reference — check that
   `engine.builder.file_store is engine.file_store`.
2. The store has no `.md` files, so the loop body never runs — the `remember()` call above prevents this.
3. `builder_reached_file_store.wait(timeout=5.0)` in the job timed out — raise it and re-run.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_index/test_builder.py
git commit -m "test(index): reproduce the incremental_update lock-order deadlock

Drives the exact interleaving: the builder holds L_db inside its write txn and
reaches for L_mem via file_store.list_paths, while a memory job holds L_mem and
reaches for L_db. Hangs past a 10s join today."
```

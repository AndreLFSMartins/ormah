# Task 8: `run_consolidation`

Read `00-overview.md` first. Requires Tasks 1 and 2. Independent of Tasks 3–7.

**Files:**
- Modify: `src/ormah/background/consolidator.py` — imports (`:8`), `_apply_consolidation` (`:92-179`), `run_consolidation` (`:182-204`)
- Modify: `src/ormah/engine/memory_engine.py` — the `_apply_consolidation` call site inside `apply_maintenance_results` (`:1869`, `:~1900`)
- Test: `tests/test_background/test_consolidator.py` (append)

**Interfaces:**
- Consumes: `restore_aware_job`, `memory_operation_at` (Task 1); `install_probe` (Task 2).
- Produces: `_apply_consolidation(engine, node_ids, title, content, node_type, *, epoch=None) -> str` — same `epoch=None` convention as `_apply_edge` (Task 5), for the same reason: `apply_maintenance_results` calls it from inside a method that already holds `L_mem` via `@_serialized_memory_operation`.

## Shape of this job

`_apply_consolidation` is one logical unit — new node, identity edge transfer, `derived_from` edges, demote-to-archival — spread across several already-per-call-locked engine methods (`remember`, `connect`, `update_node`) plus two direct `file_store`/`db.transaction()` writes for the `about_self` tag (`:155-164`). Wrap the **whole function body** in one `memory_operation_at(epoch)` when a job epoch is supplied, the same shape as duplicate_merger's auto-merge in Task 7: one cluster's consolidation is atomic with respect to a restore, not split across several acquisitions with a restore able to land between "create the new node" and "demote the originals".

`run_consolidation`'s per-cluster loop already wraps each `_consolidate_cluster` call in `try/except Exception` (`:197-201`) to keep one bad cluster from aborting the others — that handler **must not** swallow `RestoredUnderfoot`, since an abort there means the whole run's candidate list is stale, not just one cluster.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_consolidator.py`, inside `class TestConsolidation` so it can reuse `consolidation_engine`:

```python
    @patch("ormah.background.llm_client.llm_generate")
    def test_lock_is_not_held_across_the_llm_call(self, mock_llm, consolidation_engine):
        from tests.test_background.lock_probe import install_probe

        engine, ids = consolidation_engine
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_min_cluster_size = 2

        probe = install_probe(engine)
        lock_held_at_call = []

        def fake_llm(*args, **kwargs):
            lock_held_at_call.append(probe.held)
            return json.dumps({
                "title": "Python uses indentation",
                "summary": "Python blocks are delimited by indentation.",
                "type": "fact",
            })

        mock_llm.side_effect = fake_llm

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

        assert lock_held_at_call, "the fake LLM was never called — the fixture stopped exercising the job"
        assert not any(lock_held_at_call)

    @patch("ormah.background.llm_client.llm_generate")
    def test_aborts_when_a_restore_lands_mid_run(self, mock_llm, consolidation_engine):
        engine, ids = consolidation_engine
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_min_cluster_size = 2

        nodes_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        epoch_before = engine.restore_epoch

        # The bump must land AFTER the job read its entry epoch: restore_aware_job reads
        # engine.restore_epoch at call time, so bumping before the call would hand the job
        # the new value and leave no mismatch to detect. Inside the fake LLM is where a real
        # restore lands — between the unlocked LLM call and the apply step that follows it.
        def fake_llm(*args, **kwargs):
            engine._restore_epoch += 1
            return json.dumps({
                "title": "Python uses indentation",
                "summary": "Python blocks are delimited by indentation.",
                "type": "fact",
            })

        mock_llm.side_effect = fake_llm

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)  # returns cleanly

        # Guard against silent vacuousness: the assertion below holds trivially if the job
        # never reached an apply step (no clusters found, min cluster size unmet). Since the
        # bump lives inside the fake LLM, a moved epoch is proof the job actually got there.
        assert engine.restore_epoch > epoch_before, \
            "the fake LLM was never called — the fixture stopped exercising the job"
        nodes_after = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        assert nodes_after == nodes_before
```

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_consolidator.py -q -k "lock or aborts"
```

Expected: `assert not any([True])`; a consolidated node created despite the stale epoch (`nodes_after > nodes_before`).

- [ ] **Step 3: Convert `consolidator.py`**

Import (`:8`):

```python
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
```

`_apply_consolidation` signature and guard (`:92-102`, then indent the whole existing body by one level):

```python
def _apply_consolidation(
    engine,
    node_ids: list[str],
    title: str,
    content: str,
    node_type: str,
    *,
    epoch: int | None = None,
) -> str:
    """Create a consolidated node, link originals, and demote them to archival.

    Returns the new node's ID. When *epoch* is given the whole operation is one
    exclusive apply step (#240): a restore landing mid-consolidation must not be
    able to observe the new node without the originals demoted, or vice versa.
    ``apply_maintenance_results`` passes no epoch — it already holds L_mem.
    """
    from contextlib import nullcontext

    from ormah.models.node import (
        ConnectRequest,
        CreateNodeRequest,
        EdgeType,
        Tier,
        UpdateNodeRequest,
    )

    guard = engine.memory_operation_at(epoch) if epoch is not None else nullcontext()
    with guard:
        conn = engine.db.conn
        placeholders = ",".join("?" * len(node_ids))
        # ... existing body, unchanged, indented one level deeper ...
        return new_id
```

Everything between the old `conn = engine.db.conn` line and the final `return new_id` moves inside `with guard:` verbatim, indented by four spaces. Do not otherwise change it.

`run_consolidation` (`:182-204`) — decorator, signature, call site, and the re-raise:

```python
@restore_aware_job
def run_consolidation(engine, epoch: int) -> None:
    """Find clusters of similar working memories and consolidate via LLM."""
    settings = engine.settings
    if not settings.llm_enabled:
        return

    clusters = _find_consolidation_clusters(
        engine, limit=settings.consolidation_max_clusters_per_run
    )
    if not clusters:
        return

    consolidated_count = 0
    for cluster in clusters:
        try:
            _consolidate_cluster(engine, cluster, epoch)
            consolidated_count += 1
        except RestoredUnderfoot:
            raise
        except Exception as e:
            logger.warning("Failed to consolidate cluster: %s", e)

    if consolidated_count:
        logger.info("Consolidated %d cluster(s)", consolidated_count)
```

`_consolidate_cluster` (`:207`) gains the epoch parameter and forwards it at its one call site (`:263`):

```python
def _consolidate_cluster(engine, cluster: list[dict], epoch: int) -> None:
    ...
    node_ids = [n["id"] for n in cluster]
    _apply_consolidation(engine, node_ids, title, summary, node_type, epoch=epoch)
```

(The `llm_generate` call in between stays exactly where it is — unlocked, which is the point.)

- [ ] **Step 4: Fix the `apply_maintenance_results` call site**

In `src/ormah/engine/memory_engine.py`, the `_apply_consolidation` call inside `apply_maintenance_results` (near `:1900`, in the `for c in results.get("consolidations", [])` loop) currently passes the same positional arguments the old signature took. Confirm it does **not** pass a fifth positional/keyword `epoch` argument — it must not, since that method is already `@_serialized_memory_operation` and should use the `epoch=None` default. If the call already matches `_apply_consolidation(self, node_ids, title, summary, node_type)` positionally, no change is needed; just confirm it by reading the surrounding 15 lines before moving on.

- [ ] **Step 5: Run the whole file plus the maintenance-batch suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_consolidator.py tests/test_background/test_run_maintenance.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean. `test_run_maintenance.py` exercises `apply_maintenance_results`, which is the second caller of `_apply_consolidation` and of `_apply_edge` (Task 5) — a regression there means the `epoch=None` default path broke.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/consolidator.py src/ormah/engine/memory_engine.py \
        tests/test_background/test_consolidator.py
git commit -m "fix(consolidator): make one cluster's consolidation a single apply step (#240)"
```

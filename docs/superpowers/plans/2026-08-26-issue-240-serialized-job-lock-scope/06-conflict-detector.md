# Task 6: `run_conflict_detection`

Read `00-overview.md` first. Requires Tasks 1 and 2. Independent of Tasks 3–5.

**Files:**
- Modify: `src/ormah/background/conflict_detector.py` — imports (`:10`), `run_conflict_detection` (`:216-294`)
- Test: `tests/test_background/test_conflict_detector.py` (append)

**Interfaces:**
- Consumes: `restore_aware_job`, `memory_operation_at` (Task 1); `install_probe` (Task 2).
- Produces: nothing other tasks depend on.

## Shape of this job

Candidate discovery (`_find_conflict_candidates`, `:105`) is read-only and stays unlocked. There are **two** write regions, and they are separated by the LLM loop:

1. Per pair: the edge insert in `db.transaction()` (`:246-268`).
2. After the loop: the markdown flush over `dirty_nodes` (`:279-288`), one `file_store.load`/`save` per node.

Both get their own `memory_operation_at(epoch)`. The markdown flush takes one acquisition **per node**, not one for the whole dict — a foreground write must be able to land between two nodes.

The body is wrapped in `try/except Exception` (`:219`/`:293`) — add the re-raise. The inner `try/except Exception` at `:280-288` catches per-node markdown failures; it must **not** swallow `RestoredUnderfoot`, so the guard goes *outside* that try.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_conflict_detector.py`. Read the top of that file first for its existing helpers and its `_LLM_PATCH` equivalent; the tests below assume a helper that creates two contradicting nodes — reuse whatever the file already has instead of writing a new one.

```python
def test_conflict_detection_does_not_hold_the_lock_across_the_llm_call(engine):
    """Same bug as auto_linker: the LLM runs under L_mem today (#240)."""
    import json
    from unittest.mock import patch

    from tests.test_background.lock_probe import install_probe

    id_a, id_b = _create_conflicting_pair(engine)
    engine.settings.llm_provider = "ollama"

    probe = install_probe(engine)
    lock_held_at_call: list[bool] = []

    def fake_llm(*args, **kwargs):
        lock_held_at_call.append(probe.held)
        return json.dumps({
            "same_subject": True, "conflict": True, "type": "tension",
            "explanation": "they disagree",
        })

    with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
        from ormah.background.conflict_detector import run_conflict_detection
        run_conflict_detection(engine)

    assert lock_held_at_call, "the fake LLM was never called — the fixture stopped exercising the job"
    assert not any(lock_held_at_call)


def test_conflict_detection_aborts_when_a_restore_lands_mid_run(engine):
    import json
    from unittest.mock import patch

    id_a, id_b = _create_conflicting_pair(engine)
    engine.settings.llm_provider = "ollama"

    edges_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    epoch_before = engine.restore_epoch

    # The bump must land AFTER the job read its entry epoch: restore_aware_job reads
    # engine.restore_epoch at call time, so bumping before the call would hand the job the
    # new value and leave no mismatch to detect. Inside the fake LLM is where a real restore
    # lands — between the unlocked LLM call and the apply step that follows it.
    def fake_llm(*args, **kwargs):
        engine._restore_epoch += 1
        return json.dumps({
            "same_subject": True, "conflict": True, "type": "tension",
            "explanation": "they disagree",
        })

    with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
        from ormah.background.conflict_detector import run_conflict_detection
        run_conflict_detection(engine)  # returns cleanly

    # Guard against silent vacuousness: the abort assertion below holds trivially if the
    # job never reached an apply step at all (no candidates, filtered node type, an edge
    # already present). Since the bump lives inside the fake LLM, a moved epoch is proof
    # the job actually got there.
    assert engine.restore_epoch > epoch_before, \
        "the fake LLM was never called — the fixture stopped exercising the job"
    edges_after = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    assert edges_after == edges_before
```

If the file has no two-contradicting-nodes helper, add one modelled on `test_auto_linker._create_pair`: two `fact` nodes with opposite content and no `space`, created with `auto_link_similarity_threshold = 999.0` so node creation does not link them itself.

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_conflict_detector.py -q -k "lock or aborts"
```

Expected: `assert not any([True])` on the first; an edge created despite the stale epoch on the second.

- [ ] **Step 3: Convert the job**

Import (`:10`):

```python
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
```

Decorator and signature (`:216-217`):

```python
@restore_aware_job
def run_conflict_detection(engine, epoch: int) -> None:
```

Wrap the edge write (`:246`) — one line of extra nesting around the existing `with engine.db.transaction() as db_conn:` block, contents unchanged:

```python
            with engine.memory_operation_at(epoch):
                with engine.db.transaction() as db_conn:
                    if conflict_type == "evolution":
                        ...
```

Wrap each markdown flush (`:279-288`), guard outside the per-node `try`:

```python
        # Persist new connections to markdown files
        for nid, new_connections in dirty_nodes.items():
            with engine.memory_operation_at(epoch):
                try:
                    mem_node = engine.file_store.load(nid)
                    if mem_node is None:
                        continue
                    mem_node.connections.extend(new_connections)
                    mem_node.touch_updated()
                    engine.file_store.save(mem_node)
                except Exception as e:
                    logger.debug(
                        "Failed to persist conflict edge to markdown for %s: %s", nid[:8], e)
```

Re-raise before the catch-all (`:293`):

```python
    except RestoredUnderfoot:
        raise
    except Exception as e:
        logger.warning("Conflict detection failed: %s", e)
```

- [ ] **Step 4: Run the whole file**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_conflict_detector.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/conflict_detector.py tests/test_background/test_conflict_detector.py
git commit -m "fix(conflict-detector): take L_mem per edge and per markdown flush (#240)"
```

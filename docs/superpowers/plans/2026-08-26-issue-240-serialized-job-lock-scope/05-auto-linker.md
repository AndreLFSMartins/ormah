# Task 5: `run_auto_linker` — the 25-minute symptom

Read `00-overview.md` first. Requires Tasks 1 and 2.

**Files:**
- Modify: `src/ormah/background/auto_linker.py` — imports (`:10`), `_apply_edge` (`:269-313`), `run_auto_linker` (`:316-422`)
- Test: `tests/test_background/test_auto_linker.py` (append)

**Interfaces:**
- Consumes: `restore_aware_job`, `memory_operation_at` (Task 1); `install_probe` (Task 2).
- Produces: `_apply_edge(engine, node_a_id, node_b_id, edge_type, reason, similarity=0.0, *, epoch=None)` — the new parameter is keyword-only with a `None` default **because `MemoryEngine.apply_maintenance_results` (`memory_engine.py:1874`) also calls it**, from inside a method that is already `@_serialized_memory_operation`. With `epoch=None` the function does not acquire anything and behaves exactly as today. Task 8 relies on the same convention for `_apply_consolidation`.

## What the tests measure, and what was deliberately rejected

The measured symptom is temporal; the cause is structural. "The write returned in under X ms" would measure the machine and go red on load — **rejected**, an intermittent test is worse than none. Two structural assertions replace it:

1. **The lock is not held across the LLM call.** With 3 pairs, today the fake LLM is called 3 times, each recording `lock_held=True`, on **1** depth-0 acquisition. After the fix: 3 calls with `lock_held=False`, and one acquisition per applied edge. `assert not any(c.lock_held for c in calls)` fails today and passes after — it is the bug, literally.
2. **Foreground progress**, with `threading.Event`, no sleeps: the fake LLM *blocks*; a foreground thread runs `engine.remember()` and must finish **while** the job is parked in the LLM; only then is the event released. Today it hangs to the wait timeout; after the fix it passes deterministically.

   The wait's result is *carried out* of the job thread (`llm_saw_the_write`) rather than asserted inside it. An `assert` raised inside the fake LLM would be caught by `run_auto_linker`'s own blanket `except Exception`, which releases `L_mem` on its way out — the blocked writer would then complete, and the test would pass ~10 s slower instead of failing. Wall-clock bounds are not an option here: spec §7 rejected timing assertions outright as machine-dependent. Carrying the boolean out is the deterministic equivalent.

`run_auto_linker` wraps its body in `try/except Exception` (`:320`/`:421`) — add the re-raise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_auto_linker.py` (module already imports `json`, `patch`, `CreateNodeRequest`, `NodeType`, and defines `_LLM_PATCH`, `_create_pair`, `_reset_adapter`):

```python
def test_lock_is_not_held_across_the_llm_call(engine):
    """The bug, stated as an assertion (#240)."""
    from tests.test_background.lock_probe import install_probe

    _create_pair(engine)
    _create_pair(engine, title_a="Ruby language", content_a="Ruby is a programming language.",
                 title_b="Ruby lang", content_b="Ruby is a popular programming language.")

    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    probe = install_probe(engine)
    lock_held_at_call: list[bool] = []

    def fake_llm(*args, **kwargs):
        lock_held_at_call.append(probe.held)
        return json.dumps({"relationship": "supports", "reason": "same topic"})

    with patch(_LLM_PATCH, side_effect=fake_llm):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)

    assert lock_held_at_call, "the fake LLM was never called — the fixture stopped exercising the job"
    assert not any(lock_held_at_call)
    assert probe.acquisitions >= len(lock_held_at_call)


def test_a_foreground_write_completes_while_the_job_is_inside_the_llm(engine):
    """The 25-minute symptom. No sleeps: the fake LLM blocks until the write lands."""
    import threading

    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    job_is_inside_llm = threading.Event()
    foreground_write_done = threading.Event()
    llm_saw_the_write = []

    def blocking_llm(*args, **kwargs):
        job_is_inside_llm.set()
        # Record the wait's outcome instead of asserting on it. An assert raised here
        # would be swallowed by run_auto_linker's own blanket `except Exception`, which
        # then releases L_mem — the writer would unblock, both outer assertions would
        # still read true, and a reintroduced whole-run lock would show up as a ~10s
        # slow pass instead of a red test. Carrying the value out makes it a hard failure.
        llm_saw_the_write.append(foreground_write_done.wait(timeout=10.0))
        return json.dumps({"relationship": "supports", "reason": "same topic"})

    def foreground_write():
        assert job_is_inside_llm.wait(timeout=10.0)
        engine.remember(CreateNodeRequest(
            content="a user memory written while the linker is thinking",
            type=NodeType.fact, title="foreground"))
        foreground_write_done.set()

    writer = threading.Thread(target=foreground_write, daemon=True)
    writer.start()

    with patch(_LLM_PATCH, side_effect=blocking_llm):
        from ormah.background.auto_linker import run_auto_linker
        job_thread = threading.Thread(target=run_auto_linker, args=(engine,), daemon=True)
        job_thread.start()
        job_thread.join(timeout=20.0)

    writer.join(timeout=5.0)
    # Do not assume a call count: the engine fixture's own Self node makes this a
    # 3-pair run, so the LLM is called more than once. The first call is the one that
    # actually blocks; later calls find the event already set and return True at once.
    # Every wait must have succeeded — one False means L_mem was held across the call.
    assert llm_saw_the_write, "the fake LLM was never called — the fixture stopped exercising the job"
    assert all(llm_saw_the_write), "L_mem was held across the LLM call"
    assert foreground_write_done.is_set()
    assert not job_thread.is_alive()


def test_auto_linker_aborts_when_a_restore_lands_mid_run(engine):
    """Abort the run, and leave nothing written after the bump."""
    _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_link_similarity_threshold = 0.0
    _reset_adapter()

    # The bump must land AFTER the job read its entry epoch, not before: restore_aware_job
    # reads engine.restore_epoch at call time, so bumping first would just hand the job the
    # new value and there would be no mismatch to detect. Bumping inside the fake LLM puts
    # it exactly where a real restore lands — between the unlocked LLM call and the apply
    # step that follows it.
    def fake_llm(*args, **kwargs):
        engine._restore_epoch += 1
        return json.dumps({"relationship": "supports", "reason": "same topic"})

    edges_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    epoch_before = engine.restore_epoch

    with patch(_LLM_PATCH, side_effect=fake_llm):
        from ormah.background.auto_linker import run_auto_linker
        run_auto_linker(engine)  # returns cleanly, no raise

    # Guard against silent vacuousness: the abort assertion below holds trivially if the
    # job never reached an apply step at all (no candidates, filtered node type, an edge
    # already present). Since the bump lives inside the fake LLM, a moved epoch is proof
    # the job actually got there.
    assert engine.restore_epoch > epoch_before, \
        "the fake LLM was never called — the fixture stopped exercising the job"
    edges_after = engine.db.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    assert edges_after == edges_before
```

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_auto_linker.py -q -k "lock or foreground or aborts"
```

Expected:
- `..._not_held_across_the_llm_call`: `assert not any([True, True])`
- `..._foreground_write_completes...`: fails after the 10 s wait — `assert all([False, ...])`, "L_mem was held across the LLM call"
- `..._aborts_when_a_restore_lands`: an edge was created despite the bump; `assert 1 == 0`

The middle test takes ~10 s while red. That is the timeout, not a sleep; it disappears once green.

- [ ] **Step 3: Convert `auto_linker.py`**

Import (`:10`):

```python
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
```

`_apply_edge` (`:269`) — new keyword-only parameter and one guard around both writes:

```python
def _apply_edge(
    engine,
    node_a_id: str,
    node_b_id: str,
    edge_type: str,
    reason: str,
    similarity: float = 0.0,
    *,
    epoch: int | None = None,
) -> None:
    """Record a link decision: write to auto_link_checked and optionally create an edge.

    ``edge_type="none"`` records the pair as checked without creating an edge.

    *epoch* is the caller's restore epoch. Background jobs pass it so the whole
    apply step is exclusive and aborts if a restore landed (#240);
    ``apply_maintenance_results`` passes nothing because it already holds L_mem.
    """
    from contextlib import nullcontext

    from ormah.models.node import Connection, EdgeType

    pair = tuple(sorted([node_a_id, node_b_id]))
    now = datetime.now(timezone.utc).isoformat()

    guard = engine.memory_operation_at(epoch) if epoch is not None else nullcontext()
    with guard:
        with engine.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auto_link_checked (node_a, node_b, result, checked_at) "
                "VALUES (?, ?, ?, ?)",
                (*pair, edge_type, now),
            )

            if edge_type not in ("none", "error"):
                conn.execute(
                    "INSERT INTO edges (source_id, target_id, edge_type, weight, created, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (node_a_id, node_b_id, edge_type, round(similarity, 3), now, reason),
                )

        if edge_type not in ("none", "error"):
            try:
                mem_node = engine.file_store.load(node_a_id)
                if mem_node is not None:
                    md_conn = Connection(
                        target=node_b_id,
                        edge=EdgeType(edge_type),
                        weight=round(similarity, 2),
                    )
                    mem_node.connections.append(md_conn)
                    mem_node.touch_updated()
                    engine.file_store.save(mem_node)
            except Exception as e:
                logger.debug("Failed to persist connection to markdown for %s: %s",
                             node_a_id[:8], e)
```

Note the indentation change: the markdown write moves **inside** `guard` so the edge row and the markdown connection land in one exclusive step. `L_mem → L_db` order is preserved — `guard` is taken before `db.transaction()`, never inside it.

Decorator and signature (`:316-317`):

```python
@restore_aware_job
def run_auto_linker(engine, epoch: int) -> None:
```

The call site (`:374-377`) gains the epoch:

```python
                    _apply_edge(
                        engine, node["id"], match["id"], relationship,
                        llm_result.get("reason", ""), similarity, epoch=epoch,
                    )
```

`_set_watermark` (`auto_linker.py:28-33`) opens its own `db.transaction()`, so its call site (`:187-188`) needs the same guard:

```python
        if last_complete is not None:
            with engine.memory_operation_at(epoch):
                _set_watermark(engine, last_complete)
```

Re-raise before the catch-all (`:421`):

```python
    except RestoredUnderfoot:
        raise
    except Exception as e:
        logger.warning("Auto-linker failed: %s", e)
```

- [ ] **Step 4: Run the whole auto_linker file**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_auto_linker.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: every test in the file passes, including the pre-existing watermark and poison-content tests. If a watermark test regresses, the cause is almost certainly the `_set_watermark` wrapping — check whether it now runs after an abort.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/auto_linker.py tests/test_background/test_auto_linker.py
git commit -m "fix(auto-linker): release L_mem across the LLM call, take it per edge (#240)"
```

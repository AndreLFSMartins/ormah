# Task 7: `run_duplicate_detection`

Read `00-overview.md` first. Requires Tasks 1 and 2. Independent of Tasks 3–6.

**Files:**
- Modify: `src/ormah/background/duplicate_merger.py` — imports (`:10`), `run_duplicate_detection` (`:242-389`)
- Test: `tests/test_background/test_duplicate_merger.py` (append)

**Interfaces:**
- Consumes: `restore_aware_job`, `memory_operation_at` (Task 1); `install_probe` (Task 2).
- Produces: nothing other tasks depend on.

## Shape of this job

Two write regions per pair, mutually exclusive by score:

1. **Auto-merge** (`:339-351`): `engine.execute_merge(...)`, itself `@_serialized_memory_operation`. The guard must wrap it anyway — the decorator gives per-call atomicity, not the epoch check, and the `RLock` makes the nesting free.
2. **Proposal insert** (`:371-383`): `db.transaction()`.

The `try/except Exception` at `:349-351` catches auto-merge failures and **must not** swallow `RestoredUnderfoot` — put the guard *outside* it. The outer body-wide `try/except Exception` (`:251`/`:389`) gets the re-raise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_duplicate_merger.py`. Read the file's top first and reuse its existing near-duplicate-pair helper and LLM patch target rather than inventing new ones.

```python
def test_duplicate_detection_does_not_hold_the_lock_across_the_llm_call(engine):
    import json
    from unittest.mock import patch

    from tests.test_background.lock_probe import install_probe

    _create_duplicate_pair(engine)
    engine.settings.llm_provider = "ollama"

    probe = install_probe(engine)
    lock_held_at_call: list[bool] = []

    def fake_llm(*args, **kwargs):
        lock_held_at_call.append(probe.held)
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    assert lock_held_at_call, "the fake LLM was never called — the fixture stopped exercising the job"
    assert not any(lock_held_at_call)


def test_duplicate_detection_aborts_when_a_restore_lands_mid_run(engine):
    import json
    from unittest.mock import patch

    _create_duplicate_pair(engine)
    engine.settings.llm_provider = "ollama"

    proposals_before = engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM proposals").fetchone()["c"]
    nodes_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
    epoch_before = engine.restore_epoch

    # The bump must land AFTER the job read its entry epoch: restore_aware_job reads
    # engine.restore_epoch at call time, so bumping before the call would hand the job the
    # new value and leave no mismatch to detect. Inside the fake LLM is where a real restore
    # lands — between the unlocked LLM call and the apply step that follows it.
    def fake_llm(*args, **kwargs):
        engine._restore_epoch += 1
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    with patch("ormah.background.llm_client.llm_generate", side_effect=fake_llm):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)  # returns cleanly

    # Guard against silent vacuousness: the abort assertions below hold trivially if the
    # job never reached an apply step at all. Since the bump lives inside the fake LLM, a
    # moved epoch is proof the job actually got there.
    assert engine.restore_epoch > epoch_before, \
        "the fake LLM was never called — the fixture stopped exercising the job"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM proposals").fetchone()["c"] == proposals_before
    assert engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes").fetchone()["c"] == nodes_before
```

The node-count assertion is what proves the auto-merge path aborted too, not only the proposal path.

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_duplicate_merger.py -q -k "lock or aborts"
```

Expected: `assert not any([True])`; and a proposal or a merge landing despite the stale epoch.

- [ ] **Step 3: Convert the job**

Import (`:10`):

```python
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
```

Decorator and signature (`:242-243`):

```python
@restore_aware_job
def run_duplicate_detection(engine, epoch: int) -> None:
```

Auto-merge (`:339-351`) — guard outside the failure handler:

```python
                # Auto-merge for high-confidence duplicates
                if score >= engine.settings.auto_merge_threshold:
                    with engine.memory_operation_at(epoch):
                        try:
                            result = engine.execute_merge(
                                node["id"], match["id"],
                                merged_content=merged_content,
                                merged_title=merged_title,
                            )
                            logger.info("Auto-merged: %s", result)
                            proposals_created += 1
                            merged = True
                        except Exception as e:
                            logger.warning("Auto-merge failed for %s / %s: %s",
                                           node["id"][:8], match["id"][:8], e)
                            merged = False
                    if merged:
                        continue
```

The `continue` moves out of the `try` because `continue` inside a `with` inside a `try` still works, but keeping it outside makes the control flow readable and keeps the lock held for the shortest possible span. Initialise `merged = False` immediately before the `if score >= ...` line so the name always exists.

Proposal insert (`:371-383`):

```python
                proposal_id = str(uuid.uuid4())
                with engine.memory_operation_at(epoch):
                    with engine.db.transaction() as conn:
                        conn.execute(
                            "INSERT INTO proposals (id, type, status, source_nodes, "
                            "proposed_action, reason, created) "
                            "VALUES (?, 'merge', 'pending', ?, ?, ?, ?)",
                            (
                                proposal_id,
                                json.dumps([node["id"], match["id"]]),
                                proposed_action,
                                reason,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                proposals_created += 1
```

Re-raise before the catch-all (`:389`):

```python
    except RestoredUnderfoot:
        raise
    except Exception as e:
        logger.warning("Duplicate detection failed: %s", e)
```

- [ ] **Step 4: Run the whole file**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_duplicate_merger.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/duplicate_merger.py tests/test_background/test_duplicate_merger.py
git commit -m "fix(duplicate-merger): take L_mem per merge and per proposal (#240)"
```

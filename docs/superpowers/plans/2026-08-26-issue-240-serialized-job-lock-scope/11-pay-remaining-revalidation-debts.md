# Task 11: pay the revalidation debt in the three remaining jobs

Read `00-overview.md` first. Requires Tasks 1–10 (all complete and committed).

**Files:**
- Modify: `src/ormah/background/consolidator.py` — `_apply_consolidation`'s demote loop (`:186`)
- Modify: `src/ormah/background/auto_cluster.py` — the per-node apply step (`:49-54`)
- Modify: `src/ormah/background/duplicate_merger.py` — the auto-merge apply step (`:340-353`)
- Modify: `src/ormah/engine/memory_engine.py` — **only if** the duplicate_merger fix genuinely cannot be done inside the job (see below; it can, so expect no change here)
- Test: `tests/test_background/test_consolidator.py`, `tests/test_background/test_auto_cluster.py`, `tests/test_background/test_duplicate_merger.py` (append to each)

**Interfaces:**
- Consumes: `memory_operation_at(epoch)` (Task 1); the `_still_decays` pattern from `decay_manager.py:15-41` (Task 3) is the template to mirror.
- Produces: nothing later tasks depend on.

## Why this exists

Spec §5 named decay's tier revalidation as a debt *created by removing whole-run exclusion*, and Task 3 paid it. The final whole-branch review found the identical shape unguarded in three other jobs. Under `@serialized_memory_job` none of these were reachable; this change makes all three reachable, so each needs the same treatment decay got: **re-read the state inside the apply step, and skip the item if it no longer qualifies.**

The pattern in all three cases: *snapshot outside the lock → apply inside the lock, using the snapshot*. The fix is always: *inside the lock, re-read what the write depends on; if it changed, skip this item and let the next run reprocess it.*

**Skip the item, do not abort the run.** This is the opposite of `RestoredUnderfoot` handling, and deliberately so: a restore invalidates the whole snapshot, but one node changing invalidates only that node.

## The three windows

| Job | What is stale | Concrete failure |
|---|---|---|
| `consolidator` | the cluster's `node_ids`, snapshotted before the LLM call | node N is snapshotted as `working`; the user promotes it to `core` during the LLM call; the apply step demotes it to `archival`, silently undoing the promotion — bit-for-bit the #257 canary, in a different job |
| `auto_cluster` | "this node has no space", from the candidate query | user assigns a space between the query and the apply step; the apply step overwrites it |
| `duplicate_merger` | both nodes' `content`, which the LLM wrote `merged_content` from | user edits the kept node during the LLM call; `execute_merge` overwrites it with merged text derived from the pre-edit content |

- [ ] **Step 1: Write the failing tests**

Each test uses the same seam the Task 3 canary used: patch something that runs in the **unlocked** phase, and land the competing write there. Do NOT patch anything called from inside the apply step's lock — a lock held on one thread cannot observe a "concurrent" write happening inside itself (this cost this plan two round-trips already).

Append to `tests/test_background/test_consolidator.py`, inside `class TestConsolidation`:

```python
    @patch("ormah.background.llm_client.llm_generate")
    def test_a_node_promoted_during_the_llm_call_is_not_demoted(self, mock_llm, consolidation_engine):
        """The #257 canary, in the consolidator: revalidate tier inside the apply step."""
        from ormah.models.node import Tier, UpdateNodeRequest

        engine, ids = consolidation_engine
        engine.settings.llm_provider = "ollama"
        engine.settings.consolidation_min_cluster_size = 2

        promoted_id = ids[0]
        promoted = {"done": False}

        def promote_then_answer(*args, **kwargs):
            """The LLM call is the unlocked phase: a foreground promotion lands here."""
            if not promoted["done"]:
                promoted["done"] = True
                engine.update_node(promoted_id, UpdateNodeRequest(tier=Tier.core))
            return json.dumps({
                "title": "Python uses indentation",
                "summary": "Python blocks are delimited by indentation.",
                "type": "fact",
            })

        mock_llm.side_effect = promote_then_answer

        from ormah.background.consolidator import run_consolidation
        run_consolidation(engine)

        assert promoted["done"], "the fake LLM was never called — the fixture stopped exercising the job"
        row = engine.db.conn.execute(
            "SELECT tier FROM nodes WHERE id = ?", (promoted_id,)).fetchone()
        assert row["tier"] == "core", "consolidation demoted a node promoted after the snapshot"
```

Append to `tests/test_background/test_auto_cluster.py` (created in Task 4 — reuse its `_seeded_pair`, `_space_of` and `_unassign` helpers):

```python
def test_a_space_assigned_after_the_scan_is_not_overwritten(engine):
    """auto_cluster's candidate query says 'no space'; revalidate before writing one."""
    orphan = _seeded_pair(engine, 0)
    assigned_by_user = {"done": False}

    real_load = engine.file_store.load

    def assign_then_load(node_id):
        """file_store.load is the first thing the apply step does; the user write lands
        just before it, standing in for one that arrived after the candidate query."""
        if not assigned_by_user["done"] and node_id == orphan:
            assigned_by_user["done"] = True
            node = real_load(node_id)
            node.space = "chosen-by-user"
            node.touch_updated()
            real_save(node)
            engine.db.conn.execute(
                "UPDATE nodes SET space = 'chosen-by-user' WHERE id = ?", (orphan,))
            engine.db.conn.commit()
        return real_load(node_id)

    real_save = engine.file_store.save
    engine.file_store.load = assign_then_load

    run_auto_cluster(engine)

    assert assigned_by_user["done"], "the apply step never ran — the fixture stopped exercising the job"
    assert _space_of(engine, orphan) == "chosen-by-user"
```

Append to `tests/test_background/test_duplicate_merger.py` (reuse the file's existing near-duplicate-pair helper and LLM patch target — Task 7 used `_create_pair` with `engine.settings.auto_merge_threshold = 0.0`; do the same):

```python
def test_a_node_edited_during_the_llm_call_is_not_merged_over(engine):
    """The merged text was written from pre-edit content; do not apply it to edited nodes."""
    import json
    from unittest.mock import patch

    id_a, id_b = _create_pair(engine)
    engine.settings.llm_provider = "ollama"
    engine.settings.auto_merge_threshold = 0.0

    edited = {"done": False}

    def edit_then_answer(*args, **kwargs):
        """The LLM call is the unlocked phase: a foreground edit lands here."""
        if not edited["done"]:
            edited["done"] = True
            engine.update_node(id_a, UpdateNodeRequest(
                content="the user rewrote this node while the merger was thinking"))
        return json.dumps({
            "is_duplicate": True, "reason": "same fact",
            "merged_title": "merged", "merged_content": "merged content",
        })

    nodes_before = engine.db.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]

    with patch("ormah.background.llm_client.llm_generate", side_effect=edit_then_answer):
        from ormah.background.duplicate_merger import run_duplicate_detection
        run_duplicate_detection(engine)

    assert edited["done"], "the fake LLM was never called — the fixture stopped exercising the job"
    row = engine.db.conn.execute(
        "SELECT content FROM nodes WHERE id = ?", (id_a,)).fetchone()
    assert row is not None, "the edited node was merged away"
    assert "the user rewrote this node" in row["content"], "the stale merged text overwrote a fresh edit"
    assert engine.db.conn.execute(
        "SELECT COUNT(*) AS c FROM nodes").fetchone()["c"] == nodes_before
```

Add `from ormah.models.node import UpdateNodeRequest` to that file's imports if it is not already there.

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py \
  tests/test_background/test_auto_cluster.py \
  tests/test_background/test_duplicate_merger.py \
  -q -k "promoted or overwritten or edited"
```

Expected: all three fail — `assert 'archival' == 'core'`, `assert 'proj' == 'chosen-by-user'`, and the content assertion showing the stale merged text landed.

If a test fails because the fixture produced no work for the job (no cluster, no candidate pair), that is the vacuousness trap this plan hit three times: fix the seeding, say so in your report, and make sure the anti-vacuousness guard (`assert ..."done"`) is what tells you.

- [ ] **Step 3: `consolidator.py` — re-read the tier before demoting**

In `_apply_consolidation`, replace the demote line (`:186`):

```python
            engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))
```

with:

```python
            # Revalidate before demoting: node_ids was snapshotted before the LLM call,
            # so a foreground promotion may have landed since. Skip the item, do not abort
            # the run — one node changing invalidates that node, not the whole cluster (#240).
            current = conn.execute(
                "SELECT tier FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if current is None or current["tier"] != "working":
                logger.debug(
                    "Consolidation left %s alone: tier changed since the snapshot", node_id[:8])
                continue
            engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))
```

`conn` is already bound at the top of `_apply_consolidation`. The `derived_from` edge above it still gets created — the consolidated node legitimately derives from the original either way; only the demotion is withheld.

- [ ] **Step 4: `auto_cluster.py` — re-read the space before assigning**

Replace the apply step (`:48-54`):

```python
            # Update markdown file
            with engine.memory_operation_at(epoch):
                node = engine.file_store.load(node_id)
                if node:
                    node.space = most_common
                    node.touch_updated()
                    engine.file_store.save(node)

            assigned += 1
```

with:

```python
            # Update markdown file
            with engine.memory_operation_at(epoch):
                node = engine.file_store.load(node_id)
                if node is None:
                    continue
                # Revalidate: the candidate query said this node had no space, but that was
                # read outside the lock. A space assigned since is the user's, not ours (#240).
                if node.space:
                    logger.debug(
                        "Auto-cluster left %s alone: a space was assigned since the scan",
                        node_id[:8])
                    updates.pop()
                    continue
                node.space = most_common
                node.touch_updated()
                engine.file_store.save(node)

            assigned += 1
```

`updates.pop()` removes the entry appended for this node immediately above, so the later chunked DB write does not re-apply what the file write just declined. Verify that `updates.append((most_common, node_id))` is the statement directly above the apply step before relying on this — if code moved, drop the `append` until after the revalidation instead, which is cleaner.

- [ ] **Step 5: `duplicate_merger.py` — re-read both contents before merging**

The merged text the LLM produced is only valid for the content it saw. Inside the auto-merge apply step (`:340`), before `engine.execute_merge(...)`:

```python
                merged = False
                if score >= engine.settings.auto_merge_threshold:
                    with engine.memory_operation_at(epoch):
                        # Revalidate: merged_content was written by the LLM from the content
                        # snapshotted before the call. Applying it over an edit made since would
                        # silently discard that edit. Skip the pair; the next run re-checks it
                        # against the new content (#240).
                        fresh = engine.db.conn.execute(
                            "SELECT id, content FROM nodes WHERE id IN (?, ?)",
                            (node["id"], match["id"]),
                        ).fetchall()
                        current = {r["id"]: r["content"] for r in fresh}
                        if (
                            current.get(node["id"]) != node["content"]
                            or current.get(match["id"]) != other["content"]
                        ):
                            logger.debug(
                                "Auto-merge skipped %s / %s: content changed since the snapshot",
                                node["id"][:8], match["id"][:8])
                            continue
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

Note the `continue` inside the `with`: it exits the context manager cleanly, releasing the lock, and moves to the next `match` — the intended behaviour.

**This requires no change to `execute_merge` or any other engine API.** If you conclude it does, stop and report rather than changing `memory_engine.py`.

- [ ] **Step 6: Run the three files in full**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py \
  tests/test_background/test_auto_cluster.py \
  tests/test_background/test_duplicate_merger.py \
  tests/test_background/test_run_maintenance.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean. `test_run_maintenance.py` is included because `apply_maintenance_results` is the second caller of `_apply_consolidation` — it passes no epoch and must keep working; the revalidation you added runs for it too, which is correct (it is a real re-read, not epoch-dependent).

- [ ] **Step 7: Full suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt
tail -12 out.txt
```

Expected: the printed path contains `ormah-wt-240/`; **exactly 4 failures**, all of them these known-pre-existing, environment-dependent ones:
`tests/test_adapters/test_space_detect.py::test_detect_returns_none_for_home` and the three `tests/test_setup.py::TestConfigureCodexMcp` tests. Any fifth failure is yours — report it.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/background/consolidator.py src/ormah/background/auto_cluster.py \
        src/ormah/background/duplicate_merger.py \
        tests/test_background/test_consolidator.py tests/test_background/test_auto_cluster.py \
        tests/test_background/test_duplicate_merger.py
git commit -m "fix(jobs): revalidate snapshotted state inside the apply step (#240)"
```

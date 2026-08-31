# Task 4: `run_importance_scoring` and `run_auto_cluster`

Read `00-overview.md` first. Requires Tasks 1 and 2.

**Files:**
- Modify: `src/ormah/background/importance_scorer.py` (141 lines)
- Modify: `src/ormah/background/auto_cluster.py` (69 lines)
- Test: `tests/test_background/test_importance_scorer.py` (append)
- Test: `tests/test_background/test_auto_cluster.py` (create — check first whether it exists; as of planning it does not)

**Interfaces:**
- Consumes: `restore_aware_job`, `memory_operation_at` (Task 1); `install_probe` (Task 2).
- Produces: `_commit_updates_chunked(db, updates, chunk_size=100, *, engine=None, epoch=None)` — the two new keyword-only parameters are optional so `tests/test_background/test_chunked_writes.py` keeps calling it with `(db, updates)`. **Read that file before editing**; if it asserts on the signature, keep it green.

## Why these two matter separately from the LLM jobs

Neither calls an LLM. Their bug is pure whole-run retention, and it is the one that reaches a **default install** with `llm_provider=none`. A test that only watched the LLM would report both green while the bug is untouched. The assertion here is the depth-0 acquisition count: `== 1` today for any item count, proportional to items after.

Both bodies are wrapped in `try/except Exception` (`auto_cluster` at `:16`/`:68`; `importance_scorer` has none) — `auto_cluster` needs the `except RestoredUnderfoot: raise` re-raise, `importance_scorer` does not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_importance_scorer.py`:

```python
def test_importance_scoring_takes_the_lock_per_node_and_per_chunk(engine):
    """No LLM in this job at all — the hold is pure whole-run retention."""
    from tests.test_background.lock_probe import install_probe

    for i in range(4):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"node {i} with enough content to score", type=NodeType.fact,
            title=f"node {i}"))
        engine.db.conn.execute(
            "UPDATE nodes SET access_count = ?, importance = 0.0 WHERE id = ?", (i * 5, nid))
    engine.db.conn.commit()

    probe = install_probe(engine)
    run_importance_scoring(engine)

    # Before the fix: exactly 1 for any node count.
    assert probe.acquisitions >= 4


def test_importance_scoring_aborts_when_a_restore_lands_mid_run(engine):
    from ormah.background.memory_lock import RestoredUnderfoot  # noqa: F401  (documents intent)

    for i in range(4):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"node {i} with enough content to score", type=NodeType.fact,
            title=f"node {i}"))
        engine.db.conn.execute(
            "UPDATE nodes SET access_count = ?, importance = 0.0 WHERE id = ?", (i * 5, nid))
    engine.db.conn.commit()

    real_save = engine.file_store.save
    saves = {"count": 0}

    def bump_after_first(node):
        path = real_save(node)
        saves["count"] += 1
        if saves["count"] == 1:
            engine._restore_epoch += 1
        return path

    engine.file_store.save = bump_after_first
    run_importance_scoring(engine)  # returns cleanly

    assert saves["count"] == 1
```

Create `tests/test_background/test_auto_cluster.py`:

```python
"""Auto-cluster: another no-LLM job that held L_mem for its whole run."""

from __future__ import annotations

from ormah.background.auto_cluster import run_auto_cluster
from ormah.models.node import ConnectRequest, CreateNodeRequest, EdgeType, NodeType

from tests.test_background.lock_probe import install_probe


def _unassign(engine, node_id: str) -> None:
    engine.db.conn.execute("UPDATE nodes SET space = NULL WHERE id = ?", (node_id,))
    engine.db.conn.commit()


def _space_of(engine, node_id: str) -> str | None:
    row = engine.db.conn.execute(
        "SELECT space FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row["space"] if row else None


def _seeded_pair(engine, i: int) -> str:
    """One spaced anchor plus one unassigned neighbour edged to it."""
    anchor, _ = engine.remember(CreateNodeRequest(
        content=f"anchor {i}", type=NodeType.fact, title=f"anchor {i}", space="proj"))
    orphan, _ = engine.remember(CreateNodeRequest(
        content=f"orphan {i}", type=NodeType.fact, title=f"orphan {i}"))
    _unassign(engine, orphan)
    engine.connect(ConnectRequest(
        source_id=orphan, target_id=anchor, edge=EdgeType.related_to, weight=1.0))
    return orphan


def test_auto_cluster_assigns_from_neighbours(engine):
    orphan = _seeded_pair(engine, 0)
    run_auto_cluster(engine)
    assert _space_of(engine, orphan) == "proj"


def test_auto_cluster_takes_the_lock_per_node_not_once_per_run(engine):
    orphans = [_seeded_pair(engine, i) for i in range(3)]
    probe = install_probe(engine)
    run_auto_cluster(engine)

    assert all(_space_of(engine, o) == "proj" for o in orphans)
    # Before the fix: exactly 1, whatever the node count.
    assert probe.acquisitions >= 3


def test_auto_cluster_aborts_when_a_restore_lands_mid_run(engine):
    orphans = [_seeded_pair(engine, i) for i in range(3)]
    real_save = engine.file_store.save
    saves = {"count": 0}

    def bump_after_first(node):
        path = real_save(node)
        saves["count"] += 1
        if saves["count"] == 1:
            engine._restore_epoch += 1
        return path

    engine.file_store.save = bump_after_first
    run_auto_cluster(engine)  # returns cleanly

    assert saves["count"] == 1
    assert sum(_space_of(engine, o) == "proj" for o in orphans) == 0
```

The last assertion is the half that matters: the DB chunk write happens *after* the per-node file saves, so an abort must leave **no** space assigned in the index.

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_auto_cluster.py \
            tests/test_background/test_importance_scorer.py -q
```

Expected: the four new tests fail (`assert 1 >= 3`, `assert 1 >= 4`, and `assert 3 == 1` / `assert 4 == 1` on the abort tests, which currently run to completion).

- [ ] **Step 3: Convert `importance_scorer.py`**

Change the import (line 9):

```python
from ormah.background.memory_lock import restore_aware_job
```

Change `_commit_updates_chunked` (`:32-41`) to take the epoch:

```python
def _commit_updates_chunked(db, updates, chunk_size: int = 100, *, engine=None, epoch=None) -> None:
    """Apply (importance, node_id) updates in bounded write transactions so a
    full-store batch never holds the write lock long enough to stall foreground writes.

    When *engine* and *epoch* are given, each chunk also takes L_mem for itself and
    revalidates the restore epoch (#240) — the care this function already took for
    L_db, extended to the lock that was being held for the whole run.
    """
    from contextlib import nullcontext

    for i in range(0, len(updates), chunk_size):
        guard = engine.memory_operation_at(epoch) if engine is not None else nullcontext()
        with guard:
            with db.transaction() as conn:
                for importance_val, nid in updates[i : i + chunk_size]:
                    conn.execute(
                        "UPDATE nodes SET importance = ? WHERE id = ?",
                        (importance_val, nid),
                    )
```

Change the decorator and signature (`:44-45`):

```python
@restore_aware_job
def run_importance_scoring(engine, epoch: int) -> None:
```

Wrap the per-node file write (`:129-134`) — replace those six lines with:

```python
        # Update markdown file
        with engine.memory_operation_at(epoch):
            node = engine.file_store.load(nid)
            if node is not None:
                node.importance = round(importance, 4)
                node.touch_updated()
                engine.file_store.save(node)
```

Load and save go inside the **same** acquisition on purpose: a read-modify-write split across two acquisitions is a lost update.

Pass the epoch to the chunked commit (`:139`):

```python
    if updates:
        _commit_updates_chunked(engine.db, updates, engine=engine, epoch=epoch)
```

- [ ] **Step 4: Convert `auto_cluster.py`**

Change the import (line 8):

```python
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
```

Decorator and signature (`:13-14`):

```python
@restore_aware_job
def run_auto_cluster(engine, epoch: int) -> None:
```

Wrap the per-node file write (`:48-53`):

```python
            # Update markdown file
            with engine.memory_operation_at(epoch):
                node = engine.file_store.load(node_id)
                if node:
                    node.space = most_common
                    node.touch_updated()
                    engine.file_store.save(node)
```

Wrap each DB chunk (`:57-64`):

```python
        if updates:
            chunk_size = 100
            for i in range(0, len(updates), chunk_size):
                with engine.memory_operation_at(epoch):
                    with engine.db.transaction() as conn:
                        for space_val, node_id in updates[i : i + chunk_size]:
                            conn.execute(
                                "UPDATE nodes SET space = ? WHERE id = ?", (space_val, node_id)
                            )
```

Re-raise before the catch-all (`:68`):

```python
    except RestoredUnderfoot:
        raise
    except Exception as e:
        logger.warning("Auto-cluster failed: %s", e)
```

- [ ] **Step 5: Run both test files plus the chunked-writes suite**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_auto_cluster.py \
            tests/test_background/test_importance_scorer.py \
            tests/test_background/test_chunked_writes.py -q
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: all pass, ruff clean. `test_chunked_writes.py` must stay green **without edits** — the new parameters are keyword-only with defaults precisely so it does.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/importance_scorer.py src/ormah/background/auto_cluster.py \
        tests/test_background/test_importance_scorer.py tests/test_background/test_auto_cluster.py
git commit -m "fix(jobs): scope L_mem to each apply step in importance scorer and auto-cluster (#240)"
```

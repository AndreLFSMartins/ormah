# Task 03: Stamp `archived_at` on demotion to archival

**Depends on:** Task 02.

The single chokepoint for tier changes is `MemoryEngine.update_node`. Stamp `archived_at`
there whenever a node *enters* the archival tier (old tier != archival, new tier == archival).
`decay_manager` demotes via `update_node`, so it inherits this for free.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` (`update_node`)
- Test: `tests/test_engine/test_archived_at.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine/test_archived_at.py`:

```python
from __future__ import annotations

from ormah.models.node import CreateNodeRequest, NodeType, Tier, UpdateNodeRequest


def _archived_at(engine, node_id):
    row = engine.db.conn.execute(
        "SELECT archived_at FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return row["archived_at"]


def test_demotion_to_archival_stamps_archived_at(engine):
    node_id, _ = engine.remember(CreateNodeRequest(
        content="demote me", type=NodeType.fact, tier=Tier.working, title="d"))
    assert _archived_at(engine, node_id) is None

    engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))

    assert _archived_at(engine, node_id) is not None
    # also persisted to the file (source of truth)
    assert engine.file_store.load(node_id).archived_at is not None


def test_non_archival_update_does_not_stamp(engine):
    node_id, _ = engine.remember(CreateNodeRequest(
        content="rename me", type=NodeType.fact, tier=Tier.working, title="r"))
    engine.update_node(node_id, UpdateNodeRequest(title="renamed"))
    assert _archived_at(engine, node_id) is None


def test_archived_at_not_overwritten_on_re_demotion(engine):
    node_id, _ = engine.remember(CreateNodeRequest(
        content="x", type=NodeType.fact, tier=Tier.working, title="x"))
    engine.update_node(node_id, UpdateNodeRequest(tier=Tier.archival))
    first = _archived_at(engine, node_id)
    # a later metadata edit must not move the archival timestamp
    engine.update_node(node_id, UpdateNodeRequest(title="x2"))
    assert _archived_at(engine, node_id) == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine/test_archived_at.py -v`
Expected: FAIL (`archived_at` stays None after demotion).

- [ ] **Step 3: Implement the stamp**

In `src/ormah/engine/memory_engine.py` `update_node`, replace the existing tier-apply line:

```python
        if req.tier is not None:
            node.tier = req.tier
```

with:

```python
        if req.tier is not None:
            entering_archival = (
                req.tier == Tier.archival and node.tier != Tier.archival
            )
            node.tier = req.tier
            if entering_archival and node.archived_at is None:
                node.archived_at = datetime.now(timezone.utc)
```

`Tier` and `datetime`/`timezone` are already imported in this module (used elsewhere in
`update_node`). Verify the imports exist; if `Tier` is not imported, add it to the existing
`from ormah.models.node import ...` line.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_engine/test_archived_at.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Regression — decay still works and now stamps**

Run: `.venv/bin/python -m pytest tests/test_background/test_decay_manager.py -v`
Expected: PASS (decay demotes via update_node; archived_at now set as a side effect).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_archived_at.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_archived_at.py
git commit -m "feat(engine): stamp archived_at when a node enters the archival tier (#28)"
```

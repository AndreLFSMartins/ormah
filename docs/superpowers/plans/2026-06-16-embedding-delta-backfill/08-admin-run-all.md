# Task 08: Wire `embedding_backfill` into `/admin/tasks/run-all` (sleep-cycle)

Register the job in the admin task registry so the 02:00 sleep-cycle pass (`POST
/admin/tasks/run-all`) runs it — the path the operator uses with in-process intervals set to
`999999`. `embedding_backfill` is a standard `(module, function)` runner, so it fits
`_TASK_RUNNERS` directly (no `index_updater`-style special case).

**Files:**
- Modify: `src/ormah/api/routes_admin.py` (`_TASK_RUNNERS` ~L20-30; `_TASK_DESCRIPTIONS` ~L32-44; `_SLEEP_CYCLE_ORDER` ~L46-58)
- Test: `tests/test_api/test_admin_embedding_backfill_task.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_admin_embedding_backfill_task.py`:

```python
"""embedding_backfill must be a registered admin task in the sleep-cycle (#32)."""
from __future__ import annotations

from ormah.api import routes_admin


def test_embedding_backfill_in_task_registry():
    assert "embedding_backfill" in routes_admin._TASK_RUNNERS
    module, func = routes_admin._TASK_RUNNERS["embedding_backfill"]
    assert module == "ormah.background.embedding_backfill"
    assert func == "run_embedding_backfill"


def test_embedding_backfill_has_description():
    assert "embedding_backfill" in routes_admin._TASK_DESCRIPTIONS


def test_embedding_backfill_in_sleep_cycle_order():
    order = routes_admin._SLEEP_CYCLE_ORDER
    assert "embedding_backfill" in order
    # runs after the index is updated
    assert order.index("embedding_backfill") > order.index("index_updater")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api/test_admin_embedding_backfill_task.py -v`
Expected: FAIL — key not in `_TASK_RUNNERS`.

- [ ] **Step 3: Add to `_TASK_RUNNERS`**

In `src/ormah/api/routes_admin.py`, add to the `_TASK_RUNNERS` dict (after the
`memory_backup` entry ~L29):

```python
    "embedding_backfill": ("ormah.background.embedding_backfill", "run_embedding_backfill"),
```

- [ ] **Step 4: Add to `_TASK_DESCRIPTIONS`**

Add to the `_TASK_DESCRIPTIONS` dict (~L32-44):

```python
    "embedding_backfill": "Backfills missing vector embeddings (delta) or re-embeds all on an embedding-schema bump. Keeps vector search complete after restarts and overnight ingest (#32).",
```

- [ ] **Step 5: Add to `_SLEEP_CYCLE_ORDER`**

In the `_SLEEP_CYCLE_ORDER` list (~L46-58), insert `"embedding_backfill"` immediately after
`"index_updater"`:

```python
_SLEEP_CYCLE_ORDER = [
    "importance_scorer",
    "index_updater",
    "embedding_backfill",
    "duplicate_merger",
    "conflict_detector",
    "auto_linker",
    "auto_cluster",
    "consolidator",
    "decay_manager",
    "forgetting_manager",
    "memory_backup",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api/test_admin_embedding_backfill_task.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Full suite + lint + commit**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src/ tests/
git add src/ormah/api/routes_admin.py tests/test_api/test_admin_embedding_backfill_task.py
git commit -m "feat(api): run embedding_backfill in the sleep-cycle run-all pass (#32)"
```

- [ ] **Step 8: Verify the whole feature**

Run the full fast suite once more and confirm green:

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (no regressions; new tests from Tasks 01-08 all green).

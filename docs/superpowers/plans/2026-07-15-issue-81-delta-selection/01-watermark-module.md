# Task 1: Shared watermark module

Read `00-overview.md` first. Work in `/Users/andre/Documents/GitHub/Tools/ormah-81` on branch `fix/81-delta-selection`.

**Files:**
- Create: `src/ormah/background/watermark.py`
- Modify: `src/ormah/index/builder.py:36` (full_rebuild watermark reset)
- Test: `tests/test_background/test_watermark.py` (create)

Key-parametrized generalization of the private trio in `auto_linker.py:13-32` (which is NOT touched — see overview). Keys used later: `duplicate_check_watermark`, `conflict_check_watermark`. `full_rebuild` re-allocates every node's `seq`, so it must clear the new cursors exactly like it already clears `auto_link_watermark` (overview invariant).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_background/test_watermark.py
"""Tests for the shared seq-watermark helpers (#81)."""

from __future__ import annotations

from ormah.background.watermark import get_watermark, set_watermark


def test_default_is_zero(engine):
    assert get_watermark(engine.db.conn, "duplicate_check_watermark") == 0


def test_roundtrip(engine):
    set_watermark(engine, "duplicate_check_watermark", 42)
    assert get_watermark(engine.db.conn, "duplicate_check_watermark") == 42


def test_overwrite(engine):
    set_watermark(engine, "conflict_check_watermark", 7)
    set_watermark(engine, "conflict_check_watermark", 9)
    assert get_watermark(engine.db.conn, "conflict_check_watermark") == 9


def test_keys_are_independent(engine):
    set_watermark(engine, "duplicate_check_watermark", 5)
    assert get_watermark(engine.db.conn, "conflict_check_watermark") == 0
    # and independent of the auto_linker's key
    assert get_watermark(engine.db.conn, "auto_link_watermark") == 0


def test_malformed_value_reads_as_zero(engine):
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("duplicate_check_watermark", "not-a-number"),
        )
    assert get_watermark(engine.db.conn, "duplicate_check_watermark") == 0


def test_full_rebuild_resets_all_incremental_watermarks(engine):
    """Mass reindex re-allocates seq; every incremental cursor must be cleared
    (upstream already does this for auto_link_watermark, builder.py:36)."""
    set_watermark(engine, "duplicate_check_watermark", 42)
    set_watermark(engine, "conflict_check_watermark", 43)

    engine.builder.full_rebuild()

    assert get_watermark(engine.db.conn, "duplicate_check_watermark") == 0
    assert get_watermark(engine.db.conn, "conflict_check_watermark") == 0
```

(If the `engine` fixture exposes the builder under another attribute, mirror how `tests/test_background/test_auto_linker.py` invokes `full_rebuild` — it has an equivalent reset test for `auto_link_watermark`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_watermark.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ormah.background.watermark'`

- [ ] **Step 3: Write the implementation**

```python
# src/ormah/background/watermark.py
"""Shared seq-watermark helpers for incremental background jobs (#81).

Generalizes the pattern auto_linker introduced in #26: a job records the seq
of the last fully-processed node under a key in ``meta`` and selects only
``seq > watermark`` on the next run. auto_linker still uses its private copy
(kept untouched to avoid conflicts with queued PRs); migrating it here is a
follow-up.
"""

from __future__ import annotations

DUPLICATE_WATERMARK_KEY = "duplicate_check_watermark"
CONFLICT_WATERMARK_KEY = "conflict_check_watermark"


def get_watermark(conn, key: str) -> int:
    """Return the seq of the last fully-processed node for *key*, or 0."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def set_watermark(engine, key: str, seq: int) -> None:
    with engine.db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, str(seq)),
        )
```

- [ ] **Step 4: Extend the full_rebuild reset**

In `src/ormah/index/builder.py`, replace line 36:

```python
        self.db.conn.execute("DELETE FROM meta WHERE key = 'auto_link_watermark'")
```

with:

```python
        self.db.conn.execute(
            "DELETE FROM meta WHERE key IN "
            "('auto_link_watermark', 'duplicate_check_watermark', 'conflict_check_watermark')"
        )
```

(The comment above it already explains why; leave it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_watermark.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/ormah/background/watermark.py src/ormah/index/builder.py tests/test_background/test_watermark.py
git commit -m "feat(background): shared seq-watermark helpers for incremental jobs (#81)"
```

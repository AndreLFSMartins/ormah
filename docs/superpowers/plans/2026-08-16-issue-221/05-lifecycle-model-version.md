# Task 5: Integer lifecycle-model version

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:159-197` (`_migrate_fsrs`)
- Create: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - module-level constant `LIFECYCLE_MODEL_VERSION: int = 2` in `memory_engine.py`
  - `MemoryEngine._lifecycle_model_version(self) -> int`
  - `MemoryEngine._seed_stability_from_access_count(self) -> None`
  - `_migrate_fsrs(self) -> None` keeps its name and its call site at `memory_engine.py:151`.

**Semantics:**

| Store state | `_lifecycle_model_version()` | Action |
|---|---|---|
| No `lifecycle_model_version`, no `fsrs_migrated` | `0` | seed from `access_count`, then write `2` |
| No `lifecycle_model_version`, `fsrs_migrated = '1'` | `1` | skip the seed, write `2` |
| `lifecycle_model_version = 2` | `2` | nothing |

Version `2` records *which model produced the stored stabilities*. It does not rescale them: #191 rules that a future curve migration must preserve each node's archival deadline rather than apply a constant factor, and this issue introduces no curve change to migrate.

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine/test_lifecycle_model_version.py`:

```python
"""Integer lifecycle-model version replaces the boolean fsrs_migrated flag (#221)."""

from __future__ import annotations

from ormah.engine.memory_engine import LIFECYCLE_MODEL_VERSION
from ormah.models.node import CreateNodeRequest, NodeType, Tier


def _version(engine) -> str | None:
    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
    ).fetchone()
    return row["value"] if row else None


def _make_node(engine) -> str:
    """A real node, so the seed has something to act on — an empty table would
    make every assertion below pass vacuously."""
    node_id, _ = engine.remember(CreateNodeRequest(
        content="A node the migration will or will not reseed",
        type=NodeType.fact,
        tier=Tier.working,
        title="Migration subject",
    ))
    return node_id


def _stability(engine, node_id: str) -> float:
    return engine.db.conn.execute(
        "SELECT stability FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()["stability"]


def test_the_version_constant_is_two():
    """1 = the legacy FSRS seed; 2 = bounded reinforcement."""
    assert LIFECYCLE_MODEL_VERSION == 2


def test_a_fresh_store_ends_at_the_current_version(engine):
    assert _version(engine) == "2"


def test_a_legacy_store_is_backfilled_without_reseeding(engine):
    """AC6: fsrs_migrated='1' means the seed already ran — record it as version 1."""
    node_id = _make_node(engine)
    # Simulate a store migrated by the old boolean flag: drop the new key, restore
    # the legacy one, and set a stability the seed would overwrite if it re-ran.
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('fsrs_migrated', '1')"
    )
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 42.0, access_count = 5 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    engine._migrate_fsrs()

    assert _version(engine) == "2"
    assert _stability(engine, node_id) == 42.0, "the seed re-ran on an already-migrated store"


def test_an_unmigrated_store_still_gets_seeded(engine):
    node_id = _make_node(engine)
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'fsrs_migrated'")
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, access_count = 5 WHERE id = ?", (node_id,)
    )
    engine.db.conn.commit()

    engine._migrate_fsrs()

    assert _version(engine) == "2"
    assert _stability(engine, node_id) == 10.0, "min(30, access_count * 2) was not applied"


def test_the_version_read_survives_a_corrupt_value(engine):
    engine.db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_model_version', 'banana')"
    )
    engine.db.conn.commit()

    assert engine._lifecycle_model_version() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_lifecycle_model_version.py -v`
Expected: collection error — `ImportError: cannot import name 'LIFECYCLE_MODEL_VERSION'`.

- [ ] **Step 3: Add the constant**

In `src/ormah/engine/memory_engine.py`, next to the existing `_EMBEDDING_SCHEMA_VERSION` module constant:

```python
# Lifecycle-model version. 1 = the legacy FSRS seed (previously recorded as the
# boolean meta key 'fsrs_migrated'); 2 = bounded reinforcement (#221). An integer
# so a future curve migration can tell which model produced the stored values.
LIFECYCLE_MODEL_VERSION = 2
```

- [ ] **Step 4: Rewrite `_migrate_fsrs`**

Replace lines 159-197 entirely:

```python
    def _migrate_fsrs(self) -> None:
        """Seed FSRS stability once, and record the store's lifecycle-model version."""
        version = self._lifecycle_model_version()
        if version >= LIFECYCLE_MODEL_VERSION:
            return

        if version == 0:
            self._seed_stability_from_access_count()

        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES "
                "('lifecycle_model_version', ?)",
                (str(LIFECYCLE_MODEL_VERSION),),
            )

    def _lifecycle_model_version(self) -> int:
        """Read the store's lifecycle-model version, upgrading the legacy flag.

        Stores written before #221 only carry the boolean 'fsrs_migrated' key,
        which could say migrated/not-migrated and nothing else; it maps to
        version 1. An unreadable value is treated as 0 so the seed re-runs
        rather than being silently skipped.
        """
        row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
        ).fetchone()
        if row:
            try:
                return int(row["value"])
            except (TypeError, ValueError):
                return 0

        legacy = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'fsrs_migrated'"
        ).fetchone()
        return 1 if legacy else 0

    def _seed_stability_from_access_count(self) -> None:
        """Seed FSRS stability from access_count, updating both DB and markdown."""
        rows = self.db.conn.execute(
            "SELECT id, access_count, last_accessed FROM nodes"
        ).fetchall()

        with self.db.transaction() as conn:
            for r in rows:
                access_count = r["access_count"] or 0
                stability = min(30.0, access_count * 2.0) if access_count > 0 else 1.0
                last_review = r["last_accessed"]

                # Update DB
                conn.execute(
                    "UPDATE nodes SET stability = ?, last_review = ? WHERE id = ?",
                    (stability, last_review, r["id"]),
                )

                # Update markdown file
                node = self.file_store.load(r["id"])
                if node is not None:
                    node.stability = stability
                    if last_review:
                        try:
                            node.last_review = datetime.fromisoformat(last_review)
                        except (ValueError, TypeError):
                            pass
                    self.file_store.save(node)

        logger.info("FSRS data migration complete: seeded %d nodes from access_count", len(rows))
```

The seeding body is unchanged apart from losing the `fsrs_migrated` write — the version write now lives in `_migrate_fsrs`, which owns it for both paths.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_engine/test_lifecycle_model_version.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run the engine suite**

Run: `./.venv/bin/python -m pytest tests/test_engine/ -v`
Expected: all pass. Startup runs `_migrate_fsrs` on every engine fixture, so a regression here fails broadly.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "refactor(lifecycle): integer lifecycle-model version replaces the fsrs_migrated flag (#221)"
```

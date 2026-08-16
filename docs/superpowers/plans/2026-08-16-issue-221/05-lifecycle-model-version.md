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
| No `lifecycle_model_version`, no `fsrs_migrated`, no node carries `last_review` | `0` | seed from `access_count`, then write `2` + `fsrs_migrated` |
| No `lifecycle_model_version`, no `fsrs_migrated`, but some node carries `last_review` | `1` | **skip the seed**, write `2` + `fsrs_migrated` |
| No `lifecycle_model_version`, `fsrs_migrated = '1'` | `1` | skip the seed, write `2` + `fsrs_migrated` |
| `lifecycle_model_version` present but unreadable | `1` | **skip the seed** (fail closed), rewrite both keys |
| `lifecycle_model_version = 2` | `2` | nothing |

Version `2` records *which model produced the stored stabilities*. It does not rescale them: #191 rules that a future curve migration must preserve each node's archival deadline rather than apply a constant factor, and this issue introduces no curve change to migrate.

**Two council findings shaped the table above — do not simplify it back.**

*C3 (high, Codex).* The version lives only in SQLite `meta`, and `backup.py:331-334` excludes
`index.db`, `index.db-shm` and `index.db-wal` from every backup. A fresh-device restore brings
back Markdown carrying valid `stability`, but the index is rebuilt empty — no version key. Mapping
that to `0` runs the seed, which overwrites every stability with `min(30, access_count * 2)` **and
rewrites the Markdown**, the actual source of truth. That violates this plan's own "do not rescale
existing stability" constraint, through a supported recovery path rather than manual corruption.
A "some stability != 1.0" guard is not enough: `fsrs_growth_factor = 0.001` with 2-decimal
rounding, or `fsrs_max_stability = 1.0`, both leave every node at exactly `1.0` under model v2.

The durable signal already exists and was simply never consulted: `last_review` is written to the
Markdown frontmatter (`markdown.py:72-73`) and restored into SQLite on rebuild (`builder.py:161`).
Any store that ever ran the seed or a reinforcement carries it, and it survives backup, restore and
`full_rebuild`. The residual case is harmless: `access_count > 0` implies a reinforcement happened,
hence `last_review` is set; and with `access_count = 0` the seed returns `1.0` anyway.

*I1 (medium, Cursor).* A store created under #221 would carry only `lifecycle_model_version`. A
binary from before `a28837b` does not know that key, sees `fsrs_migrated` absent, and reseeds. Both
keys are therefore written together, so rolling back stays safe.

**What the C3 guard does NOT cover — scope boundary, council round 2 (both peers, `high`).**

The `last_review` guard protects exactly one shape of restore: the one where the index is *gone*,
so `meta` comes back empty. It does nothing for a restore onto an installation whose index is
still there, and that path is real:

- `IndexBuilder.full_rebuild` (`builder.py:24-36`) clears `node_tags`, `edges`, `nodes_fts`,
  `nodes` and `node_vectors`, but from `meta` it deletes only `auto_link_watermark`. Every other
  key — including the version — survives the rebuild.
- `MemoryEngine.reload_restored_graph` (`memory_engine.py:1237-1244`) calls `rebuild_index()` and
  never calls `_migrate_fsrs`, which runs only from `__init__` (`memory_engine.py:151`).

So restoring a pre-FSRS backup onto an already-migrated install keeps `lifecycle_model_version = 2`,
hits the early return, and never reaches the guard at all. Those nodes keep `stability = 1.0`
instead of `min(30, access_count * 2)`.

**This is a pre-existing defect, not one this issue creates.** On `a28837b` today, `_migrate_fsrs`
already returns early on `if fsrs_migrated: return`, with the same result. #221 inherits it and —
until this paragraph was added — advertised it as handled. **Fixing it is out of scope here**
(decision: André, 2026-08-16) and belongs to its own issue — r-spade/ormah#236 — whose shape is: treat the lifecycle
keys as derived state (delete them in `full_rebuild`, same as `auto_link_watermark`) and call
`_migrate_fsrs` at the end of `rebuild_index`, with an end-to-end restore test.

Do not claim anywhere in this plan, in the PR body, or in the docs that the C3 guard covers
restore in general. It covers the empty-`meta` case only.

An unreadable version is now treated as **already migrated** rather than `0` — the original plan had
this backwards. Skipping a seed is inert; running one is destructive.

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
    # A genuinely pre-FSRS store: no node has ever been seeded or reinforced.
    # Stated explicitly rather than assumed — this is what separates it from the
    # rebuilt-index case below, and the whole seed decision now rests on it.
    engine.db.conn.execute("UPDATE nodes SET last_review = NULL")
    engine.db.conn.commit()

    engine._migrate_fsrs()

    assert _version(engine) == "2"
    assert _stability(engine, node_id) == 10.0, "min(30, access_count * 2) was not applied"


def test_a_corrupt_version_fails_closed_as_migrated(engine):
    """Skipping a seed is inert; running one overwrites stability. Fail closed."""
    engine.db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_model_version', 'banana')"
    )
    engine.db.conn.commit()

    assert engine._lifecycle_model_version() == 1


def test_a_rebuilt_index_does_not_reseed_earned_stability(engine):
    """C3: SQLite is excluded from backups, so a restore arrives with no meta.

    The Markdown still carries stability and last_review, so the store is not a
    pre-FSRS one and must not be reseeded.

    SCOPE, stated so nobody reads more into a green than it carries: this covers
    the EMPTY-meta restore only. It deletes the keys by hand and calls
    _migrate_fsrs directly — it goes through neither full_rebuild nor
    reload_restored_graph. The same-device restore, where meta survives the
    rebuild and _migrate_fsrs is never called, is a pre-existing defect tracked
    outside this issue (see the scope boundary above). This test passing does
    NOT mean restore is safe in general.
    """
    node_id = _make_node(engine)
    now = datetime.now(timezone.utc)
    engine.db.conn.execute(
        "UPDATE nodes SET stability = 1.0, access_count = 7, last_review = ? WHERE id = ?",
        (now.isoformat(), node_id),
    )
    # Exactly what a fresh-device restore or a deleted index looks like.
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'fsrs_migrated'")
    engine.db.conn.commit()

    engine._migrate_fsrs()

    # Without the last_review guard the seed would write min(30, 7*2) = 14.0.
    assert _stability(engine, node_id) == 1.0
    assert _version(engine) == "2"


def test_the_legacy_flag_is_written_alongside_the_version(engine):
    """I1: a rollback to a binary that only knows fsrs_migrated must not reseed."""
    row = engine.db.conn.execute(
        "SELECT value FROM meta WHERE key = 'fsrs_migrated'"
    ).fetchone()
    assert row is not None and row["value"] == "1"
```

Add `from datetime import datetime, timezone` to the test file's imports.

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
            # Keep the legacy flag in sync so rolling back to a binary that only
            # knows 'fsrs_migrated' does not reseed a store built under #221.
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('fsrs_migrated', '1')"
            )

    def _lifecycle_model_version(self) -> int:
        """Read the store's lifecycle-model version, upgrading the legacy flag.

        Stores written before #221 only carry the boolean 'fsrs_migrated' key,
        which could say migrated/not-migrated and nothing else; it maps to
        version 1.

        Every fallback here fails closed at 1 (already migrated), because the
        only action version 0 unlocks is a destructive one: the seed overwrites
        stability and rewrites the Markdown. Skipping a needed seed leaves
        defaults in place; running an unneeded one destroys real values.
        """
        row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
        ).fetchone()
        if row:
            try:
                return int(row["value"])
            except (TypeError, ValueError):
                return 1

        legacy = self.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'fsrs_migrated'"
        ).fetchone()
        if legacy:
            return 1

        # No meta at all. SQLite is derived and excluded from backups
        # (backup.py:331-334), so this is also what a fresh-device restore or a
        # deleted index looks like — not only a genuinely pre-FSRS store. Ask
        # the durable source instead: last_review lives in the Markdown
        # frontmatter (markdown.py:72-73) and is restored on rebuild
        # (builder.py:161), so any store that ever seeded or reinforced carries
        # it. Seeding over that would overwrite stability the user actually earned.
        reviewed = self.db.conn.execute(
            "SELECT 1 FROM nodes WHERE last_review IS NOT NULL LIMIT 1"
        ).fetchone()
        return 1 if reviewed else 0

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
Expected: 7 passed.

`test_a_rebuilt_index_does_not_reseed_earned_stability` is the one that matters most: drop the
`last_review` guard from `_lifecycle_model_version` and it must report `stability == 14.0`
instead of `1.0`. Verify that by hand once before moving on — a guard nobody ever saw fail is
a guard nobody knows works.

- [ ] **Step 6: Run the engine suite**

Run: `./.venv/bin/python -m pytest tests/test_engine/ -v`
Expected: all pass. Startup runs `_migrate_fsrs` on every engine fixture, so a regression here fails broadly.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "refactor(lifecycle): integer lifecycle-model version replaces the fsrs_migrated flag (#221)"
```

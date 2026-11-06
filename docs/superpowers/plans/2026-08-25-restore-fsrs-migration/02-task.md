> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 2: Per-node seed eligibility

Raised by the Dev Council. Round 1 (Codex F1/F2/F3): the store-wide seed
overwrites externally authored `stability`, skips mixed stores entirely, and
strands a partially seeded graph on an I/O failure — all three collapse into
one change, decide eligibility per node. Round 2 (Codex F2) and round 3
(Cursor F1) add the other half: never record a version over a graph that did
not fully index, and put that check inside `_migrate_fsrs`, because the two
callers this issue is about — `startup()` and `BackupService.rebuild_index` —
would never read a flag left on the builder.

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:230-260` (`_seed_stability_from_access_count`)
- Modify: `src/ormah/engine/memory_engine.py:169-188` (`_migrate_fsrs`: seed condition and version write)
- Test: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes (existing): `MemoryEngine._lifecycle_model_version()` — unchanged; still returns 0/1/2 and decides which version is recorded.
- Produces: `_seed_stability_from_access_count()` mutates only nodes matching `last_review IS NULL AND stability = 1.0 AND access_count > 0`. `_migrate_fsrs()` calls it whenever the recorded version is below `LIFECYCLE_MODEL_VERSION` (previously: only at version 0), and writes `lifecycle_model_version` / `fsrs_migrated` only when `len(self.file_store.list_paths()) == SELECT COUNT(*) FROM nodes`. Tasks 3 and 4 rely on both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine/test_lifecycle_model_version.py`:

```python
def _unmigrated_meta(engine) -> None:
    """Put the store back to 'no lifecycle marker', the way full_rebuild does."""
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'lifecycle_model_version'")
    engine.db.conn.execute("DELETE FROM meta WHERE key = 'fsrs_migrated'")
    engine.db.conn.commit()


def _write_lifecycle(engine, node_id: str, *, stability: float,
                     access_count: int, last_review) -> None:
    """Set a node's lifecycle fields in the DURABLE source, then reindex.

    Council round 3, Cursor F3: a fixture that only UPDATEs SQLite proves
    nothing about restore, because full_rebuild reindexes from Markdown and
    throws the DB row away. Everything these tests assert about a restored
    graph has to start on disk.
    """
    node = engine.file_store.load(node_id)
    node.stability = stability
    node.access_count = access_count
    node.last_review = last_review
    engine.file_store.save(node)
    engine.builder.full_rebuild()


def test_the_seed_never_overwrites_stability_it_did_not_produce(engine):
    """Codex F1: externally authored Markdown may carry a real stability with
    no last_review. The invariant that every Ormah writer stamps last_review
    says nothing about such a file, so eligibility must be decided per node."""
    node_id = _make_node(engine)
    _write_lifecycle(engine, node_id, stability=42.0, access_count=5, last_review=None)
    _unmigrated_meta(engine)

    engine._migrate_fsrs()

    assert _stability(engine, node_id) == 42.0, "the seed destroyed a stability it did not write"
    assert _version(engine) == "2"


def test_a_mixed_store_seeds_only_its_unreviewed_nodes(engine):
    """Codex F2: one migrated node must not suppress the seed for the rest."""
    reviewed = _make_node(engine)
    unreviewed = _make_node(engine)
    _write_lifecycle(engine, reviewed, stability=42.0, access_count=5,
                     last_review=datetime.now(timezone.utc))
    _write_lifecycle(engine, unreviewed, stability=1.0, access_count=5, last_review=None)
    _unmigrated_meta(engine)

    engine._migrate_fsrs()

    assert _stability(engine, reviewed) == 42.0, "an earned value was reseeded"
    assert _stability(engine, unreviewed) == 10.0, "a pre-FSRS node was skipped"


def test_a_node_with_no_usage_history_is_left_alone(engine):
    """access_count = 0 carries no signal, so the seed must not touch the node
    — not its stability, and not its last_review."""
    node_id = _make_node(engine)
    _write_lifecycle(engine, node_id, stability=1.0, access_count=0, last_review=None)
    _unmigrated_meta(engine)

    engine._migrate_fsrs()

    row = engine.db.conn.execute(
        "SELECT stability, last_review FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    assert row["stability"] == 1.0
    assert row["last_review"] is None, "the seed stamped a node it did not change"


def test_an_interrupted_seed_resumes_on_the_next_run(engine):
    """Codex F3: Markdown writes are not rolled back with the DB transaction.
    The per-node predicate is what makes the retry correct — a node already
    seeded no longer qualifies, one not yet reached still does."""
    first = _make_node(engine)
    second = _make_node(engine)
    for node_id in (first, second):
        _write_lifecycle(engine, node_id, stability=1.0, access_count=5, last_review=None)
    _unmigrated_meta(engine)

    real_save = engine.file_store.save
    saved: list[str] = []

    def save_once_then_fail(node):
        if saved:
            raise OSError("disk full")
        saved.append(node.id)
        return real_save(node)

    engine.file_store.save = save_once_then_fail
    with pytest.raises(OSError):
        engine._migrate_fsrs()
    engine.file_store.save = real_save

    assert _version(engine) is None, "a version was recorded over a failed seed"

    engine._migrate_fsrs()

    assert _stability(engine, first) == 10.0
    assert _stability(engine, second) == 10.0
    assert _version(engine) == "2"


def test_no_version_is_recorded_while_a_file_is_missing_from_the_index(engine):
    """Council round 2 (Codex F2) / round 3 (Cursor F1): recording version 2
    over a graph that did not fully index strands every node that only lands on
    a later incremental pass. The check has to live here, because startup() and
    BackupService.rebuild_index call this method without consulting the builder."""
    node_id = _make_node(engine)
    _write_lifecycle(engine, node_id, stability=1.0, access_count=5, last_review=None)
    _unmigrated_meta(engine)
    # A file on disk that never made it into the index — exactly the shape
    # full_rebuild leaves behind when a file fails to hash, parse, or index.
    (engine.file_store.nodes_dir / "broken.md").write_text("not: [valid", encoding="utf-8")

    engine._migrate_fsrs()

    assert _version(engine) is None, "a version was recorded over an incomplete graph"
    assert _stability(engine, node_id) == 10.0, "indexed nodes were not seeded"

    (engine.file_store.nodes_dir / "broken.md").unlink()
    engine._migrate_fsrs()

    assert _version(engine) == "2"
```

Add `import pytest` to the imports at the top of the file if it is not already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine/test_lifecycle_model_version.py -v -k "never_overwrites or mixed_store or no_usage_history or interrupted or missing_from_the_index"`
Expected: `never_overwrites` FAILS (`42.0` becomes `10.0`); `mixed_store` FAILS (unreviewed stays `1.0`, because the store-wide guard returns 1 and the seed never runs); `no_usage_history` FAILS on `last_review is None`; `interrupted` FAILS (the second node stays `1.0` on retry); `missing_from_the_index` FAILS on `_version is None` (a version is recorded despite `broken.md`).

- [ ] **Step 3: Write the implementation**

In `src/ormah/engine/memory_engine.py`, replace the body of `_seed_stability_from_access_count` (lines 230-260):

```python
    def _seed_stability_from_access_count(self) -> None:
        """Seed FSRS stability from access_count, updating both DB and markdown.

        Eligibility is per node, not per store (#236, council round 1). A node
        qualifies only when it carries no evidence of its own lifecycle state:
        no last_review, the default stability, and a real usage history. Any
        other node — one Ormah reinforced, one seeded by an earlier run, one an
        external tool wrote a real stability into — is left untouched in the DB
        and on disk. Fail-closed, because the seed is destructive: skipping a
        node leaves a default in place, seeding one destroys a real value.

        This is also what makes the migration resumable. Markdown writes below
        are not rolled back with the DB transaction, so a failed save leaves
        earlier files rewritten; on the next run those nodes no longer qualify
        and the ones not yet reached still do.
        """
        rows = self.db.conn.execute(
            "SELECT id, access_count, last_accessed FROM nodes "
            "WHERE last_review IS NULL AND stability = 1.0 AND access_count > 0"
        ).fetchall()

        with self.db.transaction() as conn:
            for r in rows:
                stability = min(30.0, r["access_count"] * 2.0)
                last_review = r["last_accessed"]

                conn.execute(
                    "UPDATE nodes SET stability = ?, last_review = ? WHERE id = ?",
                    (stability, last_review, r["id"]),
                )

                node = self.file_store.load(r["id"])
                if node is not None:
                    node.stability = stability
                    if last_review:
                        try:
                            node.last_review = datetime.fromisoformat(last_review)
                        except (ValueError, TypeError):
                            pass
                    self.file_store.save(node)

        logger.info("FSRS data migration: seeded %d eligible nodes from access_count", len(rows))
```

Then rewrite `_migrate_fsrs` (lines 169-188). Replace:

```python
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
```

with:

```python
        version = self._lifecycle_model_version()
        if version >= LIFECYCLE_MODEL_VERSION:
            return

        # Run the seed for every version below the current model, not only for
        # a store-wide "pre-FSRS" verdict (#236, council round 1, Codex F2). A
        # restored graph can mix externally authored pre-FSRS nodes with Ormah's
        # own; the store-wide guard resolves such a graph as migrated and would
        # skip all of them. The per-node predicate inside the seed is what keeps
        # this safe — on a store with nothing to do it matches no rows.
        self._seed_stability_from_access_count()

        if not self._graph_is_fully_indexed():
            # Recording a version over a partial graph is the one irreversible
            # mistake here (council round 2, Codex F2; round 3, Cursor F1): a
            # pre-FSRS node that lands on a later incremental pass would sit
            # behind the early return above forever. Seeding what IS indexed is
            # safe and idempotent, so keep it and simply withhold the marker.
            logger.warning(
                "Lifecycle migration ran on an incomplete graph; withholding the "
                "version marker so the next start re-evaluates it."
            )
            return

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

    def _graph_is_fully_indexed(self) -> bool:
        """True when every Markdown node file has a row in the index.

        full_rebuild logs and skips files it cannot hash, parse, or index, then
        returns a partial count, so "the rebuild finished" does not mean "the
        graph is whole". The check belongs here rather than on the caller: both
        paths this issue is about — startup() and BackupService.rebuild_index —
        reach the migration without ever seeing the builder's bookkeeping.

        list_paths() globs nodes/*.md only, and soft-deleted files are moved to
        deleted/, so tombstones are absent from both sides of the comparison.
        """
        indexed = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        return len(self.file_store.list_paths()) == indexed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engine/test_lifecycle_model_version.py -v`
Expected: all PASS, including the pre-existing `test_a_legacy_store_is_backfilled_without_reseeding`, `test_an_unmigrated_store_still_gets_seeded` and `test_a_rebuilt_index_does_not_reseed_earned_stability`. If `test_a_legacy_store_...` fails, read it before touching it: it sets `stability = 42.0`, so the predicate must already exclude that node — a failure there means the SQL filter is wrong, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "fix(lifecycle): decide FSRS seed eligibility per node (#236)"
```

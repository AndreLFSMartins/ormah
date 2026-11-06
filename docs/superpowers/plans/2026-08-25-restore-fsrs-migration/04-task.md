> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 4: End-to-end restore through `BackupService`

**Files:**
- Test: `tests/test_backup.py`

**Interfaces:**
- Consumes: Task 1 (`full_rebuild` clears keys, reached via `BackupService.rebuild_index`), Task 2 (per-node seed and the withheld version marker) and the existing `MemoryEngine.startup() -> _migrate_fsrs` path (`memory_engine.py:121-161` — it is `startup()`, not `__init__`). No production code change expected; if these tests fail after Tasks 1-3, that is a finding to report, not a reason to edit them.

- [ ] **Step 1: Write the test**

Append to `tests/test_backup.py`:

```python
def test_restore_onto_existing_index_seeds_pre_fsrs_backup(tmp_path):
    """#236, CLI path: a backup holding pre-FSRS Markdown (no last_review,
    access_count > 0) is restored onto a memory dir whose index.db already
    says 'migrated'. The next engine start must seed stability from
    access_count instead of trusting the stale marker."""
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    memory_dir.mkdir()
    (memory_dir / "nodes").mkdir()

    # The backup: one pre-FSRS node, written straight to Markdown.
    pre_fsrs = MemoryNode(
        type=NodeType.fact,
        title="Pre-FSRS",
        content="Used five times before FSRS existed",
        access_count=5,
        stability=1.0,
        last_review=None,
    )
    FileStore(memory_dir / "nodes").save(pre_fsrs)
    service = _service(memory_dir, backup_dir)
    backup = service.create(now=datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc))

    # The target: an engine that has already migrated a different graph.
    for path in (memory_dir / "nodes").glob("*.md"):
        path.unlink()
    settings = Settings(memory_dir=memory_dir)
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        row = engine.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
        ).fetchone()
        assert row["value"] == "2"
    finally:
        engine.shutdown()

    service.restore(backup.name)

    engine = MemoryEngine(settings)
    engine.startup()
    try:
        stability = engine.db.conn.execute(
            "SELECT stability FROM nodes WHERE id = ?", (pre_fsrs.id,)
        ).fetchone()["stability"]
        assert stability == 10.0, "restore onto an existing index skipped the FSRS seed"
        assert engine.file_store.load(pre_fsrs.id).stability == 10.0
    finally:
        engine.shutdown()
```

- [ ] **Step 2: Verify the test fails without the fix**

Council round 3 (Cursor F4) killed an earlier version of this step that used
`git revert --no-commit HEAD~1`: after Tasks 1-3 that reverts the per-node seed,
not the builder change, and its recovery line never restored `memory_engine.py`.
Revert by path instead, and only the one file the red state needs:

```bash
git checkout HEAD~3 -- src/ormah/index/builder.py
python -m pytest tests/test_backup.py -v -k "seeds_pre_fsrs_backup or withholds_the_version"
```
Expected: both new tests FAIL — `seeds_pre_fsrs_backup` on `stability == 10.0`
(stays `1.0`, because the stale `lifecycle_model_version` survives the rebuild).

Restore the tree and confirm nothing else moved:

```bash
git checkout HEAD -- src/ormah/index/builder.py
git status --short   # only tests/test_backup.py may be modified
```

`HEAD~3` is Task 1's parent given three commits (Tasks 1, 2, 3). If your history
differs, resolve it explicitly rather than counting: `git log --oneline -4` and
check out `src/ormah/index/builder.py` from the commit BEFORE the one whose
subject is `fix(index): full_rebuild clears the lifecycle migration keys (#236)`.

- [ ] **Step 2b: Write the incomplete-graph end-to-end test**

Append to `tests/test_backup.py`:

```python
def test_restore_withholds_the_version_while_a_file_cannot_be_indexed(tmp_path):
    """Council round 3 (Cursor F1): the CLI restore path reaches the migration
    through startup(), which never sees the builder's bookkeeping. If a version
    were recorded over a partial graph, the node that only indexes on a later
    pass would sit behind the early return forever."""
    memory_dir = tmp_path / "memory"
    backup_dir = tmp_path / "backups"
    memory_dir.mkdir()
    (memory_dir / "nodes").mkdir()

    pre_fsrs = MemoryNode(
        type=NodeType.fact,
        title="Pre-FSRS",
        content="Used five times before FSRS existed",
        access_count=5,
        stability=1.0,
        last_review=None,
    )
    FileStore(memory_dir / "nodes").save(pre_fsrs)
    (memory_dir / "nodes" / "broken.md").write_text("not: [valid", encoding="utf-8")
    service = _service(memory_dir, backup_dir)
    backup = service.create(now=datetime(2026, 8, 25, 13, 0, 0, tzinfo=timezone.utc))

    for path in (memory_dir / "nodes").glob("*.md"):
        path.unlink()
    service.restore(backup.name)

    settings = Settings(memory_dir=memory_dir)
    engine = MemoryEngine(settings)
    engine.startup()
    try:
        version = engine.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
        ).fetchone()
        assert version is None, "a version was recorded while broken.md was unindexed"
        stability = engine.db.conn.execute(
            "SELECT stability FROM nodes WHERE id = ?", (pre_fsrs.id,)
        ).fetchone()["stability"]
        assert stability == 10.0, "the indexed node was not seeded"
    finally:
        engine.shutdown()

    # Repair the file into a second pre-FSRS node; the next start completes.
    repaired = MemoryNode(
        type=NodeType.fact,
        title="Repaired",
        content="Also used five times",
        access_count=5,
        stability=1.0,
        last_review=None,
    )
    (memory_dir / "nodes" / "broken.md").unlink()
    FileStore(memory_dir / "nodes").save(repaired)

    engine = MemoryEngine(settings)
    engine.startup()
    try:
        engine.rebuild_index()
        version = engine.db.conn.execute(
            "SELECT value FROM meta WHERE key = 'lifecycle_model_version'"
        ).fetchone()
        assert version["value"] == "2"
        stability = engine.db.conn.execute(
            "SELECT stability FROM nodes WHERE id = ?", (repaired.id,)
        ).fetchone()["stability"]
        assert stability == 10.0, "the repaired node was stranded"
    finally:
        engine.shutdown()
```

- [ ] **Step 3: Run the test with the fix in place**

Run: `python -m pytest tests/test_backup.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backup.py
git commit -m "test(backup): restore onto an existing index seeds pre-FSRS nodes (#236)"
```

---


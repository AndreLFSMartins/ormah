> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 1: The seed runs on every call

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:169-181` (`_migrate_fsrs`)
- Test: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes (existing): `MemoryEngine._lifecycle_model_version() -> int`, `MemoryEngine._seed_stability_from_access_count() -> None`, `MemoryEngine._graph_is_fully_indexed() -> bool`, `LIFECYCLE_MODEL_VERSION`.
- Consumes (existing test helpers, already defined at the top of the test file — use them, do not redefine): `_make_node(engine) -> str`, `_version(engine) -> str | None`, `_stability(engine, node_id) -> float`.
- Produces: `_migrate_fsrs()` calls `_seed_stability_from_access_count()` unconditionally, before reading whether the recorded version is already current. Task 2 relies on the guard still running only while the version is below current.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine/test_lifecycle_model_version.py`:

```python
def test_a_node_indexed_after_the_migration_is_still_seeded(engine):
    """#236, council round 4 (Codex, high @ 0.98): the store-wide marker must
    not gate the per-node seed. A pre-FSRS Markdown node dropped into nodes/ by
    an external tool and picked up by incremental_update arrives AFTER the store
    already records version 2. Under the old early return it kept stability 1.0
    forever, so decay treated a well-used memory as brand new."""
    assert _version(engine) == "2"

    latecomer = MemoryNode(
        type=NodeType.fact,
        title="Latecomer",
        content="Used five times before FSRS existed",
        access_count=5,
        stability=1.0,
        last_review=None,
    )
    engine.file_store.save(latecomer)
    engine.builder.incremental_update()

    engine._migrate_fsrs()

    assert _stability(engine, latecomer.id) == 10.0, (
        "the store-wide version marker short-circuited the per-node seed"
    )
    assert engine.file_store.load(latecomer.id).stability == 10.0, "Markdown was not reseeded"
    assert _version(engine) == "2", "the marker should be left exactly as it was"
```

Add `MemoryNode` to the existing `from ormah.models.node import ...` line at the top of the file if it is not already there. `NodeType` is already imported.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome \
  python -m pytest tests/test_engine/test_lifecycle_model_version.py -v -k "indexed_after_the_migration"
```

Expected: FAIL on `assert _stability(...) == 10.0` — the value is `1.0`, because `_migrate_fsrs` returns at `version >= LIFECYCLE_MODEL_VERSION` before ever reaching the seed.

- [ ] **Step 3: Write minimal implementation**

In `src/ormah/engine/memory_engine.py`, replace these lines of `_migrate_fsrs`:

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
```

with:

```python
        # The seed runs on every call, gated by nothing (#236, council round 4,
        # Codex high@0.98). A store-wide marker cannot decide a per-node
        # question: a pre-FSRS node can arrive at any time — an external tool
        # writes it into nodes/ and incremental_update indexes it — long after
        # the store records the current version. Gating the seed on that marker
        # stranded such a node at stability 1.0 forever. The per-node predicate
        # inside the seed is what makes this cheap and safe: on a store with
        # nothing to do it matches no rows, and a node it already seeded no
        # longer qualifies.
        self._seed_stability_from_access_count()

        version = self._lifecycle_model_version()
        if version >= LIFECYCLE_MODEL_VERSION:
            return
```

Leave the rest of the method — the `_graph_is_fully_indexed()` guard, its warning, and the two `INSERT OR REPLACE` statements — exactly as they are.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
env HOME=/private/tmp/claude-501/-Users-andre-Documents-GitHub-Tools-ormah-wt-236/bfc80cca-2299-49d6-8031-0bef47a85395/scratchpad/fakehome \
  python -m pytest tests/test_engine/test_lifecycle_model_version.py -v
```

Expected: all PASS, including every pre-existing test named in the overview's Global Constraints. If `test_a_rebuilt_index_does_not_reseed_earned_stability` or `test_a_restore_onto_an_existing_index_keeps_earned_stability` fails, do NOT edit it — it means the seed is touching a node it must not, which is a design failure to report.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "fix(lifecycle): the FSRS seed runs on every migration call (#236)"
```

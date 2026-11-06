> Overview: [00-overview.md](00-overview.md). Read it first; it carries the header, Global Constraints, and task order.

### Task 3: `rebuild_index` re-runs the FSRS migration

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:1322-1326` (`rebuild_index`)
- Modify: `src/ormah/engine/memory_engine.py:2036-2046` (lock-order docstring in `_record_confirmed_use`)
- Modify: `tests/test_engine/test_lifecycle_model_version.py:100-106` (scope note)
- Test: `tests/test_engine/test_lifecycle_model_version.py`

**Interfaces:**
- Consumes: Task 1 — `full_rebuild()` leaves no lifecycle keys in `meta`.
- Consumes: Task 2 — `_migrate_fsrs()` runs the seed for any version below 2, seeds only nodes matching `last_review IS NULL AND stability = 1.0 AND access_count > 0`, and withholds the version marker while the graph is incomplete. This task therefore calls it unconditionally; the guard is inside.
- Consumes (existing): `MemoryEngine._migrate_fsrs()`, `MemoryEngine._lifecycle_model_version()`, `_serialized_memory_operation` decorator (`memory_engine.py:89`), `MemoryEngine.reload_restored_graph()` (already decorated, calls `self.rebuild_index()`).
- Produces: `MemoryEngine.rebuild_index() -> int` is a serialized memory operation that ends with `self._migrate_fsrs()`. Task 4's end-to-end test relies on the same migration via `MemoryEngine.startup()`, not on this method.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine/test_lifecycle_model_version.py`:

```python
def _rewrite_as_pre_fsrs(engine, node_id: str, access_count: int) -> None:
    """Rewrite one node's Markdown the way a pre-FSRS store would have it:
    no last_review, default stability, but a real usage history."""
    node = engine.file_store.load(node_id)
    node.last_review = None
    node.stability = 1.0
    node.access_count = access_count
    engine.file_store.save(node)


def test_a_restore_onto_an_existing_index_seeds_pre_fsrs_nodes(engine):
    """#236: the store was already migrated (version 2 in meta), then the
    Markdown is replaced by pre-FSRS nodes and the graph is reloaded. The
    surviving marker must not short-circuit the seed."""
    node_id = _make_node(engine)
    assert _version(engine) == "2"
    _rewrite_as_pre_fsrs(engine, node_id, access_count=5)

    engine.reload_restored_graph()

    assert _stability(engine, node_id) == 10.0, "min(30, access_count * 2) was not applied"
    assert _version(engine) == "2"
    assert engine.file_store.load(node_id).stability == 10.0, "Markdown was not reseeded"


def test_a_restore_onto_an_existing_index_keeps_earned_stability(engine):
    """The inverse of the case above: a store that carries last_review is not
    pre-FSRS, so reloading must leave earned stability alone and simply
    re-record the version."""
    node_id = _make_node(engine)
    node = engine.file_store.load(node_id)
    node.stability = 42.0
    node.access_count = 5
    node.last_review = datetime.now(timezone.utc)
    engine.file_store.save(node)

    engine.reload_restored_graph()

    assert _stability(engine, node_id) == 42.0, "the seed re-ran on a migrated store"
    assert _version(engine) == "2"


def test_an_admin_rebuild_re_records_the_version(engine):
    """rebuild_index is also reachable from the admin route; it must leave the
    store at the current version, not with the keys wiped by full_rebuild."""
    _make_node(engine)

    engine.rebuild_index()

    assert _version(engine) == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine/test_lifecycle_model_version.py -v -k "existing_index or admin_rebuild"`
Expected: `..._seeds_pre_fsrs_nodes` FAILS on `_stability == 10.0` (stays `1.0`, because `rebuild_index` never calls `_migrate_fsrs`); `..._admin_rebuild_re_records_the_version` FAILS on `_version == "2"` (is `None`, because Task 1 cleared the key and nothing re-records it); `..._keeps_earned_stability` FAILS on `_version == "2"` (is `None`).

- [ ] **Step 3: Write minimal implementation**

In `src/ormah/engine/memory_engine.py`, replace lines 1322-1326:

```python
    def rebuild_index(self) -> int:
        """Full rebuild of the index from markdown files, including embeddings."""
        count = self.builder.full_rebuild()
        self._reindex_all_embeddings()
        return count
```

with:

```python
    @_serialized_memory_operation
    def rebuild_index(self) -> int:
        """Full rebuild of the index from markdown files, including embeddings.

        full_rebuild wipes the lifecycle markers (#236), so the migration is
        re-evaluated here; the seed's per-node predicate decides which restored
        nodes are genuinely pre-FSRS, and _migrate_fsrs itself withholds the
        version marker if the rebuild left the graph incomplete. Serialized
        because the seed calls
        file_store inside db.transaction(); holding the memory lock first keeps
        the memory -> db order used by reinforcement.
        """
        count = self.builder.full_rebuild()
        self._reindex_all_embeddings()
        self._migrate_fsrs()
        return count
```

Then in the `_record_confirmed_use` docstring (lines 2036-2046), replace:

```python
        Lock order: this decorator acquires the memory lock before the body
        opens db.transaction(), i.e. memory-lock -> db-lock. The inverse order
        (db-lock -> memory-lock, via file_store calls inside a transaction)
        exists in _seed_stability_from_access_count, _migrate_identity_tiers,
        and _ensure_self_node, but all three run only from startup() before the
        server serves, so the two orders never interleave today. Invariant this
        depends on: never call file_store inside db.transaction() outside
        startup().
```

with:

```python
        Lock order: this decorator acquires the memory lock before the body
        opens db.transaction(), i.e. memory-lock -> db-lock. The inverse order
        (db-lock -> memory-lock, via file_store calls inside a transaction)
        exists in _seed_stability_from_access_count, _migrate_identity_tiers,
        and _ensure_self_node. They run from startup() before the server
        serves, or — for the seed, via rebuild_index (#236) — under
        _serialized_memory_operation, where the memory RLock is already held
        and the order collapses to memory -> db. Invariant this depends on:
        never call file_store inside db.transaction() outside startup() or a
        _serialized_memory_operation.
```

Then in `tests/test_engine/test_lifecycle_model_version.py`, replace lines 100-106 of the `test_a_rebuilt_index_does_not_reseed_earned_stability` docstring:

```python
    SCOPE, stated so nobody reads more into a green than it carries: this covers
    the EMPTY-meta restore only. It deletes the keys by hand and calls
    _migrate_fsrs directly — it goes through neither full_rebuild nor
    reload_restored_graph. The same-device restore, where meta survives the
    rebuild and _migrate_fsrs is never called, is a pre-existing defect tracked
    outside this issue (see the scope boundary above). This test passing does
    NOT mean restore is safe in general.
```

with:

```python
    SCOPE: this covers the EMPTY-meta case at the _migrate_fsrs level only —
    it deletes the keys by hand and never goes through full_rebuild or
    reload_restored_graph. The same-device restore, where meta used to survive
    the rebuild, is covered by test_a_restore_onto_an_existing_index_* below
    (#236).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engine/test_lifecycle_model_version.py tests/test_engine/test_mutation_stamping.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the wider engine and cloud-restore suites for regressions**

Run: `python -m pytest tests/test_engine tests/test_cloud tests/test_backup.py -q`
Expected: all PASS. If a test hangs, suspect a lock re-entry issue: `rebuild_index` is now serialized and must be reached only from code paths that either hold no lock or hold the memory RLock (`reload_restored_graph`, the admin route). Report it rather than removing the decorator.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/engine/memory_engine.py tests/test_engine/test_lifecycle_model_version.py
git commit -m "fix(lifecycle): rebuild_index re-evaluates the FSRS migration (#236)"
```

---


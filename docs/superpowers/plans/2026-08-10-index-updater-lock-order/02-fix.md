# Task 2: Hoist the FileStore calls out of the transaction

**Files:**
- Modify: `src/ormah/index/builder.py:57-91` (`incremental_update`) — line numbers are for
  `upstream/main` (ab1eb85), where this branch is cut. On `local-main` the same method sits at
  105-141 and additionally carries the Beta's `_prior_row` / `_index_file(path, prior)` work (#126),
  which does **not** exist upstream. The body below is the upstream form; the merge into `local-main`
  (Task 4) reconciles the two.

**Interfaces:**
- Consumes: `self.file_store.list_paths() -> list[Path]`, `self.file_store.file_hash(path: Path) -> str`.
- Produces: unchanged public signature — `incremental_update(self) -> tuple[int, int]` returning
  `(added, updated)`.

**Prerequisite:** Task 1's test is committed and fails by hanging. Do not start otherwise.

- [ ] **Step 1: Replace the method body**

Confirm `Path` and `logger` are already imported at the top of `builder.py` before editing; on
`upstream/main` they are.

Replace lines 57-91 of `src/ormah/index/builder.py` with:

```python
    def incremental_update(self) -> tuple[int, int]:
        """Update index for changed/new files. Returns (added, updated) counts."""
        conn = self.db.conn
        added = 0
        updated = 0

        indexed: dict[str, str] = {}
        for row in conn.execute("SELECT id, file_hash FROM nodes").fetchall():
            indexed[row["id"]] = row["file_hash"]

        indexed_ids = set(indexed.keys())
        disk_ids: set[str] = set()

        # Both FileStore calls take L_mem -- the engine hands FileStore its own lock
        # (FileStore(nodes_dir, self._memory_operation_lock)). Calling them inside the write txn
        # would request L_mem while holding L_db, the reverse of the L_mem -> L_db order every
        # @serialized_memory_job background job takes: a deadlock cycle, and this job runs every
        # 60s. Hoisting also halves the I/O done under L_db. full_rebuild already hoists
        # list_paths for the same reason.
        paths = self.file_store.list_paths()
        hashes: dict[Path, str] = {}
        for path in paths:
            try:
                hashes[path] = self.file_store.file_hash(path)
            except Exception as e:
                # A file removed between listing and hashing. This used to be swallowed by the
                # per-path try inside the loop; keep it non-fatal rather than killing the job.
                logger.warning("Failed to hash %s: %s", path, e)

        with self.db.transaction():
            for path in paths:
                if path not in hashes:
                    continue  # hashing failed above; already logged
                try:
                    file_hash = hashes[path]
                    node = parse_node(path.read_text(encoding="utf-8"))
                    disk_ids.add(node.id)

                    if node.id not in indexed:
                        self._index_file(path)
                        added += 1
                    elif indexed[node.id] != file_hash:
                        self._remove_node(node.id, keep_vectors=True)
                        self._index_file(path)
                        updated += 1
                except Exception as e:
                    logger.warning("Failed to process %s: %s", path, e)

            # Remove nodes whose files were deleted
            removed_ids = indexed_ids - disk_ids
            for node_id in removed_ids:
                self._remove_node(node_id)

        return added, updated
```

**Why the `if path not in hashes: continue` matters.** Today `file_hash` runs inside the loop's
`try`, so a file deleted mid-run is logged and skipped. Pre-computing the hashes in a bare dict
comprehension would let that same `OSError` escape and kill the whole job — a regression. The
explicit loop plus the skip preserves the current tolerance exactly.

- [ ] **Step 2: Run the deadlock test — expect PASS**

```bash
python -m pytest tests/test_index/test_builder.py::test_incremental_update_does_not_deadlock_against_a_memory_job -v
```

Expected: **PASS**, and fast — well under the 10 s join.

- [ ] **Step 3: Run the whole index suite**

```bash
python -m pytest tests/test_index/ -v
```

Expected: all pass. `test_db_concurrency.py` lives here and exercises the same locks — it must stay green.

- [ ] **Step 4: Commit the fix**

```bash
git add src/ormah/index/builder.py
git commit -m "fix(lock-order): hoist the index sweep's FileStore calls out of its write txn

incremental_update opened the write txn (L_db) and then called file_store.list_paths
and file_hash, both decorated with the engine's restore-exclusion RLock (L_mem):
L_db -> L_mem. Every @serialized_memory_job background job takes L_mem -> L_db.
Opposite orders on two locks deadlock, and index_updater runs every 60s -- the live
server froze all writes ~2 minutes after each start while reads kept serving.

Verified live by py-spy: auto_linker held L_mem (acquired: True) waiting on L_db at
auto_linker.py:312 while index_updater held L_db waiting on L_mem at builder.py:119,
both jobs stamped with an identical t0. An external BEGIN IMMEDIATE returned
'database is locked' on 10 consecutive probes over 60s; read-only connections passed.

Hoisting both calls above the txn removes the inversion at the root without retaining
any new lock. @serialized_memory_job on the job was rejected: it would hold L_mem
across the whole 36k-file loop every 60s, trading the deadlock for write starvation.
full_rebuild already hoists list_paths -- this aligns incremental_update with the
pattern in its own file, and moves half the loop's I/O out from under L_db.

The hashes are pre-computed in an explicit loop, not a comprehension, so a file
removed between listing and hashing stays non-fatal -- the loop's own try/except
used to absorb exactly that.

Correcting the record: f7ac305 closed this same class for the forgetting sweep and
stated 'Still unaudited: nothing.' That was wrong. Its audit covered the 8 background
jobs and the 10 decorated MemoryEngine writers; IndexBuilder is a third class that
opens transactions and calls FileStore, and index_updater -- registered at
scheduler.py:157 with no @serialized_memory_job -- was the one live inversion left.
A scan finds 11 decorated-FileStore calls under open transactions across 5 blocks;
the other 4 blocks are the two __init__ migrations (single-threaded) and
delete_node_guarded (fixed by f7ac305).

Present unchanged in upstream/main at 0.14.8 -- an upstream defect, not a Beta
regression.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

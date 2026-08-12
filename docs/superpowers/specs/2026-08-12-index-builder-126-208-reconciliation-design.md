# Reconciling #126 (pair-verdict invalidation) with #208 (lock-order hoist) in IndexBuilder

**Date:** 2026-08-12
**Status:** approved (design), not implemented
**Blocks:** the upstream sync (`integration/upstream-sync` → `local-main`, 4 commits)
**Related:** `docs/superpowers/specs/2026-08-10-index-updater-lock-order-design.md` (the lock-order
analysis — severity, `py-spy` evidence, the lock cycle, why not `@serialized_memory_job`). Not
re-derived here.

## Problem

`git merge upstream/main` in the sync worktree conflicts in two files:
`src/ormah/index/builder.py` (4 hunks) and `tests/test_index/test_builder.py` (2 hunks).

This is not a "keep THEIRS" case. `index/builder.py` carries 18 local commits absent upstream.

The conflict is superficial: both changes added a parameter to the same signatures. They are
otherwise orthogonal.

| | origin | when it may be read |
|---|---|---|
| `file_hash` (#208) | `FileStore` → takes `L_mem` | **outside** the write transaction, mandatorily |
| `prior` / `prior_fingerprints` (#126) | `SELECT … FROM nodes` → already `L_db` | inside the transaction |

## Why this must ship with the sync, not after it

The deadlock exposure does not exist in the Beta today and **is introduced by completing the sync**:

| branch | `FileStore.__init__` | takes `L_mem`? |
|---|---|---|
| `local-main` (live Beta) | `(self, nodes_dir)` | no — `_memory_operation_lock` has 0 occurrences in `src/` |
| `integration/upstream-sync` | `(self, nodes_dir, operation_lock=None)`; engine passes the lock | yes |
| `upstream/main` | idem | yes |

`memory_engine.py:201` and `:1486` in the sync worktree pass `self._memory_operation_lock` into the
`FileStore`. A reconciliation that drops #208 therefore ships a Beta that freezes every write
roughly two minutes after each start. #208 is the antidote and must land in the same merge.

## Design

Hoist the `FileStore` reads to before the write transaction (#208); leave the database reads inside
it (#126). Both parameters coexist.

### Signatures

```python
_index_file(path, file_hash, prior=None)
_index_file_nodes_only(path, file_hash, prior=None, prior_fingerprints=None)
```

`file_hash` is positional immediately after `path`, matching upstream, so the #208 tests need no
change. `builder.py:189` (`file_hash = self.file_store.file_hash(path)`) is deleted — eliminating it
is the entire point of #208.

No external callers: the only references outside `builder.py` are six monkeypatches in
`tests/test_index/test_builder.py`.

### Per entry point

**`full_rebuild`** — hashes collected before `with self.db.transaction()`; `prior_fps` stays inside
(it is a `SELECT`). Per path, `continue` when hashing failed, then
`_index_file_nodes_only(path, hashes[path], prior_fingerprints=prior_fps)`.

The two invariants compose fail-closed with no extra code: a failed hash makes `count` skip an
increment, which trips the Beta's abort-on-partial guard (`count != len(paths)` → `RuntimeError` →
rollback). `paths` is materialized before the transaction, so `len(paths)` still counts the skipped
files. A hashing outage therefore rolls back rather than committing a truncated index.

**`incremental_update`** — hashes collected before the transaction; `prior = self._prior_row(node.id)`
stays inside, read before `_remove_node` (#126). Call becomes `_index_file(path, file_hash, prior)`.

Upstream binds `paths = self.file_store.list_paths()` here without wrapping it in `list()` and then
iterates it twice. This is safe only because `list_paths` returns `sorted(...)`, a list. Were it ever
made a generator, the second loop would see nothing, `disk_ids` would stay empty, and
`removed_ids = indexed_ids - disk_ids` would delete every node. Keep the binding materialized.

**`index_single`** — `file_hash` read before the transaction; `prior`, the `unchanged` fingerprint
comparison, and `keep_vectors=unchanged` stay inside.

## Testing

Both test suites must pass together: the #208 coverage (threaded deadlock probe + structural
assertion per entry point) and the #126 coverage (pair-verdict invalidation on changed content,
vector retention on unchanged content).

**The threaded deadlock test must fail as a hang, not as an error.** Run it against the
reconciliation *before* the fix is applied and confirm the failure mode. A test that fails with
`AttributeError` is passing vacuously — the exact false green recorded in session 4, where a
cherry-picked deadlock regression passed because `MemoryEngine` had no `_memory_operation_lock`, the
thread died, and `is_alive()` returned `False`.

## Where the work happens

**In the sync worktree, after the merge — never in `local-main`.** `local-main` has no
`_memory_operation_lock`, so the threaded test cannot be meaningful there; it would pass vacuously.
This is the primary execution risk of this task.

The worktree has no `.venv`, and the main repo's venv has ormah installed editable pointing at the
main repo. Any `pytest` run needs `PYTHONPATH=<worktree>/src`, verified by asserting
`ormah.__file__` resolves inside the worktree before trusting a single result.

## Scope

**In:** the `builder.py` reconciliation, the two test-file conflict hunks, and completing the merge.

**Out**, deliberately — each is real, none blocks this:

- auditing the remaining transaction blocks for other `L_db` → `L_mem` inversions
- a runtime lock-order guard (job failure is invisible in production today: `tracked()` only logs,
  `/admin/health` promotes `degraded` for `embedding_backfill` alone, and the UI surfaces no job
  error at all — a guard would trade a loud failure for a silent one)
- an AST lock-order checker in `make lint`
- job-failure observability, the prerequisite for any production guard
- `make restart` not restarting the launchd Beta

**Timebox: one session.** If the reconciliation does not close, the fallback is not to sync — living
13 commits behind upstream is cheaper than another multi-day cycle.

## Risk register

- **Verified:** both sides of `builder.py` read directly; the #208 diff (`429dd0c`); the absence of
  the lock in `local-main`; the absence of external callers; the abort-on-partial interaction.
- **Assumed:** that the two conflict hunks in `tests/test_index/test_builder.py` resolve by
  coexistence the way the source does. Not yet opened — first thing to check on implementation.
- **Assumed:** that the merge produces no third conflict beyond the two measured files. The
  measurement is from 2026-08-11; re-run `git merge` and abort to confirm before planning around it.

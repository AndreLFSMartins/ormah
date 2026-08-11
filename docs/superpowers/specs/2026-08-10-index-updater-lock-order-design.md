# index_updater lock-order inversion — design

**Date:** 2026-08-10
**Status:** approved, pending implementation
**Severity:** production outage — all memory writes freeze within ~2 minutes of every server start

## Problem

`IndexBuilder.incremental_update` takes the two process-wide locks in the opposite order from
every background memory job. The two orders form a cycle, and the server deadlocks: reads keep
working, every write hangs forever.

The two locks:

| Lock | Object | Taken by |
|---|---|---|
| `L_mem` | `MemoryEngine._memory_operation_lock` (`threading.RLock`, no timeout) | 10 `MemoryEngine` writers, 8 `FileStore` methods, 8 background jobs via `@serialized_memory_job` |
| `L_db` | `Database._lock` (serializes write transactions across threads) | every `db.transaction()` |

The cycle, as captured live:

```text
auto_linker    : L_mem (acquired) -> waits for L_db   [auto_linker.py:312, _apply_edge]
index_updater  : L_db  (acquired) -> waits for L_mem  [builder.py:119, list_paths]
```

`FileStore` receives the *same* lock object as the engine — `memory_engine.py:201`:
`FileStore(settings.nodes_dir, self._memory_operation_lock)`. So a `FileStore` call made inside
a write transaction is a request for `L_mem` while holding `L_db`.

`index_updater` runs **every 60 seconds**, which is why the deadlock reappears about two minutes
after each restart.

## Evidence

Verified on the live server (PID 9604, 0.14.5) on 2026-08-10:

- `/admin/health` 2 ms and `/stats` 301 ms (reads fine); `/agent/whisper` and `/agent/recall`
  never respond (90 s and 45 s budgets exhausted, no bytes).
- External probe: `BEGIN IMMEDIATE` on `index.db` returns `database is locked` on 10 consecutive
  attempts over 60 s; read-only connections succeed.
- `py-spy dump` shows the cycle above, with `acquired: True` on the auto_linker's `L_mem` frame
  and both jobs carrying an identical `t0` (247836.347…) — they started in the same millisecond.
- Log: `Auto-linker` and `Index updater` both start at 19:53:28 and neither ever logs completion;
  `Index updater` is then skipped every minute with `maximum number of running instances reached (1)`.

Dump preserved at `~/.local/share/ormah/logs/deadlock-stack-2026-08-10.txt`.

## Scope of the inversion

A scan of the package finds **11 decorated-`FileStore` calls made under an open transaction**,
spread across **5 transaction blocks**. Four blocks (9 of the calls) are already safe; one block
(2 calls) is the live defect:

| Transaction block | Calls under it | Status |
|---|---|---|
| `_migrate_fsrs` (memory_engine.py:279) | `load`, `save` | benign — single-threaded in `__init__` |
| `_migrate_identity_tiers` (memory_engine.py:380) | `load`, `save` | benign — single-threaded in `__init__` |
| `_migrate_identity_tiers` (memory_engine.py:416) | `load`, `save`, `load`, `save` | benign — single-threaded in `__init__` |
| `delete_node_guarded` (memory_engine.py:1256) | `soft_delete` | fixed by f7ac305 |
| **`incremental_update` (builder.py:118)** | **`list_paths`, `file_hash`** | **live inversion — this spec** |

`scheduler.py:157` registers `tracked(tracker, "index_updater", engine.builder.incremental_update)`
with no `@serialized_memory_job`. It is the only background job that does not take `L_mem` first.

This is present in `upstream/main` (0.14.8) unchanged — it is an upstream defect, not a Beta
regression. The `a8788aa` merge created the exposure by decorating the 8 `FileStore` methods.

## Why f7ac305's audit missed it

That commit audited two categories: the 8 background jobs (all carrying `@serialized_memory_job`)
and the 10 decorated `MemoryEngine` writers. `index_updater` is in neither — it is a job that calls
`IndexBuilder`, a third class outside the sweep. The commit message's `Still unaudited: nothing.`
is therefore incorrect, and the new commit message must say so.

## Design

Move both `FileStore` calls above the transaction, so no `L_mem` request happens under `L_db`:

```python
paths = self.file_store.list_paths()                       # L_mem, outside the txn
hashes = {p: self.file_store.file_hash(p) for p in paths}   # L_mem, outside the txn

with self.db.transaction():                                 # L_db alone
    for path in paths:
        file_hash = hashes[path]
        node = parse_node(path.read_text(encoding="utf-8"))
        ...
```

This mirrors `full_rebuild` (builder.py:33), which already hoists `list_paths()` out of its
transaction. The fix aligns `incremental_update` with the established pattern in its own file.

### Why not `@serialized_memory_job` on index_updater

It would unify the order on `L_mem -> L_db`, matching f7ac305's pattern. Rejected: `index_updater`
holds `L_db` for the whole 36 498-file loop, every 60 s. Making it hold `L_mem` for that same span
would block every `remember` and every whisper-log write for minutes at a time — trading a deadlock
for sustained write starvation. Hoisting removes the inversion without retaining any new lock.

### Incidental benefit

Today each file is read twice inside the transaction (`file_hash` does `read_bytes`, the parse does
`read_text`). After the change total I/O is unchanged, but half of it moves outside the transaction,
shortening the window during which writes are blocked. This helps the ~1 s whisper baseline; it does
not fix it.

### Behavioural note

`list_paths()` is sampled marginally earlier than today, so a file created in the gap between the
hoisted call and the transaction is picked up on the next run instead of this one. This is not a new
property: `BEGIN IMMEDIATE` never locked the filesystem, so files could already change mid-transaction,
and `full_rebuild` has always sampled outside. `index_updater` runs every 60 s, so the delay is bounded
by one cycle.

## Testing

TDD, red before green, following the two tests f7ac305 added
(`test_sweep_does_not_deadlock_against_a_concurrent_writer`).

The test drives the exact interleaving: one thread enters `incremental_update`'s transaction and
pauses (instrumented `list_paths`) while holding `L_db`; a second thread takes `L_mem` and reaches
for `L_db`. Both then need the other's lock. The worker must hang past a bounded `join` before the
fix and complete after it.

The test must fail for the right reason — a hang, not an error — so the red run has to be confirmed
by observing the timeout, not merely a non-zero exit.

## Out of scope

- The structural ~1 s whisper latency (moving the parse loop out of the transaction).
- The two coexisting installs (repo `.venv` 0.14.5 and uv tool 0.13.6, ~9 live `ormah mcp`
  processes). Ruled out as a cause: only the server PID holds `index.db` open.
- A systematic re-audit of every class that opens a transaction and touches `FileStore`.

## Delivery

Per FORK-WORKFLOW.md Recipe A: branch cut from `upstream/main` in a **worktree** (never a checkout
inside `Tools/ormah` — the running Beta serves this tree), pushed to `fork`. Then Recipe B merges it
into `local-main` so the Beta runs the fix.

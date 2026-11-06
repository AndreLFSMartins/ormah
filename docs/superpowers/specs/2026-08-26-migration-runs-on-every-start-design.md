# The FSRS migration re-evaluates on every start (#236, council round 4)

**Date:** 2026-08-26 · **Branch:** `fix/236-restore-fsrs-migration` · **Worktree:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-236`

Follow-up to `2026-08-25-restore-fsrs-migration-design.md`. That design is implemented and on the branch (commits `0aed37d`..`ec691a6`). This one addresses the two blocking findings the Dev Council raised against it (`RUN_ID=90c431e7-ec691a67-c251f19c`, Codex, `high` @ 0.98 and 0.97). Both were routed to `unverified_blocking` — no reproduction command — and André ruled to fix both.

## The two defects

**D1 — the per-node seed is permanently gated by a store-wide marker.** `_migrate_fsrs` returns early once `lifecycle_model_version` reaches `LIFECYCLE_MODEL_VERSION`. A pre-FSRS Markdown node that arrives afterwards — dropped into `nodes/` by an external tool and picked up by `IndexBuilder.incremental_update` — is never seeded and keeps `stability = 1.0` forever, so decay and forgetting treat a well-used memory as brand new. The early return predates this branch, but the branch is what advertises support for externally authored and mixed graphs, which is what makes the gap reachable in practice.

**D2 — the completeness guard compares cardinality, not membership.** `_graph_is_fully_indexed` tests `len(self.file_store.list_paths()) == SELECT COUNT(*) FROM nodes`. Equal counts do not establish that every file has a corresponding row: an indexed file replaced externally by a different node while the process is stopped leaves both sides at one. The guard is new in this branch — before it there was no guard at all — so this is a new guard weaker than it looks, not a regression.

## Design

### 1. The seed always runs; only the marker write is gated

`_migrate_fsrs` stops short-circuiting the seed. The early return moves to guard the version write alone:

```text
always:                                      _seed_stability_from_access_count()
if version == LIFECYCLE_MODEL_VERSION:       return          # nothing left to record
if not _graph_is_fully_indexed():            warn; return    # marker withheld
record lifecycle_model_version + fsrs_migrated
```

This is safe because the seed is already per-node and idempotent: its predicate is `last_review IS NULL AND stability = 1.0 AND access_count > 0`, so on a store with nothing to do it matches no rows, and re-running it over an already-seeded node is excluded by the same predicate. The cost on a migrated store is one SELECT per `_migrate_fsrs` call.

`_migrate_fsrs` is reached from `startup()` and from `MemoryEngine.rebuild_index`. A node that arrives while the server runs is therefore seeded at the next start, not at the moment it is indexed. That bound was chosen deliberately (see Rejected alternatives).

### 2. The guard compares membership

`_graph_is_fully_indexed` parses each path from `list_paths()`, collects `node.id`, and compares that set against `SELECT id FROM nodes`.

**A file that fails to parse returns `False` immediately, before any set comparison.** This is the subtlety the whole guard turns on, and it runs against the intuitive reading: an unparseable file contributes no id, so it would drop out of *both* sides and a naive set equality would report the graph complete — the exact opposite of what the guard exists to say, and it would turn the existing `test_no_version_is_recorded_while_a_file_is_missing_from_the_index` green for the wrong reason. Fail closed on both edges: unparseable file means incomplete; sets unequal in either direction means incomplete.

The guard now runs only while the recorded version is below `LIFECYCLE_MODEL_VERSION`, so the O(N) parse is paid once per store rather than on every start.

## Scope

- Modify: `src/ormah/engine/memory_engine.py` — `_migrate_fsrs`, `_graph_is_fully_indexed`.
- Modify: `tests/test_engine/test_lifecycle_model_version.py`.

Nothing else. In particular `src/ormah/index/builder.py` and `src/ormah/background/scheduler.py` are untouched.

## Testing

Three new tests, each seen failing first, plus one existing test that pins the design:

1. **D1** — a store already at version 2; a pre-FSRS node written to Markdown and indexed via `incremental_update`; `_migrate_fsrs()` seeds it to `10.0`. Today the early return leaves it at `1.0`.
2. **D2, the council's scenario** — equal counts, different membership: an indexed file replaced externally by a different node. `len == COUNT` still holds; the guard must report incomplete and the marker must be withheld.
3. **The other direction** — a row in `nodes` with no file on disk is also incomplete.
4. **Parse failure still withholds** — this is the existing `test_no_version_is_recorded_while_a_file_is_missing_from_the_index`. It is not rewritten; it is the regression guard for the fail-closed ordering above and must stay green.

Three existing tests must stay green, because they are what proves "always seed" is not destructive: `test_a_legacy_store_is_backfilled_without_reseeding`, `test_a_rebuilt_index_does_not_reseed_earned_stability`, `test_a_restore_onto_an_existing_index_keeps_earned_stability`. The per-node predicate already excludes their nodes. A red here means the design is wrong, not the test.

## Rejected alternatives

**Seed at ingestion time, under the memory lock.** Would close D1 with no latency: wrap `IndexBuilder.incremental_update` in an engine method decorated `@_serialized_memory_operation` that seeds when `added > 0`, and repoint its three call sites. Rejected because `incremental_update` is called directly on the builder from the background scheduler's `index_updater` job (`scheduler.py:108`) and two admin routes (`routes_admin.py:259,285`); routing it through the engine would make a periodic background job hold the memory lock, and the seed writes `file_store` from inside `db.transaction()` — the db-then-file inversion this branch just finished collapsing. The cost of the rejection is bounded and named: a node arriving at runtime keeps `stability = 1.0` until the next start.

**A durable per-node marker.** Would remove the whole class of problem. Rejected because `index.db` is derived state and `full_rebuild` wipes it, so any durable marker must live in the Markdown — which means rewriting every node file to introduce it.

**Deleting the completeness guard.** Once the seed always runs, recording the version over a partial graph no longer strands anything, so the guard is arguably dead code. Rejected because it would record durably that a store is migrated through v2 when it may not be, misleading any future non-idempotent v3 migration.

## Stated limits

- A pre-FSRS node arriving while the server runs is seeded at the next start, not immediately.
- `parse_node` maps an absent `stability` and an explicit `stability: 1.0` to the same value, so a deliberately authored `1.0` with a usage history is indistinguishable from an unseeded node and will be seeded. Carried unchanged from the previous design; the council raised it again as `medium` and it remains accepted.
- The membership check is still a snapshot: a file changed between the check and the marker write is a TOCTOU the guard cannot close. It narrows the window rather than eliminating it.

## Out of scope

- `rebuild_index` holding the memory lock across the whole embedding pass — real, this branch's regression, filed as **r-spade/ormah#264**.
- `_lifecycle_model_version()`'s 0/1/2 heuristics, backup manifest changes, the incremental-update race with a concurrent rebuild.

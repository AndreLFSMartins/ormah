# Restore onto an existing index re-evaluates the FSRS migration (#236)

Branch: `fix/236-restore-fsrs-migration`. Issue: #236.

## Problem

A restore onto an installation whose `index.db` still exists never re-runs
`_migrate_fsrs`: `IndexBuilder.full_rebuild` keeps `fsrs_migrated` and
`lifecycle_model_version` in `meta`, and `reload_restored_graph` /
`rebuild_index` never call the migration. Only `MemoryEngine.startup()` does,
and it returns early on version >= 2. Restored pre-FSRS nodes keep
`stability = 1.0` instead of `min(30, access_count * 2)`.

## Evidence that bounds the design

- FSRS (`stability`, `last_review`, `_migrate_fsrs`) is in the root commit
  `f6c6854`. `backup.py` (04-26) and `cloud/restore.py` (07-13) postdate it.
  Ormah has never written pre-FSRS Markdown; the scenario only arises from
  Markdown authored outside Ormah.
- Invariant since the root commit, for Ormah-authored stores only: every
  writer of `stability` / `access_count` (seed, legacy reinforce,
  `_record_confirmed_use`) also writes `last_review`; decay does not write
  `stability`. `reinforcement_due(None)` is True, so the first confirmed use
  already stamps `last_review`. Therefore, in a store Ormah wrote,
  `access_count > 0 => last_review IS NOT NULL`.
- That invariant does NOT extend to the external Markdown this migration
  exists to handle (council round 1, Codex F1). External Markdown may carry a
  real `stability` with no `last_review`, and a store-wide seed would
  overwrite it. It may also mix external and Ormah-authored nodes, which a
  store-wide guard resolves as "migrated" and skips entirely (Codex F2).
- Consequence: the seed decision must be per node, not per store. A node is
  eligible only when it carries no evidence of its own lifecycle state.

Rejected: recording the version in the backup manifest (solves a scenario
Ormah cannot produce, touches three modules); a frontmatter-based guard
(redundant with the per-node predicate below).

## Design

1. `IndexBuilder.full_rebuild` deletes `fsrs_migrated` and
   `lifecycle_model_version` from `meta`, next to `auto_link_watermark`, with
   the same rationale: derived state that a rebuild invalidates.
2. `_seed_stability_from_access_count` becomes per-node eligible. It selects
   and updates only nodes matching, in SQL:

       last_review IS NULL AND stability = 1.0 AND access_count > 0

   Any node carrying a `last_review`, a non-default `stability`, or no usage
   history is left untouched, in the DB and on disk. A node is seeded only
   when it carries no evidence of its own lifecycle state. Restricting the SQL
   also means no Markdown file is loaded or rewritten for a node that will not
   change.

   Limit of this predicate, stated rather than glossed (council round 2, Codex
   F1): `parse_node` maps an absent `stability` field and an explicit
   `stability: 1.0` to the same value, so the predicate cannot distinguish
   them. That ambiguity is not resolvable here, because the case it would have
   to reject — `stability` default, `access_count > 0`, no `last_review` — is
   exactly the case #236 requires the seed to accept. The predicate protects
   every value that differs from the default; a deliberately authored `1.0`
   with a usage history is indistinguishable from an unseeded node and will be
   seeded.
3. `_migrate_fsrs` runs the seed whenever the recorded version is below
   `LIFECYCLE_MODEL_VERSION`, not only at version 0. The per-node predicate,
   not the store-wide guard, is now what makes the seed safe, so a mixed
   restore seeds its pre-FSRS nodes while leaving its migrated ones alone.
   `_lifecycle_model_version` itself is unchanged: it still decides which
   version is recorded.
4. `MemoryEngine.rebuild_index` is decorated with
   `@_serialized_memory_operation` and calls `self._migrate_fsrs()` after
   `_reindex_all_embeddings()`. This covers `reload_restored_graph` (already
   serialized; the RLock re-enters) and the admin `/rebuild-index` route.
5. `_migrate_fsrs` records the version only when the graph is complete.
   `full_rebuild` skips files it cannot hash, parse, or index, logging each and
   returning a partial count. Recording version 2 over a partial graph strands
   a pre-FSRS node that only lands on a later `incremental_update`, because the
   early return then skips it forever (council round 2, Codex F2; round 3,
   Cursor F1). So `_migrate_fsrs` compares `len(self.file_store.list_paths())`
   with `SELECT COUNT(*) FROM nodes` and, when they differ, seeds the nodes
   that ARE indexed but writes no version — leaving the store to retry.

   The check lives inside `_migrate_fsrs`, not in the caller. An earlier draft
   exposed a `skipped_paths` counter on `IndexBuilder` and read it in
   `MemoryEngine.rebuild_index`; Cursor showed that guards nothing, because the
   two callers this issue is actually about never read it: `startup()`
   (`memory_engine.py:121-161`) calls `full_rebuild()` and then `_migrate_fsrs()`
   directly, and `BackupService.rebuild_index` (`backup.py:460-466`) builds a
   throwaway `IndexBuilder` and discards it. The "next engine start retries"
   recovery was itself the bypass. `list_paths()` globs only `nodes/*.md`, and
   soft-deleted files live in `deleted/`, so neither side of the comparison
   counts tombstones.
6. Lock-order invariant in `_record_confirmed_use`'s docstring is updated:
   file_store inside `db.transaction()` is allowed from `startup()` **or from
   a `_serialized_memory_operation`**, because the memory lock is then held
   before the db lock (memory -> db, the same order as reinforcement).
7. CLI / cloud paths without an engine: `BackupService.rebuild_index` ->
   `full_rebuild` clears the keys; the next `MemoryEngine.startup()` runs
   `_migrate_fsrs`, which applies both the per-node predicate and the
   completeness check. No code change there; covered by test.
8. `test_a_rebuilt_index_does_not_reseed_earned_stability`'s scope note is
   updated: the same-device path is now covered by the tests below.

### Interrupted seed (council round 1, Codex F3)

The seed writes Markdown inside `db.transaction()`, so a failed
`file_store.save` rolls back the DB but leaves earlier files rewritten. Two
things contain this. First, the version is written in a separate transaction
*after* the seed returns (`memory_engine.py:177-188`), so a raising seed never
records a version — Codex's "version 2 recorded over inconsistent state" does
not hold. Second, the per-node predicate makes the retry correct: nodes
already seeded carry `last_review` and a non-default `stability`, so they no
longer qualify, while nodes not yet reached still do. The migration is
resumable without new bookkeeping.

## Tests (must fail before the fix)

Every test that claims to exercise a restore must persist its fixture to
Markdown and go through `reload_restored_graph()` (council round 3, Cursor
F3). A `stability` written only into SQLite does not survive `full_rebuild`,
which reindexes from disk, so a DB-only fixture proves nothing about restore.

- Unit (issue's case): migrated engine, Markdown rewritten to pre-FSRS
  (`last_review` absent, `access_count = 5`, `stability = 1.0`),
  `reload_restored_graph()` -> `stability == 10.0`, version back to `2`.
- Unit (inverse, `last_review` present): v2 store with earned stability in the
  frontmatter, `reload_restored_graph()` -> stability preserved, version `2`.
- Unit (Codex F1): Markdown carrying `stability: 42.0`, `access_count: 5` and
  NO `last_review`, `reload_restored_graph()` -> stability stays `42.0`.
- Unit (Codex F2, mixed store): one reviewed node with earned stability plus
  one unreviewed node with `access_count = 5` and default stability, both on
  disk; `reload_restored_graph()` -> the first keeps its value, the second
  becomes `10.0`.
- Unit (Codex F3, interrupted seed): `file_store.save` raises on the second
  node; the first node's Markdown keeps its seeded value, no version is
  recorded, and a second `reload_restored_graph()` seeds the remaining node.
- Unit (no usage history): `access_count = 0` -> neither `stability` nor
  `last_review` is touched.
- Builder: `full_rebuild` removes both lifecycle keys.
- End-to-end (Cursor F1/F2): a memory dir holding one valid pre-FSRS node and
  one unparseable `broken.md`. `BackupService.restore` then `MemoryEngine.startup()`
  -> no `lifecycle_model_version` recorded, indexed node seeded. Repair
  `broken.md` into a second pre-FSRS node, rebuild -> version `2` and both
  nodes seeded.
- End-to-end (happy path): `BackupService.restore` of a pre-FSRS backup on a
  memory dir with an existing migrated `index.db`, then a fresh
  `MemoryEngine` -> `stability == 10.0`.

## Out of scope

Backup manifest changes, changes to `_lifecycle_model_version` itself, the
incremental-update race with a concurrent rebuild.

## Known behaviour change

The seed no longer stamps `last_review = last_accessed` on nodes it does not
change. Under the old store-wide seed, every node in the store — including
those with `access_count = 0`, whose stability was set to the default it
already had — got a `last_review`. The per-node predicate skips them, so the
durable Markdown is no longer rewritten for nodes whose values do not move.

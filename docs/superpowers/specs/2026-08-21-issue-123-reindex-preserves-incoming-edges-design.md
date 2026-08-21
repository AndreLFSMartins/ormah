# Design — reindexing a node must not destroy its incoming edges (#123)

**Date:** 2026-08-21
**Status:** approved, ready for planning
**Scope:** `src/ormah/index/builder.py` (slice 1) + `src/ormah/engine/memory_engine.py` (slice 3)
+ a repair path for already-lost edges (slice 2, separate PR).
**Upstream target:** clean island from `upstream/main` (FORK-WORKFLOW.md Recipe A), branch
`fix/123-reindex-preserves-incoming-edges`. Slices 1 and 3 ship in that one PR; slice 2 gets its own.
**Issue:** r-spade/ormah#123, OPEN since 2026-07-14 (verified via `gh issue view 123`).

## The invariant

**A row in `edges` is owned by the markdown file of its `source` node. Reindexing a node may only
rewrite the edges that node declares.**

The connection `A -> B` lives in A's markdown. Reindexing B has no access to A's file and therefore
no way to reconstruct that row — so it must not delete it. Today it deletes it three separate ways.

## The three destruction paths

Every reindex (`index_single`, and the update branch of `incremental_update`) runs
`_remove_node` then `_index_file`. Incoming edges die three times over:

| # | Location | Statement | Effect |
|---|---|---|---|
| 1 | `builder.py:381` | `DELETE FROM edges WHERE source_id = ? OR target_id = ?` | explicit, bidirectional |
| 2 | `builder.py:384` | `DELETE FROM nodes WHERE id = ?` | `ON DELETE CASCADE` wipes incoming |
| 3 | `builder.py:240` | `INSERT OR REPLACE INTO nodes` | REPLACE is DELETE+INSERT; cascade fires again |

`_index_file_edges` (`builder.py:338`) then reinserts only the connections declared in *this* node's
markdown — unidirectional. The asymmetry is the defect.

Path 3 is the trap: it fires even with paths 1 and 2 fully repaired, because SQLite implements
`INSERT OR REPLACE` as a delete followed by an insert, and foreign-key `ON DELETE CASCADE` actions
are applied to that internal delete. A fix that only rewrites the explicit `DELETE FROM edges` looks
correct and changes nothing.

### Evidence (measured, not recalled)

`edges` DDL from the live index, and `PRAGMA foreign_keys=ON` at `db.py:38`:

```sql
CREATE TABLE edges (
    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    ...
    PRIMARY KEY (source_id, target_id, edge_type)
);
```

Behaviour of each write against an existing incoming edge, sqlite 3.53.1:

| Operation on `nodes` | Incoming edges |
|---|---|
| `INSERT OR REPLACE` | 1 -> 0 (cascade fires) |
| `INSERT ... ON CONFLICT(id) DO UPDATE` | 1 -> 1 (survives) |
| `DELETE FROM nodes` | 1 -> 0 (cascade fires) |

The true upsert is the only node write that leaves incoming edges standing.

### Why the loss is permanent

`_invalidate_checked_pairs` (`builder.py:320`) clears the cached pair verdicts only when the
persisted **content fingerprint** changes (title/content/type/space). `_remove_node` runs on every
**file hash** change, which includes `touch_updated()` — a write that only touches the `updated`
field. So the edge dies while the verdict survives, and the maintenance jobs skip the pair forever.

The pair gate is shared by three jobs, not one:

| Job | Gates on `auto_link_checked`? | Location |
|---|---|---|
| `auto_linker` | yes | `auto_linker.py:258` |
| `conflict_detector` | yes, unconditional | `conflict_detector.py:241-245` |
| `duplicate_merger` | yes, behind `respect_checked` | `duplicate_merger.py:266-271` |
| `consolidator` | no — keys on `consolidation_checked` by signature, and reads `edges` only by `source_id` | `consolidator.py:166` |

**This audit narrows the work rather than widening it: none of the three needs a code change.** Once
edges stop being destroyed, nothing needs to recreate them. Verdict staleness after a `touch_updated()`
remains, but that is correct behaviour — the content did not change.

The irony that makes the bug self-feeding: `auto_linker._apply_edge` calls `touch_updated()` before
saving. Creating a new link on A triggers a reindex of A and destroys A's *incoming* edges.

## Slice 1 — the core fix

`_remove_node` currently fuses two different operations. Split them:

- **`_clear_derived(node_id)`** — the *reindex* path. Clears `node_tags`, `nodes_fts`, and
  `edges WHERE source_id = ?` only. Does not touch the `nodes` row, so no cascade.
- **`_remove_node(node_id)`** — the *genuine removal* path (`pending_removal`, file gone from disk).
  Unchanged: full delete including the `nodes` row. The cascade here is correct and wanted — an
  edge pointing at a node that no longer exists is a foreign-key violation.
- **`_index_file_nodes_only`** — `INSERT OR REPLACE INTO nodes` becomes
  `INSERT ... ON CONFLICT(id) DO UPDATE SET <col> = excluded.<col>` for the 21 written columns.

`keep_vectors` disappears as a parameter: the vector is deleted only on the genuine-removal path,
which is what the flag existed to express.

### Why the upsert is a safe drop-in

`nodes` has 22 columns: the 21 written explicitly by the `INSERT`, plus `seq`. `seq` is already
assigned by a separate `UPDATE` immediately after the insert (the `node_seq_next` monotonic
allocator, council v2 crit#1 / #126). There is no column outside that set, so no column silently
changes meaning between `REPLACE` (resets omitted columns to their default) and upsert (preserves
them). The `#126` fingerprint comparison uses `prior`, read before the write, and is untouched.

### Known behavioural consequence — document it, do not "fix" it

`_index_file_edges` skips inserting `A -> B` when the reverse `B -> A` already exists with the same
edge type (`builder.py:352`, the "avoid bidirectional duplicates" canonicalisation).

- **Today:** reindexing A deletes both directions, so A's row is always reinserted. The canonical
  direction is whichever node was reindexed *last* — order-dependent and unstable.
- **After the fix:** `B -> A` survives, so A's connection is skipped. The **incumbent** wins, stably.

Both choices are arbitrary; the fix makes the outcome deterministic instead of a function of reindex
order. When the two markdown files disagree on `weight`/`reason`, the incumbent's metadata is the one
retained. This needs its own test so a reviewer does not read it as a regression.

## Slice 2 — repair the edges already lost (separate PR)

The core fix stops the bleeding; it recovers nothing. Today the only recovery is
`POST /admin/rebuild`, which re-embeds and rebuilds FTS for the whole store (221.7 s measured on
2026-08-21). A connections-only repair re-reads each markdown's `connections` and inserts the missing
`edges` rows, touching no nodes, vectors, or FTS.

**Blocking sub-task, and the reason this is a separate PR: the drift measurement is not working.**
The ad-hoc script written during design returned `declared=0` because `parse_node` raises
`KeyError: 'id'` on at least one `.md` under the memory directory. Until that measurement is fixed,
this slice has no success criterion — "how many edges did we recover" is unanswerable. Fix the
measurement first; the number it produces is the acceptance test.

Do not carry any previously reported drift figure into this slice as a measurement. Re-derive it.

## Slice 3 — remove the merge workaround (same PR as slice 1)

`memory_engine.py:2009-2021` restores incoming edges by hand, commented *"Restore incoming edges for
the kept node that were wiped by index_single"*. Slice 1 makes it dead code.

Removing it is the second, independent proof that the fix landed: the merge tests must stay green
**without** the workaround. If they fail, slice 1 is incomplete.

**It belongs in the same PR as slice 1, not a separate one.** A branch cut from `upstream/main` that
removes the workaround without the builder fix is a real regression — the workaround is still
load-bearing there. Sequencing it as a follow-up PR would leave it blocked until slice 1 lands, which
in this fork's queue is not a bounded wait.

## Testing (TDD — red first)

`tests/test_proposal_claims_investigation.py::test_issue_123_reindex_drops_incoming_edges` asserts
`incoming() == 0`: a green test that enshrines the bug. **It is not a PR deliverable** — that file is
untracked and listed in `.git/info/exclude:56` ("One-off investigation tests from the ADR-0004 work;
never part of the suite"), together with three siblings. Invert it locally as the reproduction, but
the regression test must be born in a tracked file.

New tests go in `tests/test_index/test_builder.py`, mirroring `test_reindex_preserves_the_edge_reason`
(`:190`), which already covers the outgoing direction and supplies the fixture idiom — note its
comment that `index_single` takes a `Path` via `file_store._path_for(node)`, never an id.

| Test | Worked example | Does it catch the target bug? |
|---|---|---|
| `test_reindex_preserves_incoming_edges` | A declares `A -> B` with `reason="because X"`; reindex **B**; assert the row survives with its `reason` and `weight` | Yes — today it dies via all three paths |
| `test_touch_updated_does_not_drop_incoming_edges` | Same setup; call `touch_updated()` on B and save, then reindex | Yes — this is the real trigger: file hash changes, fingerprint does not, so the verdict survives and no job ever recreates the edge |
| `test_removing_a_node_still_drops_its_incoming_edges` | Delete B's file, run `incremental_update`; assert `A -> B` is gone | Catches **over-correction**: applying the reindex path to genuine removal would leave orphan rows and violate the FK |
| `test_reindex_keeps_the_incumbent_canonical_direction` | A and B both declare the connection; reindex A; assert `B -> A` still holds the metadata and no duplicate row appeared | Pins the consequence above so it cannot silently flip back |

Test 3 is the one that keeps the fix honest: tests 1, 2 and 4 all pass under a naive "never delete
incoming edges anywhere" change, which would be wrong.

## Verification

- Island venv, per FORK-WORKFLOW Recipe A. All three gates before trusting any number: strip
  `VIRTUAL_ENV`/`PYTHONPATH`, prove the import path contains the island directory, run with a clean
  `HOME`, redirect and capture `$?` rather than piping to `tail`.
- `git log --oneline upstream/main..HEAD` must show only this work.
- Baseline on `local-main` at `1034bfd`, re-derived 2026-08-21: **2647 passed, 1 failed** in 201 s.
  The single failure is
  `test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports`,
  in one of the four locally-excluded investigation files. The tracked suite is green. The island
  will not contain those files at all, so its baseline is the tracked suite only.
- `ruff check src/ tests/` clean.

## Out of scope

- Changing the `auto_link_checked` / `duplicate_checked` / `conflict_checked` invalidation rule. The
  audit above shows the three jobs share the gate, but the core fix removes the harm.
- `failure_reason` (`background/job_tracker.py:110`) not treating `{"skipped": ...}` as a
  non-execution, and partial sleep-cycle results returning without an `error` key. Both are real,
  both are inherited, neither is #123.
- The `consolidator`, which does not share the pair gate.
- Restarting the running daemon (pid 13585, code of 2026-08-20). That is André's call and unrelated
  to landing this fix.

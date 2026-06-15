# Bounded Forgetting (#28) — Design

**Issue:** #28 — `feat(background): bounded forgetting — delete dead-weight archival nodes`
**Branch:** off `perf/auto-linker-incremental` (#26 not yet merged to main)
**Date:** 2026-06-15

## Problem

Decay is a one-way ratchet. `decay_manager` demotes stale `working` nodes to `archival`
(`src/ormah/background/decay_manager.py`) but nothing ever removes them. `archival` only
grows. On André's real store (8.355 nodes, 80% archival) that graveyard:

- counts toward total node count (graph UI struggles),
- is scanned by every background job (auto-linker is O(n²) over *all* nodes),
- still surfaces in recall as noise (only down-ranked via `tier_boost_archival = -0.1`).

Decay reduces *priority*, not *cost* or *noise*. **Deletion is the only lever that shrinks
the store.** Shrinking `n` is also a free multiplier for #26 (auto-linker) and #25 (vector
search).

## Design constraint

Deletion is irreversible and memory lives on trust. A false negative — deleting something
that later mattered — is unrecoverable. Therefore:

> Deletion never depends on a single signal. It acts only on the `archival` tail, requires
> the conjunction of several independent signals, and keeps a reversibility window before
> anything leaves disk. Every decision is explainable per node.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Full issue: §1 gates + §2 soft→hard-purge + §3 cap backstop | André opted for the complete lifecycle in one delivery. |
| Default state | Opt-in, **OFF** (`deletion_enabled = False`) | Irreversible action in a trust-critical system → fail-closed default; user arms it explicitly. |
| Enablement surface | **Env / `.env` only, no UI toggle** | The web UI is too slow to open at André's node count. All config is pydantic-settings (`ORMAH_` prefix), read from `~/.config/ormah/.env` and `./.env`. |
| Purge timing | `deleted_at` stamped in the moved file's **frontmatter** | Self-contained: survives backup/restore and mtime/TCC-copy resets on this machine. |
| "archived ≥ N days" signal | Dedicated **`nodes.archived_at`** column | Only robust way to express graveyard age without coupling to unrelated `update_node` writes. |

## Architecture: one new background job

New module `src/ormah/background/forgetting_manager.py` → `run_forgetting(engine)`,
registered in `src/ormah/background/scheduler.py` with its own interval. Each run has two
phases, both guarded by the master switch `deletion_enabled` (when `False`, the job returns
immediately — a no-op):

### Phase A — gates → soft-delete (+ cap backstop)

1. Select `archival` candidates (SQL prefilter on cheap columns).
2. Apply the conjunction gates (§1). For each eligible node, call `engine.delete_node(id)`,
   which already does: index removal, `audit_log` (`operation='delete'`), `auto_link_checked`
   cleanup, and `file_store.soft_delete` (move to `deleted/`).
3. If `archival_soft_cap > 0` and the surviving archival count still exceeds it, evict
   worst-first by forget-score (§3) down to the cap, **respecting every protection in §1**.

### Phase B — hard-purge

1. `file_store.list_deleted()` → iterate files in `deleted/`.
2. Parse `deleted_at` from each file's frontmatter.
3. For files older than `deletion_retention_days`, `file_store.purge(node_id)` (remove from
   disk) and write `audit_log` (`operation='purge'`).

Reusing `engine.delete_node` for soft-delete keeps a single deletion path (index + audit +
auto-link cleanup all handled), so the new job stays small.

## Schema change (one migration)

Add `nodes.archived_at TEXT` (nullable):

- Set when a node is demoted to `archival` — in the `decay_manager` demotion path (and any
  other path that writes `tier = archival`).
- Migration in `Database._migrate` adds the column and backfills existing `archival` rows
  with their current `updated` value (best available proxy for legacy data).

## file_store changes

- `soft_delete(node_id)` — before/while moving to `deleted/`, stamp `deleted_at: <iso>` into
  the file's frontmatter. Centralized here, so manual `delete_node` also gets a timed
  reversibility window.
- `list_deleted()` — new: enumerate files currently in `deleted/`.
- `purge(node_id)` — new: hard-remove a file from `deleted/`.

## §1 Eligibility gates (delete only when ALL hold)

Over `tier == archival` candidates; cheap predicates in SQL, FSRS `R` computed in Python
(same formula as `decay_manager`: `R = exp(-days_since_anchor / stability)`).

1. `tier == archival` — never `working`/`core`.
2. `archived_at <= now − deletion_min_archival_days` **AND**
   `last_accessed <= now − deletion_min_archival_days` — sustained staleness, not a point
   reading.
3. `R < deletion_retrievability_floor` — retrievability below a hard floor (deeper than the
   decay demotion threshold).
4. `importance < decay_importance_threshold` — high importance never deletes.
5. `NOT EXISTS (SELECT 1 FROM affinity WHERE node_id = ? AND signal > 0)` — never positively
   useful (any `submit_feedback(+1)` or positive affinity ⇒ protected forever). Ties into #21.
6. `degree <= deletion_max_degree` **AND** no edge with `weight >= deletion_strong_edge_weight`
   — leaves are safe; never delete a bridge/hub.
7. Not the user/self node. (No "pin" concept exists in the schema today; protection is the
   self node. If a pin feature is added later, it must be respected here.)

Each gate alone produces false positives; the conjunction only catches genuine dead weight:
archival, unimportant, unused, never useful, weakly connected, old.

## §3 Cap backstop (forget-score)

When `archival_soft_cap > 0` and exceeded, evict worst-first by a composite forget-score:

```
score = (1 − R) · (1 − importance) · age_days · 1/(1 + degree) · no_positive_feedback
```

where `age_days = now − archived_at` and `no_positive_feedback ∈ {0, 1}` (a node with
positive feedback scores 0 and is never evicted). Sort descending, evict down to the cap,
skipping every node protected under §1.
If only protected nodes remain, the store stays above the cap — better to exceed the cap
than delete a valuable memory.

## Config (new fields in `src/ormah/config.py`, `ORMAH_` env prefix)

| Field | Default | Env var |
|---|---|---|
| `deletion_enabled` | `False` | `ORMAH_DELETION_ENABLED` |
| `forgetting_interval_hours` | `24` | `ORMAH_FORGETTING_INTERVAL_HOURS` |
| `deletion_min_archival_days` | `90` | `ORMAH_DELETION_MIN_ARCHIVAL_DAYS` |
| `deletion_retrievability_floor` | `0.05` | `ORMAH_DELETION_RETRIEVABILITY_FLOOR` |
| `deletion_max_degree` | `2` | `ORMAH_DELETION_MAX_DEGREE` |
| `deletion_strong_edge_weight` | `0.7` | `ORMAH_DELETION_STRONG_EDGE_WEIGHT` |
| `deletion_retention_days` | `30` | `ORMAH_DELETION_RETENTION_DAYS` |
| `archival_soft_cap` | `0` (off) | `ORMAH_ARCHIVAL_SOFT_CAP` |

Reuses existing `decay_importance_threshold` (0.5) for gate #4. Validators mirror the
existing decay/threshold validators (positive intervals, `0..1` floors).

## Operation

Enablement and tuning are env-driven, no UI involvement. To activate on André's machine:
add `ORMAH_DELETION_ENABLED=true` (and any tuning overrides) to `~/.config/ormah/.env`, then
restart the server. The slow web UI is never on the critical path.

## Testing (TDD)

Unit tests (mock external boundaries, real SQLite index):

- **Per gate, positive + negative:** stale-enough vs too-recent (`archived_at`,
  `last_accessed`), `R` below vs above floor, importance below vs above threshold, positive
  affinity present (protected) vs absent, degree/strong-edge below vs above limits, self node
  skipped.
- **Conjunction:** a node failing exactly one gate is not deleted; a node passing all is
  soft-deleted.
- **Master switch:** `deletion_enabled = False` ⇒ zero deletions (no-op), even with eligible
  nodes.
- **`soft_delete` stamps `deleted_at`** in frontmatter; file lands in `deleted/`.
- **Phase B purge:** files past `deletion_retention_days` are removed; files inside the window
  survive; `audit_log` records `operation='purge'`.
- **Cap backstop:** with `archival_soft_cap` set, worst-first eviction down to the cap;
  protected/feedback-positive/hub nodes never evicted even if it leaves the count above cap.
- **`archived_at`:** set on demotion in `decay_manager`; migration backfills existing
  archival rows from `updated`.
- **Idempotence:** a second run with no newly-eligible nodes deletes nothing.

## Out of scope

- UI changes (the issue's #22 active-graph-first is separate).
- Restore-from-`deleted/` UX (the reversibility window exists; a restore command is not part
  of this slice).
- #25 ANN / vector-search work (deferred per the perf roadmap).

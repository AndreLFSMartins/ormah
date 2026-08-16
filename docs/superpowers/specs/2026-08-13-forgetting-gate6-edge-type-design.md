# Design — forgetting gate #6 must ignore non-value-bearing edges

**Date:** 2026-08-13
**Issue:** [AndreLFSMartins/ormah#1](https://github.com/AndreLFSMartins/ormah/issues/1)
**Target branch:** `feat/bounded-forgetting` (head of the open upstream PR
[r-spade/ormah#31](https://github.com/r-spade/ormah/pull/31), base `main`)
**Status:** approved 2026-08-13, ready for planning

---

## Problem

`_evaluate_protection`'s gate #6 ("hub / strong edge") declares an archival node permanently
undeletable when either arm fires
([`forgetting_manager.py:118-121`](../../../src/ormah/background/forgetting_manager.py)):

```python
degree, max_weight = _connectivity(engine, row["id"])
if degree > s.deletion_max_degree or max_weight >= s.deletion_strong_edge_weight:
    return True, degree                           # gate #6: hub / strong edge
```

Both arms come from `_connectivity`, which counts **every** edge regardless of `edge_type`
(`forgetting_manager.py:159-165`). A `contradicts` edge therefore proves a node valuable exactly
as a `supports` edge does. That is backwards for a job whose entire purpose is pruning dead
weight: a contested or superseded memory earns the same "important, keep it" verdict as a
genuinely well-connected one.

The original gate design
(`docs/superpowers/plans/2026-06-15-bounded-forgetting/05-forgetting-gates.md`) never discusses
`edge_type` for gate #6. This is a gap the spec did not cover, not a considered-and-rejected
alternative.

### Measured blast radius — re-measured 2026-08-13 after council review

> **Correction (council round 1, 2026-08-13).** The first version of this section measured
> **total** degree, which proves nothing about the **filtered** degree the fix actually gates on
> — Cursor and Codex flagged this independently. It also claimed the 36.7k store "no longer
> exists"; it does, at `~/.local/share/ormah_old/backups/pre-cleanup-2026-08-11/index.db`. Both
> claims are replaced below by a measurement that mirrors the implemented gate exactly
> (`docs/superpowers/specs/gate6_blast.py`, read-only).

The issue reports 1,709 strong `contradicts` edges shielding 2,610 archival nodes, measured on a
36.7k-node store. Re-measured with SQL mirroring the implemented gate
(`degree_value > deletion_max_degree OR max_w_value >= STRONG`) over the nodes that actually
reach gate #6 (archival, `importance < 0.5`, no positive affinity), at this deployment's live
`ORMAH_DELETION_STRONG_EDGE_WEIGHT=0.61` — **not** the 0.7 code default:

| Store | gate #6 candidates | touch a `contradicts` edge | **lose gate #6 protection** |
|---|---|---|---|
| live (344 nodes / 175 archival) | 110 | 6 | **0** |
| archived 36.7k (kept for scale) | 35,056 | 2,776 | **86** — all via the `max_weight` arm |
| archived 36.7k, at the 0.7 default | 35,056 | 2,776 | 169 — 152 `max_weight`, **17** `degree` only |

Three conclusions follow, and all three shape this design:

1. The bug is real and worth fixing (the semantics are wrong regardless of today's counts), but
   on the live store it is a **preventive correction landed before PR #31 merges**, not
   remediation of live damage. `deletion_enabled=false` there in any case. No claim of rescued
   nodes belongs in the commit message.
2. **Both arms need the filter, but not for the reason first given.** The original argument —
   "all 13 archival nodes touching a strong `contradicts` edge have `degree >= 4`, so filtering
   only `max_weight` would be inert" — is an artifact of a 284-node store. At scale the opposite
   holds: the `max_weight` arm accounts for 86/86 of the changes at 0.61 and 152/169 at 0.7. The
   `degree` arm still earns its filter (17 real cases at 0.7), just not as *the* dominant one.
3. The blast radius is store- and threshold-dependent, so it must be re-measured immediately
   before publishing rather than quoted from here.

---

## Design

### 1. One definition of value-bearing connectivity, applied to both arms **of the gate only**

```python
# Edge types that are not evidence of value: a contested memory is not a valuable one.
_NON_PROTECTIVE_EDGE_TYPES = ("contradicts",)


def _connectivity(engine, node_id: str) -> tuple[int, int, float]:
    """Raw degree, plus degree and max weight over *value-bearing* edges only."""
    placeholders = ",".join("?" * len(_NON_PROTECTIVE_EDGE_TYPES))
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree_all, "
        f"COALESCE(SUM(CASE WHEN edge_type NOT IN ({placeholders}) THEN 1 ELSE 0 END), 0) "
        "AS degree_value, "
        f"COALESCE(MAX(CASE WHEN edge_type NOT IN ({placeholders}) THEN weight END), 0) "
        "AS max_w_value "
        "FROM edges WHERE source_id = ? OR target_id = ?",
        (*_NON_PROTECTIVE_EDGE_TYPES, *_NON_PROTECTIVE_EDGE_TYPES, node_id, node_id),
    ).fetchone()
    return row["degree_all"], row["degree_value"], row["max_w_value"]
```

`_evaluate_protection` gates on `degree_value` / `max_w_value` and keeps returning `degree_all`,
so `_forget_score` sees exactly what it saw before (see §3).

Three deliberate differences from the patch sketched in the issue:

- **Both gate arms are filtered, not just `MAX(weight)`.** `degree_value` and `max_w_value` share
  one notion of "an edge that counts as value". Splitting them would leave the degree arm as an
  unexplained exception.
- **The scoring path is *not* filtered.** Conditional aggregation, rather than a row-level
  `WHERE` filter, is what makes both answers available from one query (see §3).
- **A named module constant, not a literal in the SQL.** The reason for the exclusion lives in
  one place, and adding a second type later is a one-line change with no SQL surgery.

`edges.edge_type` is `TEXT NOT NULL` (schema verified; 0 NULL rows in the live store), so
`NOT IN (...)` carries no three-valued-logic trap. Moving the filter into `CASE WHEN` also
removes the operator-precedence hazard of the row-level version, where the parentheses around
`source_id = ? OR target_id = ?` were load-bearing. `COALESCE` on both `SUM` and `MAX` is
required: over zero matching rows an aggregate returns `NULL` while `COUNT(*)` returns 0.

### 2. `evolved_from` stays protective — out of scope, on purpose

`evolved_from` is the other candidate for exclusion: a superseded node arguably should not earn
immunity either. It is deliberately left alone. The edge is directional and `r-spade/ormah#194`
documents that the maintenance agent picks its direction without creation dates. `_connectivity`
matches `source_id OR target_id`, so excluding `evolved_from` would strip protection symmetrically
— from the surviving node as much as the superseded one. Widening the fix on an unreliable
signal trades one wrong verdict for another.

`contradicts` has no such problem: its semantics are symmetric. Both endpoints of a contradiction
are contested; neither is evidence of value.

### 3. Rejected ripple — the cap backstop must NOT reorder

> **Reversed by council round 1 (Codex high #1, 2026-08-13).** This section previously accepted
> the ripple as intended. The peer's counter-argument was checked against the code and holds.

`_evaluate_protection` returns a degree that flows straight into the cap backstop's forget-score
(`forgetting_manager.py:188` → `:212-221`):

```python
return (1.0 - r) * (1.0 - importance) * age_days * (1.0 / (1 + degree))
```

Had the filtered degree been passed here, a node whose edges are mostly `contradicts` would get a
lower `degree`, hence a **higher forget-score**, hence *earlier* eviction on cap overflow — not
merely losing immunity, but being actively prioritized for deletion.

That is the wrong reading of what a `contradicts` edge means in this codebase, verified at the
source:

- `src/ormah/background/auto_linker.py:83` — `contradicts` is emitted only for claims that are
  "genuinely incompatible … BOTH believed to be true RIGHT NOW". Temporal succession is
  explicitly *not* a contradiction; that is `evolved_from`.
- `src/ormah/engine/traversal.py:124-126` — recall renders those neighbors under
  `--- Conflicting context ---`. The edge is a feature of retrieval, not a tombstone marker.
- `src/ormah/background/conflict_detector.py:397` — every detected conflict is written at weight
  **0.9**, which is what makes contested nodes permanently immune under the unfixed gate.

So the bug is the *immunity* (a hardcoded 0.9 confidence being read as evidence of value), not
the node's presence in the graveyard. Removing the immunity is in scope; re-ranking contested
memories as dead weight is not — evicting one endpoint of a live conflict silently converts an
unresolved disagreement into one unchallenged claim.

The two callers therefore ask different questions and get different answers: the gate asks "is
this a hub worth keeping?" (filtered), the score asks "how dead is this?" (raw). Doing this from
one query costs nothing; `test_cap_ranking_ignores_contradictions` locks the boundary.

The remedy Codex preferred — an explicit `resolved`/`superseded` state, deleting only the
resolved loser — is a larger design and stays out of scope for this fix.

---

## Testing

The reproducing test the issue cites lives in `tests/test_conflict_claims_investigation.py`,
which is listed in `.git/info/exclude` — it is **not versioned**. There is no assertion to
invert. All five tests below are new, in the committed
[`tests/test_background/test_forgetting_manager.py`](../../../tests/test_background/test_forgetting_manager.py).

| # | Test | Expected RED (before fix) | Arm covered |
|---|---|---|---|
| 1 | `test_contradicts_edge_does_not_protect` | fails — node survives | `max_weight`: one `contradicts` edge at `weight=0.9` must **not** save the node |
| 2 | `test_supports_edge_still_protects` | passes before and after | non-regression on the legitimate path |
| 3 | `test_contradicts_edges_do_not_count_toward_degree` | fails — node survives | `degree`: three `contradicts` edges at `weight=0.1` (`degree=3 > deletion_max_degree=2`) must **not** save the node |
| 4 | `test_mixed_edges_only_value_bearing_degree_protects` | fails — node survives | `degree` on a mixed graph: 2 `related_to` + 3 `contradicts` ⇒ raw 5, value-bearing 2 |
| 5 | `test_cap_ranking_ignores_contradictions` | passes before and after | guard that the filter stays **out** of `_forget_score` (§3) |

Test 4 was added on council review (Cursor medium #1) and is the one that proves the `degree`
filter is not inert: 17 archival nodes in the 36.7k store were held by that arm alone at
threshold 0.7. Test 5 is the inverse of what an earlier draft asserted — see §3.

Existing coverage is unaffected: `test_strong_edge_protects_both_nodes:96` and
`test_cap_protects_strong_edge_hub:223` both build their edges with `EdgeType.related_to`, which
remains protective.

**Gates:** `python -m pytest tests/test_background/test_forgetting_manager.py -v` green, and
`ruff check src/ tests/` clean.

---

## Delivery

`forgetting_manager.py` does not exist on `upstream/main`, so `FORK-WORKFLOW.md` Recipe A
("cut the branch from `upstream/main`") cannot apply. The file lives only on
`feat/bounded-forgetting` (= `fork/feat/bounded-forgetting` @ `7130d39`) and on `local-main`.
The fix lands on the PR branch, before #31 is reviewed:

1. `git worktree add ../ormah-wt-gate6 feat/bounded-forgetting` — the **local** branch (verified
   identical to `fork/feat/bounded-forgetting` @ `7130d39`, and checked out in no other
   worktree), so commits land on the branch instead of a detached HEAD. A worktree, never a
   `checkout` inside `Tools/ormah`: this working tree is what the running Beta serves
   (Golden rule 1).
2. TDD in the worktree — tests 1, 3 and 4 RED first (tests 2 and 5 are green throughout by
   design), then the `_connectivity` change turns them green.
3. Run both gates and cite their output.
4. Commit on `feat/bounded-forgetting`, `git push fork feat/bounded-forgetting`. PR #31 picks the
   commit up on its own.
5. Re-run `gate6_blast.py` against the live store — the counts are store- and
   threshold-dependent, so they must come from the moment of publishing, not from this document.
6. Back in `Tools/ormah`, which is already on `local-main`: `git merge feat/bounded-forgetting`
   (Recipe B) so the Beta runs it. No branch switch is involved.
7. Close `AndreLFSMartins/ormah#1`, citing the commit and the blast radius from step 5.

### Explicitly not in this change

- **Back-porting `f7ac305`** (`@serialized_memory_job` on `run_forgetting`) to the PR branch.
  `local-main` carries it; `feat/bounded-forgetting` does not. That divergence is real and
  pre-existing, and it is a separate decision.
- Any change to `deletion_max_degree`, `deletion_strong_edge_weight`, or any other setting.
- A new configurable list of non-protective edge types. One hardcoded tuple until a second entry
  earns its place.

---

## Risk register

- **Verified:** the code paths (`forgetting_manager.py:118-121`, `:159-165`, `:188`, `:212-221`),
  the `edges` schema, the branch topology, the absence of the cited test from version control,
  and the live-store measurement showing zero verdict changes.
- **Assumed:** that the live store is representative of what users' stores look like. It is 284
  nodes and was reduced from 36.7k on 2026-08-12 — so "zero verdicts change" is a statement about
  *this* store today, not a bound on the fix's effect elsewhere. A larger store with many
  low-degree contested nodes would see real deletions.
- **Consequence to watch:** this change can only ever make **more** nodes deletable, never fewer.
  Deletion is soft (tombstone + `deletion_retention_days` before hard purge), so a wrong verdict
  is recoverable within the retention window — but the window is the whole safety margin.

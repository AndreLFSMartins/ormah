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

### Measured blast radius — verified 2026-08-13, and it is zero

The issue reports 1,709 strong `contradicts` edges shielding 2,610 archival nodes. That
measurement came from a 36.7k-node store that **no longer exists**. Re-measured against the live
store (`~/.local/share/ormah/memory/index.db`, read-only):

| Metric | Issue (2026-08-12) | Live store (2026-08-13) |
|---|---|---|
| nodes total | 36,700 | 284 (127 archival) |
| `contradicts` edges with `weight >= 0.7` | 1,709 | 12 |
| archival nodes shielded *solely* by gate #6 via `contradicts` | 2,610 | **0** |

All 13 archival nodes touching a strong `contradicts` edge have `degree >= 4`, so the **degree**
arm already protects them; the `max_weight` arm never decides their fate. The patch proposed in
the issue — filtering only `MAX(weight)` — would change **zero** verdicts on this store.

Two conclusions follow, and both shape this design:

1. The bug is real and worth fixing (the semantics are wrong regardless of today's counts), but
   it is a **preventive correction landed before PR #31 merges**, not remediation of live damage.
   No claim of rescued nodes belongs in the commit message.
2. `degree` ignores `edge_type` too, and `degree` is the arm that actually fires. Fixing only
   `max_weight` leaves the fix inert exactly where it matters.

---

## Design

### 1. One definition of value-bearing connectivity, applied to both arms

```python
# Edge types that are not evidence of value: a contested memory is not a valuable one.
_NON_PROTECTIVE_EDGE_TYPES = ("contradicts",)


def _connectivity(engine, node_id: str) -> tuple[int, float]:
    """Degree and max weight over *value-bearing* edges only (gate #6 / forget-score)."""
    placeholders = ",".join("?" * len(_NON_PROTECTIVE_EDGE_TYPES))
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree, COALESCE(MAX(weight), 0) AS max_w "
        "FROM edges WHERE (source_id = ? OR target_id = ?) "
        f"AND edge_type NOT IN ({placeholders})",
        (node_id, node_id, *_NON_PROTECTIVE_EDGE_TYPES),
    ).fetchone()
    return row["degree"], row["max_w"]
```

Two deliberate differences from the patch sketched in the issue:

- **The whole row is filtered, not just the aggregate.** `degree` and `max_w` share one notion of
  "an edge that counts". Splitting them would leave the degree arm as an unexplained exception.
- **A named module constant, not a literal in the SQL.** The reason for the exclusion lives in
  one place, and adding a second type later is a one-line change with no SQL surgery.

`edges.edge_type` is `TEXT NOT NULL` (schema verified; 0 NULL rows in the live store), so
`NOT IN (...)` carries no three-valued-logic trap. `MAX` ignores NULL weights and `COALESCE`
covers the empty-set case, exactly as before.

### 2. `evolved_from` stays protective — out of scope, on purpose

`evolved_from` is the other candidate for exclusion: a superseded node arguably should not earn
immunity either. It is deliberately left alone. The edge is directional and `r-spade/ormah#194`
documents that the maintenance agent picks its direction without creation dates. `_connectivity`
matches `source_id OR target_id`, so excluding `evolved_from` would strip protection symmetrically
— from the surviving node as much as the superseded one. Widening the fix on an unreliable
signal trades one wrong verdict for another.

`contradicts` has no such problem: its semantics are symmetric. Both endpoints of a contradiction
are contested; neither is evidence of value.

### 3. Accepted ripple — the cap backstop reorders

`_evaluate_protection` returns `degree`, and that value flows straight into the cap backstop's
forget-score (`forgetting_manager.py:188` → `:212-221`):

```python
return (1.0 - r) * (1.0 - importance) * age_days * (1.0 / (1 + degree))
```

With the filter, a node whose edges are mostly `contradicts` gets a lower `degree`, hence a
**higher forget-score**, hence earlier eviction when `archival_soft_cap` overflows.

This is intended. The cap ranks by dead weight, and a contested memory is dead weight. The
alternative — one degree for the gate and a different degree for the score — would be an
incoherence with no defensible justification. The docstring records the single definition.

`_forget_score` is not otherwise touched; the change reaches it only through the `degree`
argument.

---

## Testing

The reproducing test the issue cites lives in `tests/test_conflict_claims_investigation.py`,
which is listed in `.git/info/exclude` — it is **not versioned**. There is no assertion to
invert. All four tests below are new, in the committed
[`tests/test_background/test_forgetting_manager.py`](../../../tests/test_background/test_forgetting_manager.py).

| # | Test | Expected RED (before fix) | Arm covered |
|---|---|---|---|
| 1 | `test_contradicts_edge_does_not_protect` | fails — node survives | `max_weight`: one `contradicts` edge at `weight=0.9` must **not** save the node |
| 2 | `test_supports_edge_still_protects` | passes before and after | non-regression on the legitimate path |
| 3 | `test_contradicts_edges_do_not_count_toward_degree` | fails — node survives | `degree`: three `contradicts` edges at `weight=0.1` (`degree=3 > deletion_max_degree=2`) must **not** save the node |
| 4 | `test_cap_ranks_contradicted_node_worse` | fails — wrong node evicted | the `_forget_score` ripple through the cap backstop |

Test 3 is the one the issue's own patch would not have satisfied; it is the proof the fix is not
inert.

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
2. TDD in the worktree — tests 1, 3 and 4 RED first (test 2 is green throughout by design), then
   the `_connectivity` change turns them green.
3. Run both gates and cite their output.
4. Commit on `feat/bounded-forgetting`, `git push fork feat/bounded-forgetting`. PR #31 picks the
   commit up on its own.
5. Back in `Tools/ormah`, which is already on `local-main`: `git merge feat/bounded-forgetting`
   (Recipe B) so the Beta runs it. No branch switch is involved.
6. Close `AndreLFSMartins/ormah#1`, citing the commit and the re-measured (zero) blast radius.

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

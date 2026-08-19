# Design — Issue #222: stop importance from permanently blocking working-tier decay

**Issue:** [r-spade/ormah#222](https://github.com/r-spade/ormah/issues/222)
**Landing order:** #220 (done, PR #234) → **#222** → #221 → #223
**Decision source:** #191 (closed design decision), transcribed in `docs/lifecycle/2026-08-14-issue-dossier.md` §4.

## Problem

`working → archival` demotion currently requires both `R < fsrs_decay_threshold` **and**
`importance < decay_importance_threshold`. Importance mixes cumulative access count, edge
count, and an FSRS-derived recency signal. Cumulative signals alone can permanently exceed
the default `0.5` gate (measured case: 50 accesses + 4 edges → non-recency contribution
≈ `0.51445`), so such a node can never leave `working` no matter how stale it becomes.
Separately, `importance_recency_half_life_days=14` is configured but never read — importance
recency instead reuses FSRS retrievability (`exp(-days/stability)`), coupling two concepts
that #191 wants independent.

## Decision (from #191)

- Retrievability alone controls `working → archival`; importance is no longer a pre-gate for
  demotion.
- Importance's own recency signal uses `importance_recency_half_life_days`, independent of
  stability.
- Importance still applies to ranking, display, and core-cap prioritization — unchanged.
- `core` remains the explicit mechanism for permanent whisper eligibility (unaffected by this
  change; core nodes never enter the decay loop).

## Changes

### 1. `src/ormah/background/decay_manager.py`

Remove the importance pre-gate: the `node_importance = ...` read and the
`if node_importance >= importance_threshold: continue` branch, plus the
`importance_threshold = settings.decay_importance_threshold` line. Demotion becomes a
function of retrievability only. Existing protections are untouched: the loop only ever
scans `tier = 'working'` rows (core is structurally excluded), and the explicit
`user_node_id` skip (identity protection) stays.

### 2. `src/ormah/background/importance_scorer.py`

Replace the recency signal:

```python
# before
recency_signal = math.exp(-days_ago / stability)

# after
recency_signal = math.exp(-math.log(2) * days_ago / settings.importance_recency_half_life_days)
```

Anchor is unchanged (`last_review or last_accessed`). `stability` is dropped from the row
`SELECT` — no longer read by this job.

### 3. `src/ormah/config.py`

Keep the `decay_importance_threshold` field; update its comment only.

The field is not dead config after this change: `forgetting_manager._evaluate_protection`
reads it as gate #4 (high-importance protection) of bounded forgetting. That code is on
`main` behind `deletion_enabled=False`, and #191 explicitly gated #28/#31 until the lifecycle
signals are corrected. Renaming or removing the field here would pull a decay bugfix into
gated #28/#31 territory and collide with the rebase/split #31 already owes.

The comment changes from `# Decay: skip nodes above this importance` to state that the value
now governs bounded-forgetting protection, not decay, referencing #222 and #31. The shared
`field_validator` at `config.py:996` (`decay_importance_threshold`, `fsrs_decay_threshold`) is
untouched.

Recorded as a debt on the #31 side: [issue #223 comment](https://github.com/r-spade/ormah/issues/223#issuecomment-5307883033)
parks the rename for #31, which comes out of draft once #223 lands.

### Out of scope

`tier_manager.py`, `forgetting_manager.py`, the importance weight/normalization logic
(`importance_access_weight`/`importance_edge_weight`/`importance_recency_weight`), and the
rest of the decay pipeline are unchanged.

## Testing

- `tests/test_background/test_decay_manager.py`:
  - `test_high_importance_node_not_decayed` inverts: it currently asserts the behavior being
    removed. Rewrite to assert a stale high-importance node **is** demoted — including a
    variant reproducing the reported case (50 accesses, 4 edges, importance ≈ 0.514).
  - `test_low_importance_stale_node_decayed`, `test_decay_still_works_without_importance`,
    `test_decay_is_idempotent`, `test_decay_writes_audit_log`: importance values in these
    tests are incidental (all were already below the old 0.5 threshold), so their assertions
    hold unchanged — no edits needed, just re-run to confirm.
- `tests/test_background/test_importance_scorer.py` — two new tests:
  - Recency signal is independent of stability: same age, `stability=1.0` vs `stability=100.0`
    on otherwise-identical nodes → identical `recency_signal`.
  - Recency signal follows the configured half-life: `days_ago == importance_recency_half_life_days`
    → `recency_signal ≈ 0.5`.

## Docs

- `docs/05 - Background Jobs.md` and `docs/12 - Configuration Reference.md` — update the
  decay/importance descriptions, remove the `decay_importance_threshold` mention.

## Fork workflow

Per `FORK-WORKFLOW.md` Recipe A: `git worktree add -b fix/222-<slug> ../ormah-wt-222 upstream/main`,
work in the worktree (not in this checkout, which serves the running Beta), push to `fork`,
open the PR against `r-spade:main`.

# Task 3: `run_decay` — per-node apply step and tier revalidation

Read `00-overview.md` first. Requires Tasks 1 and 2.

**Files:**
- Modify: `src/ormah/background/decay_manager.py` (86 lines — read the whole file first)
- Test: `tests/test_background/test_decay_manager.py` (append; do not rewrite existing tests)

**Interfaces:**
- Consumes: `restore_aware_job`, `engine.memory_operation_at(epoch)` (Task 1); `install_probe` (Task 2).
- Produces: nothing other tasks depend on.

## Why this job carries the revalidation

Whole-run exclusion is the only thing that stops decay from demoting a node that got promoted *after* decay snapshotted it. Removing it opens that window, so this task closes it in the same commit — inside the apply step, re-read the row and recompute. This is the debt this change itself creates (spec §5), and it is also the piece that keeps PR #257's promotion behaviour correct. It lives entirely in `decay_manager.py` on purpose: no engine API changes, and #257 does not touch this module.

**`RestoredUnderfoot` must escape the job's `except Exception`.** `run_decay`'s body is one big `try/except Exception` (`:24`/`:85`). Add an explicit re-raise before it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_decay_manager.py`:

```python
def test_decay_takes_the_lock_once_per_demoted_node_not_once_per_run(engine):
    """The default-install bug: no LLM anywhere, yet L_mem is held for the whole run."""
    from tests.test_background.lock_probe import install_probe

    ids = []
    for i in range(3):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"stale node {i}", type=NodeType.fact, tier=Tier.working,
            title=f"stale {i}"))
        _make_stale(engine, nid)
        ids.append(nid)

    probe = install_probe(engine)
    run_decay(engine)

    assert all(_get_tier(engine, nid) == "archival" for nid in ids)
    # Before the fix: exactly 1, whatever the node count. After: one per demotion.
    assert probe.acquisitions >= 3


def test_decay_does_not_demote_a_node_promoted_after_the_snapshot(engine):
    """#257's canary, written here: revalidate tier inside the apply step.

    Decay snapshots the node as a stale 'working' candidate. Between that snapshot
    and the locked apply step, a foreground promotion refreshes it. Without
    per-apply-step revalidation the demotion would land anyway and silently undo
    the promotion.

    The hook point matters: it must land the promotion between the unlocked outer
    scan and the locked `_still_decays` re-check — not between `_still_decays` and
    `update_node`, which are both inside the same `memory_operation_at(epoch)` and
    so can never observe an interleaved write (every engine mutator takes the same
    lock). `lifecycle.retrievability` runs in the outer scan, once per candidate
    row, which makes it the right seam: patching it fires exactly once, before
    that node's locked apply step, and does not touch `_still_decays` or
    `update_node` — the code under test.
    """
    from ormah import lifecycle

    node_id, _ = engine.remember(CreateNodeRequest(
        content="about to be promoted", type=NodeType.fact, tier=Tier.working,
        title="promoted"))
    _make_stale(engine, node_id)

    real_retrievability = lifecycle.retrievability
    promoted = {"done": False}

    def promote_then_compute(days_since, stability, **kwargs):
        """Stand in for a concurrent foreground promotion landing right after the
        outer scan snapshots this node as a stale candidate."""
        if not promoted["done"]:
            promoted["done"] = True
            fresh = datetime.now(timezone.utc).isoformat()
            engine.db.conn.execute(
                "UPDATE nodes SET last_accessed = ?, last_review = ?, tier = 'working' "
                "WHERE id = ?", (fresh, fresh, node_id))
            engine.db.conn.commit()
        return real_retrievability(days_since, stability, **kwargs)

    lifecycle.retrievability = promote_then_compute
    try:
        run_decay(engine)
    finally:
        lifecycle.retrievability = real_retrievability

    assert _get_tier(engine, node_id) == "working"


def test_decay_aborts_the_run_when_a_restore_lands_mid_run(engine):
    """Abort, do not skip: the whole snapshot is stale, and nothing may be written."""
    ids = []
    for i in range(3):
        nid, _ = engine.remember(CreateNodeRequest(
            content=f"stale {i}", type=NodeType.fact, tier=Tier.working, title=f"s{i}"))
        _make_stale(engine, nid)
        ids.append(nid)

    real_update = engine.update_node
    demotions = {"count": 0}

    def bump_after_first(nid, req, *args, **kwargs):
        result = real_update(nid, req, *args, **kwargs)
        demotions["count"] += 1
        if demotions["count"] == 1:
            engine._restore_epoch += 1
        return result

    engine.update_node = bump_after_first
    run_decay(engine)  # returns cleanly, does not raise

    assert demotions["count"] == 1
    assert sum(_get_tier(engine, nid) == "archival" for nid in ids) == 1
```

Add to that file's imports if missing: `from ormah.models.node import UpdateNodeRequest` is imported inside the test above, so only confirm `datetime`, `timezone`, `CreateNodeRequest`, `NodeType`, `Tier` and `run_decay` are already imported at module level — they are (lines 1–11).

- [ ] **Step 2: Run them to verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_decay_manager.py -q -k "lock or promoted or aborts"
```

Expected, all three failing, each for its own reason:
- `..._once_per_demoted_node`: `assert 1 >= 3`
- `..._promoted_after_the_snapshot`: `assert 'archival' == 'working'`
- `..._aborts_the_run`: `assert 3 == 1` (all three demote; nothing checks the epoch)

- [ ] **Step 3: Rewrite `run_decay`**

Replace the import and the decorator, and restructure the loop body. Full new file body from line 8 onward:

```python
from ormah import lifecycle
from ormah.background.memory_lock import RestoredUnderfoot, restore_aware_job
from ormah.models.node import Tier, UpdateNodeRequest

logger = logging.getLogger(__name__)


def _still_decays(engine, node_id: str, now, settings) -> bool:
    """Re-read the row and recompute retrievability inside the apply step.

    L_mem no longer spans the run, so a promotion can land between the snapshot
    query and this demotion. Re-reading here — under the same lock that will
    write — is what keeps a freshly-used node in working (#223/#240).
    """
    row = engine.db.conn.execute(
        "SELECT tier, stability, last_review, last_accessed FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    if row is None or row["tier"] != "working":
        return False

    anchor_str = row["last_accessed"] or row["last_review"]
    try:
        anchor = datetime.fromisoformat(anchor_str)
        days_since = max((now - anchor).total_seconds() / 86400, 0.001)
    except (ValueError, TypeError):
        return False

    retrievability = lifecycle.retrievability(
        days_since,
        row["stability"],
        fallback_stability=settings.fsrs_initial_stability,
    )
    return retrievability < settings.fsrs_decay_threshold


@restore_aware_job
def run_decay(engine, epoch: int) -> None:
    """Auto-demote working nodes whose FSRS retrievability drops below threshold.

    Retrievability alone decides (#222/#191). Importance is deliberately not a
    pre-gate: cumulative access and edge counts could push it permanently above
    any threshold, pinning a stale node to working forever. Identity (the self
    node) and core stay protected — core never enters this query.

    The candidate scan runs unlocked; each demotion takes L_mem for itself and
    revalidates the node first (#240).
    """
    try:
        settings = engine.settings
        now = datetime.now(timezone.utc)

        # One-time cleanup: remove legacy pending decay proposals
        with engine.memory_operation_at(epoch):
            with engine.db.transaction() as conn:
                conn.execute(
                    "DELETE FROM proposals WHERE type = 'decay' AND status = 'pending'"
                )

        rows = engine.db.conn.execute(
            "SELECT id, stability, last_review, last_accessed "
            "FROM nodes WHERE tier = 'working'"
        ).fetchall()

        if not rows:
            return

        user_node_id = getattr(engine, "user_node_id", None)
        r_threshold = settings.fsrs_decay_threshold

        demoted = 0
        for row in rows:
            if row["id"] == user_node_id:
                continue

            # Compute FSRS retrievability through the shared implementation (#221).
            # Anchor on use, not on the numeric stability update: the per-day
            # reinforcement cooldown can leave last_review a full window behind
            # the last use, and an actively used node must not read as stale.
            anchor_str = row["last_accessed"] or row["last_review"]
            try:
                anchor = datetime.fromisoformat(anchor_str)
                days_since = max((now - anchor).total_seconds() / 86400, 0.001)
            except (ValueError, TypeError):
                logger.warning(
                    "Decay manager skipped node %s with invalid recency anchor %r",
                    row["id"][:8],
                    anchor_str,
                )
                continue
            # Pass the stored stability raw and let lifecycle own the zero case,
            # with the SAME fallback reinforcement uses. Hardcoding 1.0 here
            # while reinforcement falls back to fsrs_initial_stability is how
            # the two paths silently disagree (council round 3, I3).
            retrievability = lifecycle.retrievability(
                days_since,
                row["stability"],
                fallback_stability=settings.fsrs_initial_stability,
            )

            if retrievability >= r_threshold:
                continue

            with engine.memory_operation_at(epoch):
                if not _still_decays(engine, row["id"], datetime.now(timezone.utc), settings):
                    continue
                result = engine.update_node(row["id"], UpdateNodeRequest(tier=Tier.archival))
                if result:
                    demoted += 1

        if demoted:
            logger.info("Decay manager demoted %d nodes to archival", demoted)

    except RestoredUnderfoot:
        raise  # restore_aware_job ends the run; never swallowed as a generic failure
    except Exception as e:
        logger.warning("Decay manager failed: %s", e)
```

Note on the `continue` inside `with engine.memory_operation_at(epoch):` — it exits the context manager cleanly, releasing the lock. That is intended.

- [ ] **Step 4: Run the whole decay file**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python \
  -m pytest tests/test_background/test_decay_manager.py -q
```

Expected: all pass, including the pre-existing tests (`test_high_importance_stale_node_is_decayed`, `test_invalid_timestamp_skips_one_node_without_aborting_decay`, and the rest of the file). If a pre-existing test now fails, stop — that is a regression, not a stale expectation.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/background/decay_manager.py tests/test_background/test_decay_manager.py
git commit -m "fix(decay): take L_mem per demotion and revalidate tier at apply time (#240)"
```

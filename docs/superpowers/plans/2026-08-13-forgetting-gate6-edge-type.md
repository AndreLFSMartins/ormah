# Forgetting gate #6 — ignore non-value-bearing edges — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `contradicts` edges from making an archival node undeletable, in **both** arms of forgetting gate #6 (`degree` and `max_weight`).

**Architecture:** One change to one function. `_connectivity` in `src/ormah/background/forgetting_manager.py` filters the `edges` rows it aggregates, so `degree` and `max_weight` share a single definition of "an edge that counts as value". The filtered `degree` flows on to `_forget_score`, deliberately reordering the cap backstop — that ripple is locked in by a test, not left implicit.

**Tech Stack:** Python 3.11, SQLite (`engine.db.conn`), pytest (`asyncio_mode = auto`), ruff (`line-length = 100`, `target-version = py311`), git worktrees.

**Spec:** `docs/superpowers/specs/2026-08-13-forgetting-gate6-edge-type-design.md`
**Issue:** `AndreLFSMartins/ormah#1`

## Global Constraints

- **Work in a git worktree.** NEVER `git checkout` another branch inside `/Users/andre/Documents/GitHub/Tools/ormah` — that working tree is what the running Beta serves (`launchd com.ormah.server.dev`); switching its branch swaps the live server's code and crashes every whisper hook (`FORK-WORKFLOW.md` Golden rule 1).
- **Target branch is `feat/bounded-forgetting`** — the head of open PR `r-spade/ormah#31`. Do NOT cut a branch from `upstream/main`: `forgetting_manager.py` does not exist there, so `FORK-WORKFLOW.md` Recipe A does not apply here.
- **Push branches to `fork` only** (`AndreLFSMartins/ormah`), never to `upstream`/`origin`.
- **English** in all code, comments, tests and commit messages (project CLAUDE.md).
- **Exactly two files change:** `src/ormah/background/forgetting_manager.py` and `tests/test_background/test_forgetting_manager.py`. Nothing else — no settings, no config, no other module.
- **`evolved_from` stays protective.** Only `contradicts` is excluded. Widening the exclusion is out of scope (see spec §2).
- **Do not back-port `f7ac305`** (`@serialized_memory_job` on `run_forgetting`) to the PR branch. It lives on `local-main` only; that divergence is a separate decision.
- **Every new test must set `engine.settings.auto_link_similarity_threshold = 1.1` before creating its nodes.** `engine.remember` auto-links on content similarity, and fixture nodes with similar titles connect into a clique that shields them by connectivity — the exact confound documented at `tests/test_background/test_forgetting_manager.py:136-141`.

---

### Task 1: `_connectivity` ignores non-value-bearing edge types

**Files:**
- Modify: `src/ormah/background/forgetting_manager.py:159-165` (the `_connectivity` function)
- Test: `tests/test_background/test_forgetting_manager.py` (append four tests)

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first).
- Produces: `_connectivity(engine, node_id) -> tuple[int, float]` — unchanged signature and return contract (`(degree, max_weight)`); only which edge rows it counts changes. Module-level constant `_NON_PROTECTIVE_EDGE_TYPES: tuple[str, ...]` is added and used nowhere else.

---

- [ ] **Step 1: Create the worktree**

Run from `/Users/andre/Documents/GitHub/Tools/ormah`:

```bash
git fetch fork feat/bounded-forgetting
git worktree add /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6 feat/bounded-forgetting
```

Expected: `Preparing worktree (checking out 'feat/bounded-forgetting')` then `HEAD is now at 7130d39 ...`.

Uses the **local** branch `feat/bounded-forgetting` (verified identical to `fork/feat/bounded-forgetting` @ `7130d39`, and checked out in no other worktree). Using the remote-tracking ref `fork/feat/bounded-forgetting` instead would produce a detached HEAD and commits would land nowhere.

- [ ] **Step 2: Confirm the worktree's code is what pytest will import**

The venv at `/Users/andre/Documents/GitHub/Tools/ormah/.venv` is an editable install whose `.pth` points at the **main** tree's `src/`. Every test command in this plan therefore prefixes `PYTHONPATH` with the worktree's `src/`, which takes precedence over `.pth` entries. Verify that once:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-gate6/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python \
  -c "import ormah.background.forgetting_manager as m; print(m.__file__)"
```

Expected output — the path MUST start with `ormah-wt-gate6`:

```
/Users/andre/Documents/GitHub/Tools/ormah-wt-gate6/src/ormah/background/forgetting_manager.py
```

If it prints the `Tools/ormah/src/...` path instead, STOP: every later test result would be measuring the wrong tree.

- [ ] **Step 3: Write the four failing tests**

Append to `tests/test_background/test_forgetting_manager.py`, after `test_strong_edge_protects_both_nodes` (line 103). `_make_eligible`, `_make_archival_recent`, `_enable` and `_exists` already exist in this file; `ConnectRequest` and `EdgeType` are already imported at line 10.

```python
# --- gate #6 counts only value-bearing edges (fork #1) -----------------------
#
# Peers are built with _make_archival_recent (recent last_accessed ⇒ never gate-stale ⇒ never a
# Phase A candidate) and importance=0.9 (gate #4 ⇒ protected in the cap too). They therefore
# survive every run, so the edges under test are still in place when the subject is evaluated.

def test_contradicts_edge_does_not_protect(engine):
    """gate #6, max_weight arm: a strong `contradicts` edge is not evidence of value."""
    _enable(engine)
    engine.settings.auto_link_similarity_threshold = 1.1   # no incidental edges
    subject = _make_eligible(engine, content="contested claim")
    peer = _make_archival_recent(engine, "peer keeper", archived_days=400, importance=0.9)
    engine.connect(ConnectRequest(
        source_id=subject, target_id=peer, edge=EdgeType.contradicts, weight=0.9))
    run_forgetting(engine)
    assert _exists(engine, subject) is False
    assert _exists(engine, peer) is True


def test_supports_edge_still_protects(engine):
    """Non-regression: the legitimate strong-edge path is untouched."""
    _enable(engine)
    engine.settings.auto_link_similarity_threshold = 1.1
    subject = _make_eligible(engine, content="supported claim")
    peer = _make_archival_recent(engine, "peer keeper", archived_days=400, importance=0.9)
    engine.connect(ConnectRequest(
        source_id=subject, target_id=peer, edge=EdgeType.supports, weight=0.9))
    run_forgetting(engine)
    assert _exists(engine, subject) is True


def test_contradicts_edges_do_not_count_toward_degree(engine):
    """gate #6, degree arm: 3 weak `contradicts` edges must not make a node a hub.

    deletion_max_degree defaults to 2, so degree=3 protects today; every weight is 0.1, well
    under deletion_strong_edge_weight (0.7), so the max_weight arm cannot be what fires here.
    """
    _enable(engine)
    engine.settings.auto_link_similarity_threshold = 1.1
    subject = _make_eligible(engine, content="contested hub")
    for i in range(3):
        peer = _make_archival_recent(engine, f"hub peer {i}", archived_days=400, importance=0.9)
        engine.connect(ConnectRequest(
            source_id=subject, target_id=peer, edge=EdgeType.contradicts, weight=0.1))
    run_forgetting(engine)
    assert _exists(engine, subject) is False


def test_cap_ranks_contradicted_node_worse(engine):
    """The accepted ripple: the filtered degree reaches _forget_score, reordering the cap.

    Both candidates share importance (0.1), stability and last_review, so the forget-score
    reduces to `age_days / (1 + degree)`:
        before — contested 300/(1+2) = 100  <  plain 200/(1+0) = 200  ⇒ plain evicted
        after  — contested 300/(1+0) = 300  >  plain 200/(1+0) = 200  ⇒ contested evicted
    4 archival nodes with archival_soft_cap=3 ⇒ overflow of exactly 1, so precisely one of the
    two unprotected candidates is evicted and the assertions are unambiguous.
    """
    _enable(engine)
    engine.settings.auto_link_similarity_threshold = 1.1
    engine.settings.archival_soft_cap = 3
    contested = _make_archival_recent(engine, "contested old", archived_days=300)
    plain = _make_archival_recent(engine, "plain mid", archived_days=200)
    for i in range(2):   # degree 2 ⇒ NOT > deletion_max_degree (2) ⇒ not protected, only scored
        peer = _make_archival_recent(engine, f"cap peer {i}", archived_days=400, importance=0.9)
        engine.connect(ConnectRequest(
            source_id=contested, target_id=peer, edge=EdgeType.contradicts, weight=0.1))
    run_forgetting(engine)
    assert _exists(engine, contested) is False
    assert _exists(engine, plain) is True
```

- [ ] **Step 4: Run the four tests and verify three of them fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-gate6/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_forgetting_manager.py -v \
  -k "contradicts or supports_edge_still or cap_ranks"
```

Expected: `3 failed, 1 passed`.

- `test_contradicts_edge_does_not_protect` — **FAIL** at `assert _exists(engine, subject) is False` (`assert True is False`)
- `test_contradicts_edges_do_not_count_toward_degree` — **FAIL** at the same assertion
- `test_cap_ranks_contradicted_node_worse` — **FAIL** at `assert _exists(engine, contested) is False`
- `test_supports_edge_still_protects` — **PASS** (it is the non-regression guard; green before and after by design)

If any of the three passes already, STOP and report: either an incidental auto-link edge or a fixture change has broken the setup, and the test is not measuring the gate.

- [ ] **Step 5: Implement the filter**

In `src/ormah/background/forgetting_manager.py`, add the constant immediately above `_connectivity` and replace the function body. Current text (lines 159-165):

```python
def _connectivity(engine, node_id: str) -> tuple[int, float]:
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree, COALESCE(MAX(weight), 0) AS max_w "
        "FROM edges WHERE source_id = ? OR target_id = ?",
        (node_id, node_id),
    ).fetchone()
    return row["degree"], row["max_w"]
```

Replace with:

```python
# Edge types that are not evidence of value: a contested memory is not a valuable one. Both
# endpoints of a `contradicts` edge are contested, so excluding it symmetrically is correct.
# `evolved_from` is deliberately NOT here — its direction is decided without creation dates
# (r-spade/ormah#194), so excluding it would strip protection from the surviving node too.
_NON_PROTECTIVE_EDGE_TYPES: tuple[str, ...] = ("contradicts",)


def _connectivity(engine, node_id: str) -> tuple[int, float]:
    """Degree and max weight over *value-bearing* edges only.

    Both gate #6 arms and `_forget_score`'s connectivity factor read this single definition:
    an edge that does not count toward the hub arm does not count toward the strong-edge arm
    either, and a node whose edges are mostly contradictions scores as the dead weight it is.
    """
    placeholders = ",".join("?" * len(_NON_PROTECTIVE_EDGE_TYPES))
    row = engine.db.conn.execute(
        "SELECT COUNT(*) AS degree, COALESCE(MAX(weight), 0) AS max_w "
        "FROM edges WHERE (source_id = ? OR target_id = ?) "
        f"AND edge_type NOT IN ({placeholders})",
        (node_id, node_id, *_NON_PROTECTIVE_EDGE_TYPES),
    ).fetchone()
    return row["degree"], row["max_w"]
```

`edges.edge_type` is `TEXT NOT NULL` (schema verified), so `NOT IN` has no NULL trap. The parentheses around `source_id = ? OR target_id = ?` are load-bearing: without them `AND` binds tighter than `OR` and the filter would apply to only one side of the edge.

- [ ] **Step 6: Run the four tests and verify all pass**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-gate6/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_forgetting_manager.py -v \
  -k "contradicts or supports_edge_still or cap_ranks"
```

Expected: `4 passed`.

- [ ] **Step 7: Run the whole forgetting suite for regressions**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-gate6/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m pytest \
  tests/test_background/test_forgetting_manager.py -v
```

Expected: all tests pass, 0 failed. `test_strong_edge_protects_both_nodes` and `test_cap_protects_strong_edge_hub` build their edges with `EdgeType.related_to`, which stays protective — they must remain green. If either goes red, the filter is excluding more than `contradicts`.

- [ ] **Step 8: Lint**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python -m ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
git add src/ormah/background/forgetting_manager.py tests/test_background/test_forgetting_manager.py
git commit -m "fix(forgetting): gate #6 must ignore contradicts edges (fork #1)

_connectivity aggregated every edge regardless of edge_type, so a contradicts
edge proved a node valuable exactly as a supports edge did — backwards for a
job whose purpose is pruning dead weight.

Filter the rows, not just the aggregate: degree and max_weight now share one
definition of a value-bearing edge. The filtered degree also reaches
_forget_score, so the cap backstop evicts contested nodes earlier; that ripple
is intended and covered by test_cap_ranks_contradicted_node_worse.

evolved_from stays protective: its direction is chosen without creation dates
(r-spade/ormah#194), so a symmetric exclusion would strip protection from the
surviving node as well."
```

Expected: one commit on `feat/bounded-forgetting`, 2 files changed.

---

### Task 2: Publish to PR #31 and run it in the Beta

**Files:** none modified — this task only moves refs.

**Interfaces:**
- Consumes: the commit produced by Task 1, on branch `feat/bounded-forgetting`.
- Produces: nothing later tasks depend on. This is the final task.

---

- [ ] **Step 1: Push the branch to the fork**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
git push fork feat/bounded-forgetting
```

Expected: the push succeeds and `.git/hooks/pre-push` does not reject it (the commit touches only `src/` and `tests/`, no protected `docs/` path). PR `r-spade/ormah#31` picks the commit up automatically — no new PR is opened.

If the push is rejected by the pre-push hook, STOP and report which path it flagged. Do **not** use `--no-verify`.

- [ ] **Step 2: Confirm the PR now carries the commit**

```bash
gh pr view 31 --repo r-spade/ormah --json headRefOid,state,title
```

Expected: `state` is `OPEN` and `headRefOid` equals the SHA from Task 1 Step 9 (`git -C /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6 rev-parse HEAD`).

- [ ] **Step 3: Merge into the Beta**

Run from `/Users/andre/Documents/GitHub/Tools/ormah`, which is **already on `local-main`** — no branch switch is involved (`FORK-WORKFLOW.md` Recipe B):

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git rev-parse --abbrev-ref HEAD    # must print: local-main
git merge feat/bounded-forgetting
```

Expected: a merge commit, or a conflict only if someone edited `_connectivity` on `local-main` since. `local-main` carries `f7ac305` (`@serialized_memory_job`, near line 20) while the fix is near line 159 — different regions, so a clean merge is expected. If a conflict does appear, resolve by keeping **both** changes.

- [ ] **Step 4: Verify the Beta's tests still pass after the merge**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python -m pytest tests/test_background/test_forgetting_manager.py -v
```

Expected: all pass. No `PYTHONPATH` prefix here — this is the main tree the editable install already points at.

- [ ] **Step 5: Close the issue**

```bash
gh issue close 1 --repo AndreLFSMartins/ormah --comment "Fixed on \`feat/bounded-forgetting\` (PR r-spade/ormah#31), commit <SHA>.

Landed wider than the patch proposed here: \`_connectivity\` now filters the edge rows, so \`contradicts\` is excluded from **both** gate #6 arms — \`degree\` as well as \`max_weight\`. Filtering only \`max_weight\` would have been inert: re-measured against the live store on 2026-08-13, all 13 archival nodes touching a strong \`contradicts\` edge already have \`degree >= 4\`, so the degree arm is what protects them.

The 2,610-node figure in this issue came from the pre-cleanup 36.7k-node store, which no longer exists. On the current store (284 nodes, 127 archival) the fix changes **zero** verdicts — it is a preventive semantic correction landed before #31 merges, not remediation of live damage.

Design: \`docs/superpowers/specs/2026-08-13-forgetting-gate6-edge-type-design.md\` (local-main only)."
```

Replace `<SHA>` with the actual commit SHA before running.

Expected: the issue closes.

- [ ] **Step 6: Remove the worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree remove /Users/andre/Documents/GitHub/Tools/ormah-wt-gate6
```

Expected: no output. Do **not** delete the `feat/bounded-forgetting` branch, locally or on `fork` — PR #31 is still open, and deleting the fork branch would close it (`FORK-WORKFLOW.md` Recipe D).

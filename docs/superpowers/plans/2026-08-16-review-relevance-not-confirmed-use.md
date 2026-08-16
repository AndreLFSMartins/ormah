# Review Relevance Is Not Confirmed Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a relevance judgement on a memory that was never surfaced from reinforcing that memory's lifecycle.

**Architecture:** Gate the confirmed-use claim on `was_injected = 1` inside `_claim_confirmed_use`'s own INSERT, turning `INSERT ... VALUES` into `INSERT ... SELECT` over `whisper_log`. `SELECT changes()` stays the verdict. Two of the three callers already satisfy the precondition, so only the session-start review path changes behaviour.

**Tech Stack:** Python 3.12, SQLite (`sqlite3`), pytest (`asyncio_mode = auto`), ruff.

**Spec:** `docs/superpowers/specs/2026-08-16-review-relevance-not-confirmed-use-design.md`

## Global Constraints

- **Work in the worktree**: `/Users/andre/Documents/GitHub/Tools/ormah-wt-220`, branch `fix/220-confirmed-use`. Never `git checkout` inside `Tools/ormah` (Golden rule 1, `FORK-WORKFLOW.md`).
- **Interpreter**: always `./.venv/bin/python -m pytest`. **Never** bare `python -m pytest` and **never** `make test` — both resolve to the `Tools/ormah` venv and measure `local-main`. Verify before trusting any number: `./.venv/bin/python -c "import ormah; print(ormah.__file__)"` must print a path under `ormah-wt-220/src/`.
- **Do not push and do not open a PR.** Push to `fork` is not authorised; PR #229 still declares `Closes #220-#223`.
- **Nothing under `docs/` may enter this branch** (Golden rule 5). This plan and its spec live on `local-main` in `Tools/ormah`.
- `make lint` (`ruff check src/ tests/`) passes before each commit. Line length 100.
- Baseline measured 2026-08-16 before any change: `tests/test_engine/test_confirmed_use_contract.py` → **25 passed**.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/ormah/engine/memory_engine.py` | `_claim_confirmed_use` — the single writer of `confirmed_use_claims` | Modify the INSERT (L2556-2563) and the docstring's fail-closed clause (L2546-2547) |
| `tests/test_engine/test_confirmed_use_contract.py` | Contract tests for issue #220; asserts lifecycle from **both** markdown and SQLite | Add one helper and two tests |

No new files. Contracts continue the existing numbering: the file ends at 10f/7c, so the new ones are **11** and **11a**.

The spec lists four tests; two of them are already in the file and must **not** be rewritten:

- The **control** (an injected event still confirms) is `test_qualified_positive_feedback_confirms_use`, already parametrised over `explicit`/`implicit`/`auto_llm_judge`. It seeds through `_seed_whisper_log` → `recall_search` → `_log_feedback_candidates`, which hardcodes `was_injected = 1`, so it exercises exactly the positive side of the new gate.
- The **neighbour regression** check is the existing suite: contracts 7a, 8, 10b, 10e and 10f each need a claim to still be taken for injected events. They are re-run, not rewritten.

---

### Task 1: Review feedback must not claim confirmed use

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:2546-2563`
- Test: `tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: `_snapshot(engine, node_id)` and `_make_nodes(engine, count)`, already defined at the top of the test file. `_snapshot` returns `{"file": tuple, "db": tuple}` over `("access_count", "last_accessed", "stability", "last_review")`.
- Produces: `_seed_held_back_whisper_log(engine, node_id, prompt="what about caching?") -> int`, used again by Task 2.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine/test_confirmed_use_contract.py`:

```python
# --- Review relevance is not confirmed use (2026-08-16 council round) -------

def _seed_held_back_whisper_log(engine, node_id, prompt="what about caching?"):
    """Insert the kind of event the session-start review hands to the agent.

    _find_review_candidate selects rows with was_injected = 0 — memories Ormah
    held back and never surfaced — and _REVIEW_FRAMING hands that id to the
    agent asking for source="implicit" feedback. _seed_whisper_log cannot be
    used here: it goes through recall_search, which writes was_injected = 1.

    logged_at is a Python ISO timestamp, not SQLite's datetime('now'), because
    _log_feedback_candidates writes ISO and the fallback orders by this column
    as TEXT. The two formats differ at index 10 — 'T' (0x54) against ' '
    (0x20) — so a datetime('now') row sorts BEFORE an ISO row written in the
    same second, and the fallback would silently resolve the wrong event.
    """
    from datetime import datetime, timezone

    cursor = engine.db.conn.execute(
        "INSERT INTO whisper_log "
        "(session_id, space, prompt_hash, prompt_text, prompt_vec, node_id, "
        "score, decision_stage, was_injected, logged_at) "
        "VALUES ('sess-review', 'myspace', 'hash-review', ?, X'', ?, 0.31, "
        "'injection_gate', 0, ?)",
        (prompt, node_id, datetime.now(timezone.utc).isoformat()),
    )
    engine.db.conn.commit()
    return cursor.lastrowid


def test_review_relevance_feedback_does_not_confirm_use(engine):
    """Contract 11: judging a held-back memory relevant is not using it.

    The review path deliberately surfaces an event with was_injected = 0 and
    asks "would this have been useful?" — a relevance adjudication, not a use.
    _claim_confirmed_use allowlists "implicit" and checks no provenance, so the
    claim is taken and the lifecycle advances on a memory the agent never saw.
    That is fabricated retention entering through the review door, which is what
    issue #220 exists to close.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    held_back_id = _seed_held_back_whisper_log(engine, target)

    before = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit", whisper_log_id=held_back_id)

    assert _snapshot(engine, target) == before, (
        "relevance feedback on a memory that was never surfaced reinforced it"
    )
    claims = engine.db.conn.execute(
        "SELECT COUNT(*) FROM confirmed_use_claims WHERE whisper_log_id = ?",
        (held_back_id,),
    ).fetchone()[0]
    assert claims == 0, "a held-back event took a confirmed-use claim"

    # The judgement itself is still evidence — only the lifecycle is off limits.
    affinity = engine.db.conn.execute(
        "SELECT * FROM affinity WHERE whisper_log_id = ? AND node_id = ?",
        (held_back_id, target),
    ).fetchone()
    assert affinity is not None, "review feedback stopped recording affinity"
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220
./.venv/bin/python -c "import ormah; print(ormah.__file__)"
./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py::test_review_relevance_feedback_does_not_confirm_use -v
```

Expected: **FAIL** on the first assertion — `relevance feedback on a memory that was never surfaced reinforced it`. A failure on `_make_nodes`, on the INSERT, or a `KeyError` means the fixture is wrong, not the code: fix the fixture and re-run before going on. A **PASS** here means the test does not reach the defect — stop and diagnose.

- [ ] **Step 3: Gate the claim on `was_injected = 1`**

In `src/ormah/engine/memory_engine.py`, replace the INSERT inside `_claim_confirmed_use`:

```python
        if whisper_log_id is None or signal != 1 or source not in _CONFIRMED_USE_SOURCES:
            return False
        conn.execute(
            """
            INSERT INTO confirmed_use_claims (whisper_log_id, node_id, claimed_at)
            SELECT wl.id, ?, datetime('now')
            FROM whisper_log wl
            WHERE wl.id = ? AND wl.was_injected = 1
            ON CONFLICT DO NOTHING
            """,
            (node_id, whisper_log_id),
        )
        return conn.execute("SELECT changes()").fetchone()[0] == 1
```

Note the parameter order flips to `(node_id, whisper_log_id)` — the node id is now the SELECT's literal and the event id its WHERE. Getting this backwards silently claims nothing.

- [ ] **Step 4: Extend the docstring's fail-closed clause**

In the same method, replace the paragraph that currently reads *"Fail-closed: an unqualified signal, a source outside the allowlist, or a missing whisper_log_id claims nothing."* with:

```python
        Fail-closed: an unqualified signal, a source outside the allowlist, a
        missing whisper_log_id, or an event that was never injected claims
        nothing. was_injected = 1 is the provenance test: only a memory the
        agent actually saw can have been used. The session-start review path
        (_find_review_candidate, _REVIEW_FRAMING) deliberately hands the agent a
        was_injected = 0 event and asks whether it *would* have been useful, and
        that answer is relevance, not use. The other two callers already satisfy
        this — _log_feedback_candidates hardcodes was_injected = 1 and the
        session watcher filters on it — so the condition costs them nothing.

        Enforced in SQL rather than by the caller so a future fourth caller
        cannot reopen the hole. changes() returns 0 both for a non-injected
        event and for an already-taken claim; both mean "do not reinforce".
```

- [ ] **Step 5: Run the new test — expect PASS**

```bash
./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py::test_review_relevance_feedback_does_not_confirm_use -v
```

Expected: **PASS**.

- [ ] **Step 6: Run the whole contract file — the neighbours must not move**

```bash
./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py -q
```

Expected: **26 passed** (the 25 of the baseline, plus the new one). Contracts 7a, 8, 10b, 10e and 10f all depend on a claim still being taken for injected events; any failure there means the gate is too wide, not that the test is stale.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ tests/
git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py
git commit -m "fix(lifecycle): review relevance does not claim confirmed use"
git show --stat HEAD
```

Expected: ruff clean; `git show --stat HEAD` lists exactly **2 files changed**.

---

### Task 2: Pin the legacy fallback's accepted loss

**Files:**
- Test: `tests/test_engine/test_confirmed_use_contract.py`

**Interfaces:**
- Consumes: `_snapshot`, `_make_nodes`, and `_seed_held_back_whisper_log` from Task 1.
- Produces: nothing. This task adds no `src` change — it characterises a consequence Task 1 introduces, which André signed off on 2026-08-16.

- [ ] **Step 1: Write the test**

Append to `tests/test_engine/test_confirmed_use_contract.py`:

```python
def test_legacy_fallback_on_a_held_back_event_does_not_confirm(engine):
    """Contract 11a: the fallback's accepted loss, pinned deliberately.

    submit_feedback without whisper_log_id resolves to the node's newest
    whisper row, injected or not. When that row is a held-back review
    candidate, no claim is taken even though an older injected event exists —
    a legitimate reinforcement is lost in silence. Accepted: failing closed is
    the right side to err on under the at-most-once contract, and the fallback
    already documents itself as not exact. Fixing the fallback's selection
    would also move which event affinity and signals attach to, which is a
    different defect. This test exists so that loss stays a decision rather
    than becoming a surprise.
    """
    ids = _make_nodes(engine, count=1)
    target = ids[0]
    injected_id = _seed_whisper_log(engine, target)
    held_back_id = _seed_held_back_whisper_log(engine, target)
    assert held_back_id > injected_id, "the held-back event must be the newer row"

    before = _snapshot(engine, target)

    engine.submit_feedback(target, signal=1, source="implicit")

    assert _snapshot(engine, target) == before, (
        "the legacy fallback reinforced through a held-back event"
    )
    # The fallback still attaches its evidence to the newest event — unchanged.
    affinity = engine.db.conn.execute(
        "SELECT whisper_log_id FROM affinity WHERE node_id = ?", (target,)
    ).fetchone()
    assert affinity["whisper_log_id"] == held_back_id
```

- [ ] **Step 2: Run it**

```bash
./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py::test_legacy_fallback_on_a_held_back_event_does_not_confirm -v
```

Expected: **PASS** (Task 1 already made it true). If it fails on `held_back_id > injected_id`, the ordering assumption broke — both rows use `datetime('now')` at second resolution, so the tie-break is `wl.id DESC`, which the assertion checks directly. If it fails on the affinity assertion, Task 1 changed more than the claim: stop and re-read the diff.

- [ ] **Step 3: Full suite, for regressions outside this file**

```bash
./.venv/bin/python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: **11 failures**, all from the `~/.config/ormah/.env` leak, with the **same list of test IDs** measured before this branch's commits. Compare the IDs, not the count. Any failure outside that list is a regression from this work.

- [ ] **Step 4: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ tests/
git add tests/test_engine/test_confirmed_use_contract.py
git commit -m "test(lifecycle): pin the legacy fallback's accepted confirmed-use loss"
git show --stat HEAD
```

Expected: `git show --stat HEAD` lists exactly **1 file changed**.

---

## After both tasks

1. Re-invoke `/council-pr` from **inside the worktree** (it runs from `cwd`), as a fresh round 1.
2. Still unauthorised, do not do these without asking: push `fix/220-confirmed-use` to `fork`; open a PR (#229 still declares the `Closes`).
3. Carry into the PR body when it opens: the refutation of Codex finding #2 (the at-most-once contract), so the next human reviewer does not reopen it.

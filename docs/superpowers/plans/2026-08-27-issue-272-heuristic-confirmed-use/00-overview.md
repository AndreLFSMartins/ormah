# Heuristic Confirmed Use Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Each task's implementer receives
> this overview plus their own task file — nothing else.**

**Goal:** Let a heuristic whisper reference reinforce a memory when its evidence is verbatim, so the
detector carrying 81% of positive volume stops being a lifecycle dead end.

**Architecture:** `_claim_confirmed_use` admits `auto_heuristic` gated on an evidence floor of 0.80 —
the `implicit` rung of the #218 ordinal ladder. Verbatim matches (`node_id` 0.98, `title` 0.94,
`sentence` 0.92) clear it; `token_overlap` cannot, its band's supremum being 0.78. The judge's
suppression is re-anchored on *confirmation* rather than any reference, so weak hits keep the only
route that can still confirm them. A boot migration backfills rows the defect already wrote.

**Tech Stack:** Python 3.11+, SQLite, pytest (`asyncio_mode = auto`), ruff (line-length 100).
**Spec:** `docs/superpowers/specs/2026-08-27-issue-272-heuristic-confirmed-use-design.md`

## Global Constraints

- **BASE IS `fix/218-signal-strength-ladder` (`40d8ff0`), NEVER `local-main`.** Measured: `local-main`
  differs by **1581 lines** in `session_watcher.py` and **1557** in `memory_engine.py`, so every
  `local-main` line number is wrong here by construction — the exact mistake that made the first
  attempt at #220 fail. Read addresses with `git show` from the worktree, never from `Tools/ormah`.
- **Worktree:** `../ormah-wt-272`, branch `fix/272-heuristic-confirmed-use`, cut from
  `fix/218-signal-strength-ladder` — *not* `upstream/main`, which has no `src/ormah/signal_strength.py`
  at all (verified: `git cat-file -e upstream/main:src/ormah/signal_strength.py` fails).
  **Never `git checkout` a contribution branch inside `Tools/ormah`** — launchd
  `com.ormah.server.dev` serves that directory.
- **TDD is mandatory:** write the failing test and run it to observe the failure *before* any
  implementation. A test that passes on first run is a plan defect — stop and report it.
- **The baseline of already-failing tests is measured once, in Task 0**, and shared by every later
  task. "Tests pass" means *no test ID outside that baseline fails*. `make lint` before every commit.
- **Never pipe `pytest` straight into `tail`/`tee` and read `$?`.** Council round 3 (Codex) caught
  this: a pipeline's status is the LAST command's, so `pytest ... | tail` reports success while the
  suite fails — which would silently defeat the rule directly above it. Every full-suite run in this
  plan uses:

  ```bash
  python -m pytest tests/ -q > /tmp/ormah-272-run.txt 2>&1; RC=$?
  tail -20 /tmp/ormah-272-run.txt
  echo "pytest exit=$RC"   # must be 0, or the only failures are baseline IDs
  ```
- The floor is `HEURISTIC_CONFIRM_FLOOR = signal_strength.IMPLICIT` (0.80), defined by reference to
  the ladder so the two cannot drift.
- **Never modify `_record_confirmed_use`'s body, and never call it inside an open transaction** — it
  does file I/O and would take `db_lock` before `memory_lock`, inverting every serialized writer's
  order (#220 §4.3).

## Task Order and Dependencies

| Task | File | Deliverable | Depends on |
|---|---|---|---|
| 0 | below | Worktree + measured baseline | — |
| 1 | `01-claim-floor.md` | `_claim_confirmed_use` takes `strength`, gates `auto_heuristic` | 0 |
| 2 | `02-watcher-claim.md` | Heuristic block claims and reinforces | 1 |
| 3 | `03-judge-suppression.md` | Judge suppression re-anchored on confirmation | 2 |
| 4 | `04-backfill.md` | Boot migration backfills historical rows | 1 |

Tasks 1→2→3 are strictly sequential — each consumes the previous signature. Task 4 needs only Task 1
and may run in parallel with 2 and 3.

## Shared Interfaces — defined in Task 1, consumed by Tasks 2, 3 and 4

```python
# src/ormah/engine/memory_engine.py
HEURISTIC_CONFIRM_FLOOR: float  # = signal_strength.IMPLICIT == 0.80

def _claim_confirmed_use(
    self, conn, whisper_log_id: int | None, node_id: str,
    *, signal: int, source: str, strength: float,
) -> bool: ...
```

`strength` is keyword-only and **required** — no default. A default would let a future caller omit it
and inherit a value nobody chose, which is the shape of the bug this issue exists to fix.

## Task 0: Worktree and Baseline

- [ ] **Step 1: Create the island and verify its base**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree add -b fix/272-heuristic-confirmed-use ../ormah-wt-272 fix/218-signal-strength-ladder
cd ../ormah-wt-272
test -f src/ormah/signal_strength.py && echo "BASE OK" || echo "WRONG BASE — STOP"
```

Expected: `BASE OK`. `WRONG BASE` means it was cut from `upstream/main` — remove the worktree and redo.

- [ ] **Step 2: Install and measure the baseline**

```bash
pip install -e ".[dev]" -q
python -m pytest tests/ -q > /tmp/ormah-272-baseline.txt 2>&1; RC=$?
tail -30 /tmp/ormah-272-baseline.txt
echo "pytest exit=$RC"
```

Record the exact failing test IDs — this is the baseline for every later task. A fully green suite
means an empty baseline; record that explicitly.

- [ ] **Step 3: Confirm the two pinning tests are currently GREEN**

```bash
python -m pytest \
  "tests/test_engine/test_confirmed_use_contract.py::test_auto_heuristic_positive_does_not_confirm" \
  "tests/test_background/test_session_watcher.py::test_heuristic_positive_does_not_record_confirmed_use" \
  -v
```

Expected: both PASS — they pin today's exclusion. Task 2 inverts the second; Task 1 keeps the first
passing for a different reason (see `01-claim-floor.md` §"Why contract 9 still passes").

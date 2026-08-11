# ADR-0004 Spool H1 Repair — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task file is self-contained; read this overview plus your task file only.

**Goal:** Make the ingest spool honour H1 — *an outage must never discard real data* — by removing the backoff overflow that strands jobs and the `ENOENT` misclassification that feeds them to it.

**Architecture:** Two independent, small changes inside the existing directory spool. The backoff clamps its exponent before the multiplication, leaving `min()` as the sole authority over the delay. A deleted transcript gets a dedicated `IngestResult` member so the drain can hand it to `requeue` under a deterministic `failure_class`, which the existing dead-letter path already handles. No new machinery, no change to `requeue` itself.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode = auto`), ruff.

**Spec:** `docs/superpowers/specs/2026-08-11-adr-0004-spool-h1-repair-design.md` (commit `fae5344`)

## Tasks

| file | deliverable |
|---|---|
| `01-backoff-overflow.md` | the backoff saturates instead of raising `OverflowError` |
| `02-enoent-misclass.md` | a deleted transcript is dead-lettered, not retried forever |
| `03-verify-and-close.md` | close the spec's open assumption; full suite + lint |

Order matters: 01 before 02. The overflow is what turns the misclassification into a
permanent strand, and fixing it also removes the 60 s re-admission loop with no extra code.

## Global Constraints

- **Worktree:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-h1`, branch `fix/adr4-spool-h1`. Never `git checkout` inside `Tools/ormah` — that working tree is what the running Beta serves (`FORK-WORKFLOW.md` Golden rule 1).
- **The worktree has no `.venv`,** and the main repo's venv has `ormah` installed editable against `/Tools/ormah/src`. Every command sets `PYTHONPATH` to the worktree's `src/` — verified to take precedence over the editable install. Running without it silently tests the *other* checkout, and every result would describe the wrong code.
- **English** for code, comments and commits (CLAUDE.md).
- **Do not touch the re-admission loop** (`session_watcher.py:1419-1420` → `recover` → `pending/`). It is a third-order consequence that disappears with task 01; the ADR explicitly rejects adding machinery for it.
- **Do not modify `requeue`.** It already dead-letters every `failure_class` other than `"external"`.
- **`EIO`/`EACCES` must keep retrying forever.** Only `FileNotFoundError` becomes deterministic.
- **Accepted risk (spec decision D3, council finding 4):** on an acceptance-only root (`discover=False`) the `reconcile` sweep never runs (`session_watcher.py:1571-1572`), so a *false* `ENOENT` there has no self-healing net — the dead-letter is final. This is a conscious trade-off, not an oversight: do not add per-root branching to "fix" it. Codex flagged it `high`; it was weighed and declined.
- **Every piped verification command must preserve pytest's exit status** (`set -o pipefail`). `pytest ... | tail` returns `tail`'s status — this exact mistake reported a green suite during the council Pre-Flight while 7 tests were failing.
- **Do not "fix" markdown lint warnings** (MD032/MD040/MD060) — pre-existing project style, out of scope.
- Do not push this branch to `fork` — it carries `local-main`'s private docs and `.git/hooks/pre-push` is fail-closed against that.

## Shell prefix used by every command in every task

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-h1
export WT=/Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-h1
export PY=/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python
```

## Task 0: Confirm the harness runs against the worktree (do this first, always)

**Files:** none (verification only)

- [ ] **Step 1: Prove which `ormah` the interpreter will import**

```bash
PYTHONPATH=$WT/src $PY -c "import ormah; print(ormah.__file__)"
```

Expected: `/Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-h1/src/ormah/__init__.py`

If it prints the `Tools/ormah` path instead, **stop** — every test result after this point would describe the wrong checkout.

- [ ] **Step 2: Confirm the two contracts this change sits between are green before touching anything**

```bash
PYTHONPATH=$WT/src $PY -m pytest \
  tests/test_background/test_ingest_spool.py::test_requeue_external_retries_forever_with_persisted_growing_backoff \
  tests/test_background/test_ingest_spool.py::test_requeue_deterministic_failure_dead_letters_with_original_bytes -v
```

Expected: `2 passed`. These two pin the contracts on either side of the change; they must stay green throughout.

## After the plan

Integration is **not** part of this plan. Merging `fix/adr4-spool-h1` into `local-main` swaps the code the running Beta serves, so it needs explicit sign-off (`FORK-WORKFLOW.md` Recipe B). The upstream PR for task 02 needs its own branch cut from `upstream/main`, where there is no spool — a different shape, out of scope here.

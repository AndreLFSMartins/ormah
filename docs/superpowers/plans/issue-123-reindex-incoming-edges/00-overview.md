# Issue #123 — reindex must preserve incoming edges — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Each task file is self-contained — give a worker its
> task file plus this overview, nothing else.

**Goal:** Stop the incremental reindex from destroying the edges that point at a node, so the
graph stops silently shrinking between full rebuilds.

**Architecture:** A row in `edges` is owned by the markdown file of its `source` node. The reindex
path is split away from the genuine-removal path (`_clear_derived` vs `_remove_node`) so it never
touches the `nodes` row, and the node write becomes a true upsert so the `ON DELETE CASCADE` never
fires on a node that still exists.

**Tech Stack:** Python >= 3.11, sqlite3 (FK cascade semantics are load-bearing), pytest
(`asyncio_mode = auto`), ruff.

**Spec:** `docs/superpowers/specs/2026-08-21-issue-123-reindex-preserves-incoming-edges-design.md`

## Global Constraints

- **Branch:** clean island `fix/123-reindex-preserves-incoming-edges`, cut from `upstream/main`,
  in its own worktree at `../ormah-wt-123`. FORK-WORKFLOW.md Recipe A. Never work in
  `Tools/ormah` — that tree is what the running Beta serves.
- **Every island needs its own venv.** `python3 -m venv .venv` then
  `env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"`.
- **Import gate before trusting any test number.** The printed path MUST contain `ormah-wt-123/`:
  `env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"`
- **Clean `HOME` for every test run**, and never pipe pytest to `tail` (the exit code becomes
  tail's): `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q
  > out.txt 2>&1; echo "PYTEST_EXIT=$?" >> out.txt`
- **Lint:** `ruff check src/ tests/`, `target-version = py311`, `line-length = 100`.
- **Do not touch** `docs/`, `graphify-out/`, `CLAUDE.md`, `INSTRUCTIONS.md`, `SESSION_LOG.md`,
  `.council/`, `FORK-WORKFLOW.md` on the island — the pre-push hook rejects them, fail-closed.
- **Do not add** `tests/test_proposal_claims_investigation.py` or its three siblings to the island.
  They are untracked one-off investigation files (`.git/info/exclude:53-57`), not part of the suite.
- The island's baseline is the tracked suite only. On `local-main @ 1034bfd` the tracked suite is
  green (2647 passed / 1 failed, the single failure being in one of those excluded files).

## Task sequence

| # | File | Deliverable |
|---|---|---|
| 1 | `01-island-and-red-tests.md` | Island built, import gate proved, **three** failing tests that pin the invariant — one per `_remove_node` call site that matters |
| 2 | `02-non-destructive-reindex.md` | `_clear_derived` + upsert; the three tests go green |
| 3 | `03-guard-tests.md` | Over-correction guard + canonicalisation guard |
| 4 | `04-remove-merge-workaround.md` | A `D -> kept` regression test **first**, then the `memory_engine` hand-restore deleted |
| 5 | `05-verify-and-pr.md` | Full suite, ruff, island cleanliness gate, PR opened |
| 6 | `06-drift-measurement.md` | **No code, no PR.** Three acceptance numbers — **not** a go/no-go |
| 7 | `07-repair-implementation.md` | **Separate PR, gated on the fix being MERGED.** `repair_edges` — recovery without a full rebuild |

Tasks 1-5 are one PR. Task 7 is a second PR and must not be folded into the first: a branch cut from
`upstream/main` carrying the repair without the builder fix repairs a store that is still actively
losing edges.

**Task 7 starts only once the first PR is MERGED into `r-spade/ormah:main`**, proved by
`git merge-base --is-ancestor`, never by a PR being reviewed. Review in the fork does not advance
`upstream/main`. The alternative is an explicitly stacked PR on the fix branch.

Task 6 exists because task 7 has no success criterion without it. It is **not** a gate: it produces
`missing_typed` as the acceptance number and cannot cancel task 7. A measurement of this machine
cannot settle whether `r-spade/ormah:main` needs the repair — the bug has been in `main` since
2026-07-14, and this store is not that store.

## What council round 1 changed

Reviewed 2026-08-21 by Cursor and Codex; both returned `needs-attention`, 10 findings, none
rejected. The mechanism was approved unchanged — the `_clear_derived` / `_remove_node` split, the
`ON CONFLICT(id) DO UPDATE` upsert, `keep_vectors` inverting into `drop_vector`, and slices 1+3 in
one PR. Five things changed:

1. **Task 1 gained a third red test** for `incremental_update`. `_remove_node` has three call
   sites; `index_single` (`builder.py:200`) is not the one the 60 s index updater uses
   (`builder.py:161`). A fix confined to `index_single` passed the original two tests.
2. **Task 4 gained a `D -> kept` test, written before the deletion.** No existing merge test
   builds a third party pointing at the kept node, and `original_edges` only captures edges
   touching the *removed* node — so the old "the merge suite stays green" proof was vacuous.
3. **Task 6 stopped being a go/no-go** and its metric was corrected: it symmetrised the pair and
   ignored `edge_type`, undercounting by 2,182 against the live store.
4. **Task 7's gate became "merged", not "reviewed"**, with the ancestry proved by command.
5. **`repair_edges` gained a partial-failure contract** — `{scanned, inserted, failed}` — and
   tests that pin `node_vectors` and `file_hash` untouched, so a `full_rebuild` in disguise fails.

## Why tasks 2 and 3 are not one task

Task 2 is the behaviour change; task 3 only adds tests that must pass both before and after it
(the removal guard) or that pin a documented consequence (the canonicalisation guard). A reviewer
can reject task 3's framing while accepting task 2's fix. They are separately rejectable, so they
are separate tasks.

## Why the `_clear_derived` split and the upsert are ONE task

Neither alone turns the tests green. Fixing only the explicit `DELETE` and the `DELETE FROM nodes`
leaves `INSERT OR REPLACE INTO nodes` cascading, and the suite stays red. Splitting them would
produce a task whose deliverable is "still broken, trust me" — not independently testable.

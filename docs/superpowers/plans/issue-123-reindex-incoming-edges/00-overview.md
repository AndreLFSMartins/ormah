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
- **Clean, symlink-RESOLVED `HOME` for every test run**, and never pipe pytest to `tail` (the
  exit code becomes tail's). On macOS `mktemp -d` returns a path under `/tmp` or `/var`, both
  symlinks; `test_detect_returns_none_for_home` compares `Path.cwd()` (resolved) against
  `Path.home()` (not resolved) and fails spuriously unless `HOME` is resolved first:

  ```bash
  H=$(mktemp -d); H=$(cd "$H" && pwd -P)
  env -u VIRTUAL_ENV -u PYTHONPATH HOME=$H .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
  echo "PYTEST_EXIT=$?" >> out.txt
  ```
- **Lint:** `ruff check src/ tests/`, `target-version = py311`, `line-length = 100`.
- **Do not touch** `docs/`, `graphify-out/`, `CLAUDE.md`, `INSTRUCTIONS.md`, `SESSION_LOG.md`,
  `.council/`, `FORK-WORKFLOW.md` on the island — the pre-push hook rejects them, fail-closed.
- **Do not add** `tests/test_proposal_claims_investigation.py` or its three siblings to the island.
  They are untracked one-off investigation files (`.git/info/exclude:53-57`), not part of the suite.
- **The island's baseline is NOT zero failures.** Measured on a pristine
  `upstream/main @ 9a7c524` island, before a single line was changed, with the resolved-`HOME`
  recipe above: **3 failed, 1949 passed**. All three are
  `tests/test_setup.py::TestConfigureCodexMcp` and all three are a pre-existing upstream test
  bug, not a #123 regression: the tests patch `ormah.setup.shutil.which`, but
  `configure_codex_mcp` (`setup.py:629`) calls `_find_binary("codex")`, which the patch does not
  intercept. They fail on any machine with the `codex` CLI installed and pass everywhere else.
  **Out of scope for this PR.** Task 5 compares against `3 failed, 1949 passed`, not against zero.
  Re-derive the exact numbers on your own island — do not copy these.

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

## Re-anchored against `upstream/main @ 9a7c524` (2026-08-21)

The plan as council reviewed it was authored by reading **`local-main`**, while its own Global
Constraints require the island to be cut from **`upstream/main`**. The two trees differ by 248
lines in `builder.py`, 224 in `tests/test_index/test_builder.py` and 1030 in `memory_engine.py`,
so every line citation and several code primitives were wrong for the tree the work actually
happens on. Verified against the built island, not inferred:

| The plan assumed (`local-main`) | The island (`upstream/main @ 9a7c524`) |
|---|---|
| append after `test_reindex_preserves_the_edge_reason` (ends `:216`) | that test **does not exist**; `test_builder.py` is 152 lines, 4 tests — append at end of file |
| `Connection(..., reason=...)` | `Connection` has **only** `target`, `edge`, `weight`. No `reason` field, and `_index_file_edges` (`:216-222`) never writes the `edges.reason` column |
| `_remove_node` call sites `:161` / `:176` / `:200` | **`:104`** (`incremental_update`, production) / **`:113`** (genuine removal) / **`:122`** (`index_single`) |
| `index_single` calls `_remove_node(node.id, keep_vectors=unchanged)` | calls `_remove_node(node.id)` — no kwarg, no `unchanged` in scope |
| `nodes` write lists `space_locked`, `archived_at`, `content_fingerprint` | `nodes` has **19 columns**, none of those three (`schema.sql:3-23`) |
| stale comments at `:169-172` and `:204` (`_prior_row`, `pending_removal`) | neither symbol exists on the island — that step is dropped |
| `engine` fixture at `conftest.py:172` | `conftest.py:118` |

**The mechanism survived the re-anchor unchanged.** `_remove_node` (`builder.py:224`) still runs
`DELETE FROM edges WHERE source_id = ? OR target_id = ?` followed by `DELETE FROM nodes`, and
`_index_file_nodes_only` still writes with `INSERT OR REPLACE INTO nodes`. All three destruction
paths, all three call sites, and the `ON DELETE CASCADE` on both `edges` columns
(`schema.sql:26-27`) are identical. Everything council approved about the *design* still holds.

Two consequences for the tests: `reason` is replaced everywhere by `weight` as the
row-identity discriminator (the values were already distinct from the 0.5 default), and task 4's
`created`-preservation assertion carries the "same row, not a rebuilt one" proof on its own.

Because the `content_fingerprint` machinery does not exist on the island, `keep_vectors` inverts
into `drop_vector` with **constant** arguments rather than `not unchanged`: `:104` becomes
`_clear_derived(node.id)` (was `keep_vectors=True`) and `:122` becomes
`_clear_derived(node.id, drop_vector=True)` (was the `keep_vectors=False` default). Both preserve
today's vector behaviour exactly.

## What council round 1 changed

Reviewed 2026-08-21 by Cursor and Codex; both returned `needs-attention`, 10 findings, none
rejected. The mechanism was approved unchanged — the `_clear_derived` / `_remove_node` split, the
`ON CONFLICT(id) DO UPDATE` upsert, `keep_vectors` inverting into `drop_vector`, and slices 1+3 in
one PR. Five things changed:

1. **Task 1 gained a third red test** for `incremental_update`. `_remove_node` has three call
   sites; `index_single` (`builder.py:122` on the island) is not the one the 60 s index updater
   uses (`builder.py:104`). A fix confined to `index_single` passed the original two tests.
   (Council cited these as `:200` and `:161` — `local-main`'s numbering. Same two call sites.)
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

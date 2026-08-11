# Delta-selection for dedup/conflict (#81) — Implementation Plan Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task lives in its own file next to this overview; a subagent gets ONLY its task file plus this overview.

**Goal:** Replace `ORDER BY RANDOM()`/full-scan candidate selection in `duplicate_merger` and `conflict_detector` with incremental seq-watermark selection (the #26 pattern), so maintenance converges on new work.

**Architecture:** New shared `background/watermark.py` (key-parametrized get/set on `meta`). Both finders select seeds `seq > watermark ORDER BY seq ASC LIMIT max_seeds`; vector neighbors stay age-unfiltered. `run_duplicate_detection` drops its inline full-scan loop and consumes `_find_merge_candidates`. Watermarks advance only in `run_*`, to the last contiguous seed prefix with zero LLM failures. Spec: `docs/superpowers/specs/2026-07-15-issue-81-delta-selection-design.md`.

**Tech stack:** Python 3.11+, sqlite, pytest (`asyncio_mode=auto`), fastembed (real embeddings in tests).

---

## Pre-flight (once, before Task 1)

Per FORK-WORKFLOW.md: contribution branch from `upstream/main`, work in an isolated worktree so the Beta clone stays on `local-main`.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add ../ormah-81 -b fix/81-delta-selection upstream/main
cd /Users/andre/Documents/GitHub/Tools/ormah-81
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

All test commands in tasks run from `/Users/andre/Documents/GitHub/Tools/ormah-81` with `.venv/bin/python -m pytest`. When done: push `fix/81-delta-selection` to `fork` (never `upstream`), PR via `/council-pr`.

## Files

| File | Change |
|---|---|
| `src/ormah/background/watermark.py` | Create — `get_watermark(conn, key)`, `set_watermark(engine, key, seq)` |
| `src/ormah/index/builder.py` | `full_rebuild` watermark reset (line 36) extended to the two new keys |
| `src/ormah/config.py` | Add `duplicate_check_max_nodes_per_run=500`, `conflict_check_max_nodes_per_run=500` (next to `auto_link_max_nodes_per_run`, ~line 132) |
| `src/ormah/background/conflict_detector.py` | Finder: opt-in `delta=True` watermark selection (+ scope stamp); run: advance cursor |
| `src/ormah/background/duplicate_merger.py` | Finder: opt-in `delta=True`; run: rewrite onto finder + advance cursor |
| `tests/test_background/test_watermark.py` | Create |
| `tests/test_background/test_conflict_detector.py` | Extend |
| `tests/test_background/test_duplicate_merger.py` | Extend |

Not touched: `auto_linker.py` (avoids conflicts with queued PRs #119/#127), `memory_engine.py` (agent-path call sites keep positional `limit` AND legacy random selection — see invariants).

## Tasks

1. `01-watermark-module.md` — shared watermark module (TDD)
2. `02-conflict-finder-delta.md` — delta-selection in `_find_conflict_candidates`
3. `03-conflict-run-advance.md` — cursor advance in `run_conflict_detection`
4. `04-dedup-finder-delta.md` — delta-selection in `_find_merge_candidates`
5. `05-dedup-run-rewrite.md` — `run_duplicate_detection` onto the finder + advance

## Load-bearing invariants (every task must preserve)

- **Neighbors are age-unfiltered.** Only SEED selection is delta'd; `vec_store.search` results are never filtered by seq. New×old pairs must keep working.
- **Watermark advances only past drained seeds.** A seed is "drained" when its neighbor loop completed and none of its LLM checks returned `None`. Seeds with zero candidates (all prefiltered) are drained — they must not block the cursor.
- **A vectorless seed is a fail-closed BARRIER (`break`, not skip).** A seed with non-empty text whose vector is not persisted (`vec_store.get(id) is None`) must STOP the finder's seed loop with `break` in delta mode — not `continue`. An empty/backfilling `node_vectors` table (real window — `full_rebuild` wipes it and embedding backfill is async) would return zero neighbors; if the loop merely skipped the seed and kept going, a later drained seed would advance the watermark PAST the hole and the skipped seed's pairs would never be re-derived. `break` makes `drained_seeds` a contiguous prefix by construction, so the advance loop cannot jump a hole. Mirrors the auto_linker's upstream barrier contract (auto_linker.py:344-354, `test_empty_vector_index_does_not_advance_watermark`). Run-level regression: `test_{conflict,dedup}_run_vectorless_seed_blocks_watermark`.
- **Advance is a contiguous prefix in seq order.** First failed/undrained seed stops the cursor; later seeds are still processed in the same run but not passed.
- **Delta is opt-in: `delta=False` (default) keeps TODAY's selection byte-for-byte.** The agent/two-call path (memory_engine.py:1677-1679, positional `limit`) stays on legacy random selection and never advances any watermark. This is load-bearing: with the upstream default `llm_provider="none"` the `run_*` jobs never execute, so a watermark the agent path cannot advance would strand agent-driven deployments on the same oldest seed batch forever. Only the background `run_*` jobs pass `delta=True`.
- **Auto-merge requeues the survivor.** When a pair's node was merged away mid-run, the survivor's content rewrite allocates a fresh `seq` (upstream builder contract, see `test_seq_bumped_on_rewrite`), so it re-enters the delta next run; skipping its stale pairs does not lose work and the seed stays drained.
- **`full_rebuild` resets ALL incremental watermarks.** Upstream already resets `auto_link_watermark` (builder.py:36) because mass reindex re-allocates `seq`; the two new keys must join that DELETE or a rebuilt store sits entirely behind stale cursors.
- **Scope toggle resets the conflict cursor.** The conflict watermark is stamped with the `conflict_check_all_spaces` value it was advanced under; a mismatch on read treats the watermark as 0 (project-space nodes ingested while the flag was off become reachable when it turns on).
- **Full content to the LLM in the dedup run.** Finder `_nd` dicts truncate content to 400 chars; `run_duplicate_detection` re-fetches full rows by id before `_llm_check_duplicate`, or auto-merge would generate `merged_content` from truncated text (data loss).
- **Existing prefilters intact:** `auto_link_checked` skip, sim thresholds (0.25/0.4), same-type (dedup), `_BELIEF_TYPES` + space gate (conflict), contradicts/evolved_from edge skip (conflict), composite threshold (dedup), user-node exclusion.

## Verification (after Task 5)

```bash
.venv/bin/python -m pytest tests/test_background/ -v      # all green
.venv/bin/ruff check src/ tests/                          # clean
.venv/bin/python -m pytest tests/ -q                      # full suite, no regressions
```

Cite outputs in the completion report.

## Known limitations (documented in the PR body, out of scope)

- Deterministically failing seed parks the cursor — upstream #122.
- Pending-proposal skip semantics change (council-confirmed, deferred by design): the run suppresses creating a merge proposal for a pair when EITHER node already sits in ANY pending merge proposal — including an unrelated proposal for a different pair, and pairs within the same run that share a node with an earlier proposal. This OR-match is intentional upstream behavior (one pending proposal per node at a time; overlapping proposals would collide on execute_merge) and is kept verbatim. What #81 changes is the RECOVERY path: pre-#81 the full random re-scan eventually re-judged a suppressed pair, so a later-rejected proposal self-healed; under the watermark the seed drains and the cursor passes it, so a suppressed pair whose blocking proposal is later rejected stays unjudged until either node's content changes (seq bump). Proper fix is a separate feature — proposal rejection should requeue the affected pairs (bump seq or a dead-letter requeue) — out of scope for #81's selection change.
- N+1 re-fetch in the dedup run (minor, accepted): the data-loss guard re-fetches both full node rows per candidate (up to 2 SELECTs × the pair budget). Bounded and on a background job; a per-run `{id: row}` cache is a cheap future optimization, not needed for correctness.
- Embedding-corpus reindex does not reset the cursors (pre-existing #26 gap, shared with auto_linker — NEW upstream issue, not fixed here): `_reindex_all_embeddings` (memory_engine.py, fired on an embedding schema-version bump) replaces every vector WITHOUT bumping `seq` or clearing any watermark. `full_rebuild` clears all incremental cursors (this PR extended it); `_reindex_all_embeddings` does not — and neither does it for the pre-existing `auto_link_watermark`. So after a model/schema embedding upgrade, already-drained nodes are not re-examined with the new embeddings by ANY of the three jobs. A correct fix must distinguish a schema/model change (should reset) from a missing-vector backfill (should not — same embeddings restored) to avoid amplifying #32's full-re-embed cost, and it touches the embedding pipeline + auto_linker — cross-cutting, out of #81's selection scope. NOTE: a content EDIT is NOT affected — `update_node` re-embeds (`_index_embedding`) and bumps `seq`, so edited nodes re-enter the delta with a fresh vector.
- Permanent vectorless barrier replays paid LLM work until the node embeds (#122 territory): once a seed hits a permanent vectorless barrier, every run re-processes the later seeds in that batch (they never drain, so the cursor parks) and re-sends their pairs to the LLM. This is exactly auto_linker's fail-closed behavior (it too re-processes later nodes each run on a permanent barrier). Background dedup makes the replay slightly costlier than auto_linker because it deliberately ignores `auto_link_checked` (correct — that is auto_linker's table) and upstream has no dedup-verdict skip table (`duplicate_checked` is PR #79, not in this base). Transient embedding failures self-heal in one backfill cycle; a PERMANENTLY unembeddable node is the deadlock — bounded-retry / dead-letter quarantine is upstream #122. A once-per-run WARNING now logs when a barrier parks the cursor (observability).
- LLM judgment content ceiling: `_llm_check_duplicate` truncates content at 2000 chars (pre-existing upstream behavior, unchanged here). The Task 5 guard restores parity with today's run — it prevents the 400-char finder-preview REGRESSION, it does not widen the pre-existing 2000 ceiling.

## Reconciliation note (#95 / judge_pairs)

Open PR #95 introduces `judge_pairs` batching + pair-denominated caps in these same run loops. This plan is based on pure `upstream/main` (verified 2026-07-15 @ 4f66abc: no `pair_batch.py`, per-pair `_llm_check_*` calls, no `*_pairs_per_*` settings). Whichever lands second re-expresses the other: if #95 lands first, Tasks 3/5's advance logic moves to AFTER the candidates/verdicts zip (a `None` verdict marks its `seed_seq` failed) and the K-window flush replaces the linear loop. The same applies to the Recipe-B merge into `local-main`, which already carries #95.

**MANDATORY pre-flight for Tasks 3 and 5** (base may have moved since this plan was written): run `grep -l judge_pairs src/ormah/background/conflict_detector.py src/ormah/background/duplicate_merger.py` in the worktree. Empty output → the Steps 3 apply as written. Any hit → #95 landed first: STOP and re-express the task per this note (advance after the zip, keep `settings.*_max_pairs_per_run`, keep the K-window) before writing code.

# Delta-selection for duplicate_merger + conflict_detector (upstream #81)

**Date:** 2026-07-15
**Issue:** https://github.com/r-spade/ormah/issues/81
**Branch:** `fix/81-delta-selection` — cut from `upstream/main` (per FORK-WORKFLOW.md), pushed to `fork`.
**PR base state (verified on `upstream/main` @ 4f66abc):**

- `run_duplicate_detection` (duplicate_merger.py:240) scans **all** nodes with a plain
  `SELECT` (not even RANDOM), no persisted skip, no LLM-call cap — it re-judges the same
  high-scoring pairs via LLM on every run.
- `_find_merge_candidates` (duplicate_merger.py:135) is a **separate** loop:
  `ORDER BY RANDOM()` over the whole table, skips pairs present in `auto_link_checked`,
  used by the agent/two-call maintenance path (`memory_engine.py:1669-1679`).
- `run_conflict_detection` (conflict_detector.py:215) routes through
  `_find_conflict_candidates(limit=10000)` — `ORDER BY RANDOM()` over all belief-type
  nodes, `auto_link_checked` skip.
- `auto_linker` already has the fix pattern (#26): `seq` watermark in `meta`
  (`auto_link_watermark`), `seq > watermark ORDER BY seq ASC LIMIT batch`.
- `duplicate_checked` / `conflict_checked` tables and per-run LLM caps do **not** exist
  on upstream/main — they live in still-open PR #79. This spec does not depend on them.

## Problem

Random (or full-scan) candidate selection never converges on a growing store: a
genuinely-new duplicate/conflict waits until chance surfaces its node, which gets less
likely as n grows. Measured on the production store (issue comment, 2026-07-09):
9,453 of 10,287 nodes never appeared in any checked pair despite every run burning its
full budget.

## Decisions (made with André, 2026-07-15)

1. **Base = pure `upstream/main`.** Self-contained diff, independently mergeable.
   Textual conflict with open PRs #79/#95 is accepted: whoever lands last rebases.
2. **Unify dedup selection in the finder.** `run_duplicate_detection` drops its inline
   full-scan loop and consumes `_find_merge_candidates` — one selection path per job,
   mirroring the conflict job's architecture.
3. **Pure watermark from 0.** No random fallback, no fingerprint requeue. Watermark
   absent = 0 = the first runs perform an ordered catch-up walk (every existing node
   becomes a seed exactly once), then steady-state O(Δ) per run.

## Design

### New module: `src/ormah/background/watermark.py`

```python
def get_watermark(conn, key: str) -> int   # meta[key] or 0
def set_watermark(engine, key: str, seq: int) -> None
```

Parametrized generalization of auto_linker's private trio. New `meta` keys:
`duplicate_check_watermark`, `conflict_check_watermark`. The auto_linker is **not
touched** (avoids conflicts with queued PRs #119/#127); migrating it to this module is
a follow-up.

### Seed selection (both finders)

Replace the full-table fetch with:

```sql
WHERE seq > :watermark [+ existing type/space filters]
ORDER BY seq ASC LIMIT :max_nodes_per_run
```

- Seeds are delta-selected; **vector neighbors stay age-unfiltered** — a new node pairs
  against neighbors of any age, so every new duplicate/conflict (which necessarily
  involves ≥1 new node) is reachable. This resolves the new×old nuance from the issue.
- Each returned candidate carries its seed's `seq` (`seed_seq`) so consumers can
  advance the cursor correctly.
- All existing prefilters are preserved unchanged: `auto_link_checked` skip, similarity
  thresholds (0.25 dedup / 0.4 conflict), same-type (dedup), belief-types + space
  (conflict), existing contradicts/evolved_from edge skip (conflict), composite score
  threshold (dedup), user-node exclusion.

### `run_duplicate_detection` rewrite

Consumes `_find_merge_candidates` instead of its own loop; keeps the LLM confirmation,
auto-merge path, proposal dedup and creation exactly as today. **Declared behavior
change** (called out in the PR): the run now honors the `auto_link_checked` skip and a
per-run seed bound, which the inline loop lacked — strictly less wasted LLM work.

Finder contract: `limit` stays pair-denominated (agent path passes small values,
unchanged call sites); a new keyword-only `max_seeds: int | None = None` bounds the
seed selection, defaulting to the job's `*_max_nodes_per_run` setting when `None`.
The run path relies on the seed bound and passes a non-binding pair limit
(`limit=10_000`, matching today's conflict run).

### Watermark advance

Only the background `run_*` functions advance the cursor; the agent/two-call path reads
the same delta but never advances (exact mirror of auto_linker today — documented
follow-up: agent-path advance on `apply`).

Semantics: seeds are processed in `seq` order. The watermark advances to the last seed
of the **contiguous prefix with zero LLM failures** (an `_llm_check_*` returning `None`
marks its seed failed). Later seeds are still processed in the same run, but the cursor
stops at the first failed seed so the next run retries it. Known ceiling: a
deterministically failing seed parks the cursor — that is upstream #122, marked with a
`ponytail:` comment referencing it, not solved here.

### Config

Two new settings, mirroring `auto_link_max_nodes_per_run`:

```python
duplicate_check_max_nodes_per_run: int = 500
conflict_check_max_nodes_per_run: int = 500
```

No LLM-call cap: per-run work is bounded by seeds (≤6 / ≤15 vector neighbors each, LLM
invoked only for pairs passing prefilters). Pair-denominated caps are #87's scope.

### Migration

None. Missing watermark = 0 = ordered catch-up walk, which is the desired behavior.

## Tests (TDD)

- **watermark.py**: default 0; get/set roundtrip; keys independent of each other and of
  `auto_link_watermark`.
- **Finders**: only `seq > watermark` nodes become seeds; a new-seed × old-neighbor pair
  is found; `seq ASC` order; `LIMIT` respected; existing prefilters preserved (type,
  space, skip table, thresholds).
- **run_duplicate_detection**: a pair whose seed is below the watermark is NOT re-judged
  (reproduces the issue); a delta pair produces a proposal; the run routes through the
  finder (full scan gone).
- **Advance**: clean run → watermark = last seed's seq; LLM failure on a middle seed →
  watermark stops before it and the next run re-selects it.
- **Agent path**: finder with a small pair `limit` works and does not move the cursor.

## Risks / out of scope

- Textual conflicts with open PRs #79 (skip tables) and #95 (pair batching) — accepted;
  rebase burden falls on whichever lands last.
- Merging into `local-main` (Beta, Recipe B) will conflict with #79/#95 content already
  merged there — manual reconciliation in these two files is expected.
- Agent-driven deployments see the same delta until a background run advances the
  cursor — inherited from auto_linker semantics; follow-up candidate upstream.
- Out of scope: #87 (pair-denominated caps), #79 (persisted skip tables), #122
  (poison-seed dead-letter), auto_linker migration to the shared watermark module.

# Issue #259 — Claude-in-the-loop consolidation must summarize from full content

- **Date:** 2026-08-26
- **Issue:** [r-spade/ormah#259](https://github.com/r-spade/ormah/issues/259)
- **Branch:** `fix/259-maintenance-full-content` (island cut from `upstream/main` @ `90c431e`)
- **Worktree:** `Tools/ormah-wt-259`

## Problem

`MemoryEngine.get_maintenance_batches` (phase 1 of the `run_maintenance` two-call protocol)
normalizes every candidate node through a single `_norm` helper that truncates content to its
first 400 characters (`src/ormah/engine/memory_engine.py:1828`). All four batches share it:
link, conflict, merge — and consolidation.

Phase 2, `apply_maintenance_results` (`memory_engine.py:1902`), feeds the agent's consolidations
to the same `_apply_consolidation` the background consolidator uses, which **demotes the sources
to `archival`**. The result is the #192 defect on a second route: a summary written from a
400-character view of each source, after which the full sources leave the whisper pool. The
model cannot preserve what it was never shown, and the output carries no scar — the summary
reads as complete.

Truncation is correct for the other three batches: link, conflict and merge are *screening*
views, where the agent decides whether a pair is worth acting on and the full text is not the
subject of the decision.

### Second defect, found while reading the code (not in the issue)

`_find_consolidation_clusters` selects `id, title, content, space`
(`src/ormah/background/consolidator.py:40`, and the by-id re-read at `:78`) — **no `type`**.
The other three candidate finders do select it (`conflict_detector.py:123`,
`duplicate_merger.py:155`). Because `_norm` reads `node.get("type", "")`, every consolidation
cluster node reaches the agent with `"type": ""`, while phase 2 asks the agent for a `type`
back (`c.get("type", "fact")`, `memory_engine.py:1912`). The agent picks the consolidated
node's type without seeing the type of a single source.

Verified by execution, not by reading — a probe against the island's own venv:

```
CLUSTERS: 1
KEYS: ['content', 'id', 'space', 'title']
```

Same family of defect as the main one ("the model cannot preserve what it was never shown"),
on a different field, in a query this change already touches. Included deliberately.

## Decisions

### No content cap on the consolidation batch

Full content, no budget, no splitting. The batch is bounded at **4 clusters x 5 nodes = 20
nodes** (`consolidation_max_cluster_nodes: int = 5`, `config.py:288`), and the consumer is the
Claude maintenance agent, whose window is orders of magnitude larger than any cluster. Unlike
#192 — where the prompt goes through a provider window we must size and request (`num_ctx` for
Ollama) — there is no window of ours to manage here, so any cap would reintroduce the same
defect at a smaller scale: a summary from a partial view, sources archived all the same.

Accepted trade-off: `content` has no length limit in the model, so an abnormally large node
produces a large `job.batches` payload in memory and over the status response. The cost of
being wrong is latency and response size, not data loss — the inverse of the current cost.

### `type` fix included in the same change

One column in a SELECT, same defect shape, in code this PR already touches logically. Splitting
it would mean a second issue for a single word. Accepted trade-off: the diff is slightly wider
than issue #259 literally describes.

## Design

### Change (a) — explicit content limit on `_norm`

`src/ormah/engine/memory_engine.py`:

```python
def _norm(node: dict, content_limit: int | None = 400) -> dict:
    content = node.get("content") or ""
    return {
        "id": node.get("id", ""),
        "title": node.get("title", ""),
        "type": node.get("type", ""),
        "space": node.get("space", ""),
        "content": content if content_limit is None else content[:content_limit],
    }
```

The three screening batches keep calling `_norm(...)` with no argument — unchanged behaviour.
Only the consolidation batch passes `content_limit=None`.

A parameter rather than two separate helpers: one place keeps defining which fields a
normalized node has, and the default preserves screening without touching existing call sites.

### Change (b) — `type` in the cluster SELECT

`src/ormah/background/consolidator.py`, lines 40 and 78: add `type` to the selected columns.
Purely additive — `run_consolidation` builds its prompt from `title`/`content` and never
iterates the dict keys, so an extra key changes nothing on that route (inferred by reading;
confirmed by running the consolidator suite).

### Out of scope

`apply_maintenance_results`, `_apply_consolidation`, the MCP schema, and every settings default
stay untouched.

## Testing

Four tests, all red before the fix. None uses `if result:` or "completes without error" — each
fails explicitly when its fixture produces no data, so none can pass vacuously.

Cluster formation is made deterministic with `consolidation_cluster_threshold = 0.0` and
`consolidation_min_cluster_size = 2`, which the probe above proved sufficient with two similar
nodes. Tests use real fastembed embeddings (~13s with the model cached).

1. **`test_consolidation_cluster_carries_full_content`** (`tests/test_background/test_run_maintenance.py`)
   Seed two 600-char nodes, call `get_maintenance_batches()`, assert the consolidation batch is
   non-empty and each node's content is 600 chars and equal to the original.
   *Catches the target bug:* today `_norm` cuts at 400, so `400 != 600` fails.

2. **`test_screening_batches_still_truncate`** (same file)
   Same 600-char nodes, `auto_link_similarity_threshold = 0.0`; assert `link_candidates` is
   non-empty and each content equals `original[:400]`.
   *Guards against the over-fix* — removing the limit from all four batches. Green today, must
   stay green. The existing `test_content_truncated_to_400` iterates a possibly-empty list and
   would pass without checking anything; this one asserts non-empty first.

3. **`test_clusters_carry_node_type`** (`tests/test_background/test_consolidator.py`)
   Call `_find_consolidation_clusters` directly; assert non-empty and `node["type"] == "fact"`
   for every node.
   *Catches defect (b) at its cause:* the key does not exist today.

4. **`test_consolidation_cluster_carries_type`** (`test_run_maintenance.py`)
   End-to-end: `batches["consolidation_clusters"][0][0]["type"] == "fact"`.
   *Catches defect (b) at its observable effect:* `_norm` returns `""` today.

Tests 3 and 4 are the same isolated-cause plus observable-effect pair used in #261.

## Verification gates (FORK-WORKFLOW.md)

- **Import gate** — already run for this island and verified:
  `.venv/bin/python -c "import ormah; print(ormah.__file__)"` prints
  `/Users/andre/Documents/GitHub/Tools/ormah-wt-259/src/ormah/__init__.py`.
- **Test runs** — `env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest`,
  redirected to a file with `PYTEST_EXIT=$?` appended (never piped to `tail`).
- **Island gate** — `git log --oneline upstream/main..HEAD` must show only this change's commits.
- **Spec location** — this document lives on `local-main`, not on the island: `docs/superpowers/`
  is in the pre-push `PROTECTED` allowlist and would block the contribution branch's push.

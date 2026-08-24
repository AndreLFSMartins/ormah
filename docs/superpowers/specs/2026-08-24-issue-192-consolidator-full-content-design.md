# Design: consolidator must see full source content (#192)

**Issue:** #192 — `bug(background): consolidator summarizes from content[:300]`
**Date:** 2026-08-24
**Status:** approved, ready for planning

## Problem

`_consolidate_cluster` (`src/ormah/background/consolidator.py`) truncates every source memory to
its first 300 characters before showing it to the LLM, then instructs that LLM to "preserve every
concrete detail" and produce output that "becomes the PRIMARY representation of this knowledge".
`_apply_consolidation` then demotes every source to `archival` and marks it `superseded_by`, so the
content the model never saw is displaced from the whisper pool by a summary written without it.

Measured on a live 1,843-node store with 130 consolidation events: 254 of 297 consolidated
originals (85.5%) were longer than 300 chars; 110,519 characters were never shown to the model;
the worst single source had 96% of its content withheld.

After #223 this stops being symmetrical. Archival nodes return to `working` on confirmed use —
except nodes carrying `superseded_by`, which the consolidator writes onto exactly these sources.
A bad consolidation becomes the one lifecycle decision the system will not walk back on its own.

## The second truncation (found while designing this fix)

Removing the `[:300]` alone is not sufficient, and for one provider it is a regression.

The consolidator generates through `llm_generate` → `_get_or_create_adapter` →
`get_adapter(settings)` **without `num_ctx`**. For `llm_provider=ollama` that omission is
deliberate (`llm/__init__.py`, `ollama_adapter.py`): it leaves the input window to the operator's
server/Modelfile, because the shared maintenance adapter also serves `auto_linker`,
`conflict_detector`, `duplicate_merger` and the feedback judge, and pinning the ingest window
(65536) there would give all of them a large KV cache.

With `[:300]` × 5 nodes the prompt is ~3,700 chars (~950 tokens) and fits any default window.
Without it, the measured worst case (5 × ~8,000 chars ≈ 40,000 chars ≈ 10k tokens) overflows a
default Ollama window and is truncated **by the server**, silently — the same bug one level down,
now invisible to our code. A generous cap without a matching window makes ollama operators
strictly worse off than today.

## Invariant

> The consolidation prompt contains the **complete** content of every source it summarizes.

When a cluster does not fit, it is **split**, never truncated. Nodes that cannot participate stay
`working` and untouched — they lose consolidation, not memory.

## Design

### 1. `config.py` — one new setting

```python
consolidation_max_prompt_chars: int = 40000   # ~20k tokens; 5 sources of 8k chars with headroom
```

Validator: `>= 4000`. Below that the template's own 2,440-char overhead leaves no room for two
useful sources. This single number governs **both** the split budget and the input window
requested from Ollama — a budget the provider never promised to honor is fiction.

### 2. `consolidator.py` — template as a constant, split as a pure function

- The inline f-string becomes a module constant `_CONSOLIDATE_PROMPT` with a `{items_text}` slot.
  `_prompt_overhead_chars()` returns `len(_CONSOLIDATE_PROMPT.format(items_text=""))` — computed
  from the template itself, mirroring `ingest_capacity.prompt_overhead_chars()` and for the same
  reason: a hardcoded number goes stale on the first prompt edit. Measured today: 2,440 chars.
- `_split_cluster_to_fit(cluster, budget_chars) -> list[list[dict]]` — greedy packing in the
  similarity order `_find_consolidation_clusters` already produces (seed first, then descending
  similarity). Per-item cost is `len(f"- [{title}]: {content}\n")`: exactly what the prompt spends.
- `_consolidate_cluster` drops the `[:300]` and emits an INFO log carrying `new_id`, source ids,
  `source_chars` and `summary_chars`, so a lossy event is detectable after the fact (issue option 3,
  log form).
- `_apply_consolidation` is unchanged. Archival demotion and the `superseded_by` marker (#223) stay
  as they are: #192 is about what the LLM sees, not about what happens afterwards.

### 3. `llm_client.py` + `llm/__init__.py` — a dedicated route

`consolidation_llm_generate(settings, prompt, ...)` mirrors `ingest_llm_generate` in shape and
keeps the maintenance contract (cancel/timeout swallowed to `None`). It uses a third cached
adapter built with:

```python
num_ctx = estimated_tokens(consolidation_max_prompt_chars) + llm_num_predict
```

`estimated_tokens` is reused from `ingest_capacity.py` despite the ingest-flavored module name:
it is the repo's single chars→tokens heuristic, its only dependency is the leaf `ingest_prompt`,
and duplicating the constant would let the two estimates drift. If a second consumer makes the
name actively misleading, renaming the module is a separate mechanical change.

`workspace` stays at its `"judge"` default — it only selects the `cwd` of the `claude_cli`
subprocess, so a new workspace would be surface without gain.

The shared maintenance adapter keeps `num_ctx=None`. Only the route that needs the large window
asks for it, and it runs once a day (`consolidation_interval_minutes=1440`). Cost: Ollama reloads
the model when the consolidator runs.

### 4. `consolidation_max_clusters_per_run` now counts sub-clusters

The split can turn 10 clusters into ~25 LLM calls in a daily job — a silent 2.5× cost increase for
`claude_cli`/`litellm` operators. The setting exists to bound cost, so it bounds what costs.
Sub-clusters beyond the cap are not touched and record no signature; they return next run.

**Discovery is unchanged.** `_find_consolidation_clusters(engine, limit=...)` keeps receiving
`consolidation_max_clusters_per_run` and keeps stopping there; the same number then truncates the
post-split queue. The cap is therefore a ceiling on LLM calls, never a floor: a run that splits
heavily consolidates fewer raw clusters than before, and the remainder returns next run. Raising
discovery to compensate is a separate change and is not made here.

**Stats keys.** `run_consolidation` returns `clusters_found` (raw, unchanged meaning) plus
`subclusters_queued`, `subclusters_consolidated` and `nodes_skipped_oversized`.
`clusters_consolidated` keeps its name and now counts consolidated sub-clusters — it is the same
quantity operators already read as "how many LLM consolidations happened this run".

## Flow

```
run_consolidation
  └─ _find_consolidation_clusters()            → raw clusters (≤ consolidation_max_cluster_nodes)
     └─ per cluster: _split_cluster_to_fit(budget − overhead)
        ├─ sub-cluster ≥ consolidation_min_cluster_size → queued
        ├─ sub-cluster of 1 node                        → dropped (node stays working)
        └─ node larger than the whole budget            → WARNING(id, chars), stays working
     └─ queue truncated at consolidation_max_clusters_per_run
        └─ _consolidate_cluster(sub) each              → FULL content in the prompt
```

Signatures are computed per sub-cluster over the nodes that actually reached the prompt, so
`_cluster_signature`'s self-invalidating property survives: editing any source changes its
sub-cluster's signature.

## Edge cases

| Situation | Behavior | Rationale |
|---|---|---|
| Cluster fits whole | one sub-cluster identical to input | common path; only the content changes |
| 5 large nodes | 2–3 sub-clusters, similarity order preserved | most-similar stay together in the first |
| Sub-cluster of 1 | dropped, node stays `working` | `min_cluster_size=2`: nothing to consolidate |
| Node exceeds whole budget | `WARNING(id, chars)`, never enters a sub-cluster | never summarize from a partial view |
| `budget − overhead <= 0` | one `WARNING`, nothing consolidated | loud failure, not a silent no-op |
| Queue exceeds the cap | excess untouched, no signature recorded | the cap bounds cost, not work |
| LLM unavailable / bad JSON | unchanged (no signature, retry next run) | out of scope for #192 |

## Convergence

Two sub-clusters of the same cluster produce two semantically close consolidated nodes, which may
cluster again next run. That is already the current behavior (a consolidated node is born
`working`) and it converges: if the two together do not fit, the split reproduces 1+1 and nothing
happens. Stable, not a loop.

## Tests

**The issue's regression test** — the one that would have caught the bug:

- `test_full_source_content_reaches_the_prompt` — a source with a marker beyond char 300 (and
  beyond char 5000); assert the marker appears in the prompt captured from the LLM call. A
  reintroduced `[:300]` fails here.

**Split (pure unit, no LLM):**
- fits → one partition equal to the input
- does not fit → N partitions; union == input minus oversized; no duplicates; order preserved
- oversized node → absent from every partition
- partition of one → dropped

**Integration via `run_consolidation` (with `mock_llm`):**
- 5 large nodes → 2 consolidated nodes created; all 5 originals `archival`
- oversized node → stays `working`, no `superseded_by`, no `derived_from` edge
- queue > cap → exactly `cap` consolidations; the excess sub-clusters' nodes stay `working` with no
  signature recorded

**Adapter route:**
- `consolidation_llm_generate` with `llm_provider=ollama` builds an `OllamaAdapter` whose
  `num_ctx == estimated_tokens(budget) + llm_num_predict`
- the shared maintenance adapter still has `num_ctx is None` (KV-cache non-regression)

**Config:** default, env override, validator rejects `< 4000`.

**Log:** the INFO carries `source_chars` and `summary_chars`.

## Out of scope (follow-ups to open)

- Persistent `consolidation_events` audit table (issue option 3, table form).
- Consolidation fidelity eval — `eval/` covers `recall` and `whisper` only; #192 flags this as
  "worth a separate issue".
- Aligning the ingest `ollama_num_ctx` with the new setting: they are not the same window and
  should not be.

## Contribution workflow

This ships upstream as a clean island (`FORK-WORKFLOW.md` Recipe A): branch cut from
`upstream/main` in its own worktree, its own venv, import gate proven before quoting any test
number. This spec lives on `local-main` only — `docs/` is in the pre-push `PROTECTED` allowlist.

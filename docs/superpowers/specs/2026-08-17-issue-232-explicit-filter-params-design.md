# Issue #232 — Explicit filter parameters on the recall boundary

**Date:** 2026-08-17
**Issue:** [#232](https://github.com/r-spade/ormah/issues/232) — `recall_search_structured`: unknown
filter keys crash on hybrid search but are silently dropped on the FTS fallback
**Sibling issue (out of scope):** [#233](https://github.com/r-spade/ormah/issues/233) — known
`types`/`tiers`/`tags` filters silently ignored on the FTS fallback

## Problem

`MemoryEngine.recall_search_structured` collects its search filters into an untyped `**filters`
bag. No layer validates the key names, and the two search backends disagree about an unknown one:

- **Hybrid path** — `filters` is forwarded verbatim to `HybridSearch.search`
  (`src/ormah/engine/memory_engine.py:973-978`), which declares fixed named parameters and no
  `**kwargs` (`src/ormah/embeddings/hybrid_search.py:85-96`). An unknown key raises `TypeError`.
- **FTS fallback path** — `filters` is never forwarded. It is read key by key via `.get()` for the
  keys that path knows about (`src/ormah/engine/memory_engine.py:1023-1034`). An unknown key is
  silently dropped and the search returns unfiltered results.

So a mistyped filter name (`tierz=` for `tiers=`) either crashes or quietly widens the result set,
depending on whether the embeddings extra is installed in that environment. The silent mode is the
dangerous one: nothing in the return value distinguishes "filter not applied" from "filter matched
broadly".

`MemoryEngine.recall_search` (`src/ormah/engine/memory_engine.py:1070`) carries the **identical**
defect — `search.search(query, limit=limit * 3, **filters)` on the hybrid path
(`memory_engine.py:1102`) against the same key-by-key `.get()` fallback
(`memory_engine.py:1143-1156`). The issue does not name it; this design covers both, because
fixing one boundary and leaving the other leaves two contradictory contracts on the same class.

## Severity: the typo is latent, not active

Verified: **no external input chooses filter key names.**

- The HTTP surface passes an explicit, Pydantic-validated key set
  (`src/ormah/api/routes_agent.py:65-75`); MCP reaches the engine through that same surface.
- `src/ormah/api/routes_ui.py:111` passes only `q` and `limit`.
- The one dynamic path is `search_kwargs.update(intent.search_params)`
  (`src/ormah/engine/context_builder.py:534`). `search_params` is produced only by
  `extract_time_params`, whose four return paths all return exactly `created_after` and
  `created_before` (`src/ormah/engine/prompt_classifier.py:172-222`), plus a `search_query` key
  that `context_builder.py:533` pops before the merge.

No live typo exists today. The defect is that the boundary accepts anything, so the next filter
key added to `intent.search_params` — or the next hand-written call — lands in a coin flip between
crash and silence. This is a latent-defect fix, not an incident fix.

## Approach

Remove the bag rather than police it. The accepted key set at this boundary is already fixed and
knowable — it *is* the signature of `HybridSearch.search`, minus `query_vec`, and it is the same
set `_supplement_temporal` reads (`memory_engine.py:2602-2604`). Declaring those six keys as
explicit keyword-only parameters makes the interpreter itself the validator, at the function
header, before any branching.

Two alternatives were considered and rejected:

- **An allowlist `frozenset` validated at the top of both functions.** Smallest diff, but it
  recreates the accepted key set in a second location that can drift from the real signature —
  precisely the failure mode that produced this bug.
- **A private `_normalize_filters` helper both functions funnel through.** Keeps the untyped bag on
  the public boundary, so a type checker stays blind, and adds an abstraction with two callers.

## Design

### Signatures

`recall_search_structured` — the `*` already sits after `default_space` (issue #220), so the three
existing positional slots are untouched:

```python
def recall_search_structured(
    self, query: str, limit: int = 10, default_space: str | None = None,
    *,
    types: list[str] | None = None,
    tiers: list[str] | None = None,
    spaces: list[str] | None = None,
    tags: list[str] | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    min_relevance: float | None = None,
    auto_temporal: bool = True, spread_activation: bool = True,
    query_vec: Any | None = None,
) -> list[dict]:
```

`recall_search` — the `*` goes after `session_id`, preserving its four existing positional slots:

```python
def recall_search(
    self,
    query: str,
    limit: int = 10,
    default_space: str | None = None,
    session_id: str | None = None,
    *,
    types: list[str] | None = None,
    tiers: list[str] | None = None,
    spaces: list[str] | None = None,
    tags: list[str] | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> str:
```

The asymmetry in where `*` lands is deliberate: each function keeps exactly the positional arity it
has today, so none of the 26 in-tree call sites change (20 for `recall_search_structured`, 6 for
`recall_search`; counted, not estimated). `query_vec` is **not** added to
`recall_search` — it is not in that function's contract, and adding it would be scope creep.

### Body

One statement at the top of each body rebuilds the local dict the rest of the code already expects:

```python
filters = {k: v for k, v in (
    ("types", types), ("tiers", tiers), ("spaces", spaces), ("tags", tags),
    ("created_after", created_after), ("created_before", created_before),
) if v is not None}
```

Everything downstream is untouched: `filters.update(time_params)` in the auto-temporal block,
`filters.get("spaces")`, `search.search(**filters)`, and `_supplement_temporal(..., filters)` all
operate on an ordinary dict exactly as before.

### Why this is behaviour-neutral for every current caller

- `routes_agent.py:67-73` passes `types=None, tiers=None, spaces=None, tags=None` explicitly today,
  so `filters` currently holds those keys with `None` values. The comprehension drops them and
  `HybridSearch.search` restores the identical `None` defaults.
- Every guard in both bodies is a falsiness test (`if created_after:`,
  `not filters.get("created_after")`, `explicit_spaces = filters.get("spaces")`), so "key absent"
  and "key present holding `None`" were already equivalent.
- The accepted key set does not change. Only *unaccepted* keys change behaviour, and only on the
  FTS path, where they change from silence to the `TypeError` the hybrid path already raises.

### Error handling

The raised exception is the interpreter's own `TypeError`, naming the offending keyword argument,
at the function header — before `_get_hybrid_search()` is called. That ordering is the fix: the two
backends can no longer disagree because an unknown key never reaches either of them. The exception
type is unchanged from what the hybrid path raises today, so no caller that already handles it sees
a new failure mode.

## Testing

New file `tests/test_engine/test_recall_filter_contract.py`, using the shared `engine` fixture
(`tests/conftest.py:147`) plus a local three-line copy of the `fts_only` fixture pattern from
`tests/test_engine/test_confirmed_use_contract.py:51-55`. Tests are parametrized over both entry
points.

1. **`unknown_filter_raises_on_fts_fallback`** — the red test. With `_get_hybrid_search` patched to
   return `None`, passing `tierz=[...]` today returns a `list` and raises nothing. After the change
   it raises `TypeError` naming `tierz`.
2. **`unknown_filter_raises_on_hybrid_path`** — verified already green in this environment
   (`ormah.embeddings.hybrid_search` imports successfully), since the hybrid path raises today.
   It is a regression guard against reintroducing a bag, not a new red.
3. **`known_filters_accepted_on_both_paths`** — all six keys accepted with no raise and the
   documented return type, on both paths.
4. **`positional_contract_unchanged`** — `("q", 10, None)` still valid on both functions, and
   `recall_search_structured("q", 10, None, False)` still raises `TypeError`, so issue #220's
   keyword-only contract survives.

Honest note on test 2: after the change the raise precedes the branch, so the `fts_only` fixture no
longer discriminates between code paths. It earns its place as a guard, not as a path
discriminator.

## Out of scope

- **Issue #233.** `types`, `tiers` and `tags` remain ignored in the FTS fallback's main enrichment
  loop. (`types`, `tiers` and `spaces` — but not `tags` — *are* applied inside
  `_supplement_temporal` at `memory_engine.py:2613-2618`, which reads them from the dict; another
  reason not to touch that behaviour here.) No test in this change asserts anything about it;
  fixing it here would collide with #233's own fix.
- **The whisper's exception swallow.** `src/ormah/engine/context_builder.py:573-575` wraps the
  `recall_search_structured` call in `except Exception`, logs `"Whisper search failed"` and returns
  an empty whisper. A `TypeError` from a bad filter key on the hottest production path is therefore
  a logged warning and a silent empty whisper, not a loud failure. This is a known limitation of
  the fix's reach; no issue is opened for it as part of this work.
- No new filter keys, no `query_vec` on `recall_search`, no changes to any call site.

## Workflow

Recipe A from `FORK-WORKFLOW.md`: a clean island worktree at `../ormah-wt-232` on branch
`fix/232-explicit-filter-params`, cut from `upstream/main`. `Tools/ormah` stays parked on
`local-main` — the Beta server serves that tree. This spec lives on `local-main` and must not be
committed to the contribution branch.

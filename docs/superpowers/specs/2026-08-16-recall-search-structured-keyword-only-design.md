# recall_search_structured: keyword-only tuning parameters

**Date:** 2026-08-16 · **Issue:** #220 (council R1, finding 3) · **Branch:** `fix/220-confirmed-use`

## Problem

Removing the `touch_access` parameter as part of #220 changed the positional layout of
`MemoryEngine.recall_search_structured`. The signature at `a28837bc` was:

```python
self, query: str, limit: int = 10, default_space: str | None = None,
touch_access: bool = True, min_relevance: float | None = None, ...
```

`touch_access` held the 4th positional slot. With it gone, `min_relevance` inherits that slot.
A pre-existing positional call passing `False` in the 4th position now silently means
`min_relevance=0`, which removes the deliberate-recall relevance floor and admits results below
it. Nothing raises; the caller gets a wider result set and no signal that the floor is gone.

Council R1 filed this as `medium` (Codex, confidence 0.96) framed as breaking external callers.

## What the evidence changed about the framing

Verified during design:

- `src/ormah/__init__.py` is **0 bytes** — `MemoryEngine` is not re-exported at package level.
- `recall_search_structured` appears in **no** doc and **no** README section. The documented
  surface (`docs/08 - API Surface.md`) covers HTTP routes, not the engine.
- `touch_access` appears in **no** public surface: not in `src/ormah/adapters/` (MCP), not in
  `src/ormah/api/` (HTTP), not in `src/ormah/cli.py`.
- `pyproject.toml` declares one entry point: `ormah = "ormah.cli:main"`.
- All **14** in-repo call sites (4 production/eval, 10 tests) pass at most `query` positionally;
  everything after it is keyword.
- The maintainer of this workspace knows of no external consumer importing `MemoryEngine`.

So this is not a public-contract compatibility problem. It is an internal silent-failure trap,
and the most likely future victim is a caller inside this repo.

Keyword calls are not part of the trap, also verified: an unknown keyword flows into `**filters`
and is forwarded to `HybridSearch.search` (`src/ormah/embeddings/hybrid_search.py:85-96`), which
declares fixed named parameters and no `**kwargs` — so it raises `TypeError`, loudly. On the FTS
fallback the unknown key is ignored, which is now the correct behaviour: `touch_access` no longer
exists and doing nothing is what #220 intends. Neither keyword path corrupts a value.

**Only the positional path corrupts, and only silently.** That is what this change closes.

## Decision

Mark every tuning parameter keyword-only with a bare `*` in the signature.

```python
def recall_search_structured(
    self, query: str, limit: int = 10, default_space: str | None = None,
    *, min_relevance: float | None = None,
    auto_temporal: bool = True, spread_activation: bool = True,
    query_vec: Any | None = None, **filters,
) -> list[dict]:
```

`query`, `limit` and `default_space` stay positional — that is exactly what the existing call
sites use. `min_relevance`, `auto_temporal`, `spread_activation` and `query_vec` become
keyword-only.

## Contract

- A call with 4 or more positional arguments raises `TypeError` at call time.
- No existing call site changes; all 14 already comply.
- `touch_access` is **not** reintroduced. #220 removed it deliberately.
- The guarantee outlives this specific parameter: any future reordering of the tuning parameters
  can no longer be absorbed silently by a positional caller.

## Test plan

One contract test, added to `tests/test_engine/test_confirmed_use_contract.py` alongside the
other #220 contracts.

`test_recall_search_structured_rejects_positional_tuning_args`

```python
with pytest.raises(TypeError):
    engine.recall_search_structured("caching architecture", 10, None, False)
```

Worked example, walked by hand:

- **Before the change:** the call is accepted, `min_relevance=False` coerces to `0.0`, the floor
  is dropped, nothing raises. `pytest.raises(TypeError)` fails with *DID NOT RAISE* — the test is
  RED for the exact reason it targets.
- **After the change:** Python raises `TypeError: recall_search_structured() takes from 2 to 4
  positional arguments but 5 were given`. GREEN.

The assertion reaches the defect: deleting the `*` in the future turns it red again.

The positive side — keyword calls still work — needs no new test. The 14 existing call sites
exercise it throughout the suite; a dedicated test would be redundant.

## Rejected alternatives

**Deprecation shim.** Reintroduce `touch_access` as an ignored keyword-only parameter emitting
`DeprecationWarning`. Rejected: it resurrects a name #220 deleted on purpose, adds dead machinery
for zero known consumers, and — decisively — leaves the positional trap open, which is the only
part that actually corrupts.

**Document only.** Note the break in the PR description and change no code. Rejected: cheapest,
but leaves the silent-floor trap live for the next internal caller.

## Out of scope

`**filters` swallows any misspelled filter keyword (`tierz=` for `tiers=`), silently on the FTS
fallback and loudly on the hybrid path. Pre-existing, not introduced by #220, wider than this
change. Reported upstream as its own issue; not fixed here.

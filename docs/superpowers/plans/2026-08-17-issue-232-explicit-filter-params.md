# Explicit Filter Parameters on the Recall Boundary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an unknown filter key raise `TypeError` at the recall boundary on both search backends, instead of crashing on one and being silently dropped on the other.

**Architecture:** Replace the `**filters` bag on `MemoryEngine.recall_search_structured` and `MemoryEngine.recall_search` with six explicit keyword-only parameters (`types`, `tiers`, `spaces`, `tags`, `created_after`, `created_before`), then rebuild a local `filters` dict on the first line of each body so nothing downstream changes. The interpreter becomes the validator, at the function header, before the backend branch — so the two backends can no longer disagree.

**Tech Stack:** Python 3.11+, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-17-issue-232-explicit-filter-params-design.md`

## Global Constraints

- **Never run `git checkout` or any branch switch inside `/Users/andre/Documents/GitHub/Tools/ormah`** — a launchd Beta server (`com.ormah.server.dev`) serves that tree, and switching its branch crashes every whisper hook. All work happens in the worktree created in Task 1.
- **Always invoke Python as `./.venv/bin/python` from inside the worktree.** Never bare `python`, never `make test`. Measured: the main tree's venv holds an editable install resolving to `/Users/andre/Documents/GitHub/Tools/ormah/src/ormah`, so a bare `python` run from a worktree tests the *main tree's* code and produces a false green.
- **Nothing under `docs/` may be committed to the contribution branch.** This plan and its spec live on `local-main` and stay there (`FORK-WORKFLOW.md`, rule 5).
- **Ruff:** `target-version = py311`, `line-length = 100`.
- **Do not modify any call site.** All 26 in-tree call sites (20 for `recall_search_structured`, 6 for `recall_search`) already pass filters by keyword and keep their positional arity under this change. If one appears to need editing, the edit is wrong — stop and report.
- **Do not fix issue #233** (known `types`/`tiers`/`tags` dropped in the FTS fallback's enrichment loop). It is a separate issue with its own fix; no test here may assert anything about it.
- **Do not add filter keys, do not add `query_vec` to `recall_search`, do not touch `HybridSearch.search`.**

---

### Task 1: The clean island, a verified toolchain, and a recorded baseline

**Files:**
- Create: `/Users/andre/Documents/GitHub/Tools/ormah-wt-232/` (worktree, branch `fix/232-explicit-filter-params`)
- Create: `/Users/andre/Documents/GitHub/Tools/ormah-wt-232/.venv/` (dedicated dev install)

**Interfaces:**
- Consumes: nothing.
- Produces: an absolute worktree path `/Users/andre/Documents/GitHub/Tools/ormah-wt-232` whose `./.venv/bin/python` imports `ormah` from that worktree's own `src/`, plus a recorded list of pre-existing failing test IDs that Task 2 compares against.

- [ ] **Step 1: Fetch upstream and cut the island from it**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && \
  git fetch upstream && \
  git worktree add -b fix/232-explicit-filter-params \
    ../ormah-wt-232 upstream/main )
```

- [ ] **Step 2: Prove the island is clean**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  git log --oneline upstream/main..HEAD )
```

Expected: **no output at all.** Any commit listed means the branch was cut from the wrong base — remove the worktree (`git worktree remove ../ormah-wt-232`) and redo Step 1. This gate is the whole point of Recipe A in `FORK-WORKFLOW.md`; do not proceed past a non-empty result.

- [ ] **Step 3: Build the worktree's own dev environment**

This takes several minutes (fastembed pulls onnxruntime and tokenizers). It is not optional: it is what makes `./.venv/bin/python` self-anchoring, so no later command can silently test the main tree.

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  python3 -m venv .venv && \
  ./.venv/bin/pip install -q -e ".[dev]" )
```

- [ ] **Step 4: Guard the resolution before trusting any test**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/python -c "import ormah; print(ormah.__file__)" )
```

Expected: exactly `/Users/andre/Documents/GitHub/Tools/ormah-wt-232/src/ormah/__init__.py`.

If it prints a path under `Tools/ormah/src` instead, every test result from here on is meaningless — stop and report. Do not work around it with `PYTHONPATH`.

- [ ] **Step 5: Record the baseline failing test IDs**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/python -m pytest tests/ -q 2>&1 | tail -30 | tee /tmp/ormah-232-baseline.txt )
```

Expected: some failures. The repository has known environment-dependent failures (12 were measured on a neighbouring branch), and the exact set on `upstream/main` in this environment is **not** predicted here — record what you observe. Task 2 compares **test IDs against this file**, never counts. Paste the observed summary line and failing IDs into your task report.

- [ ] **Step 6: Report and stop**

Report the worktree path, the output of Step 4, and the baseline failing IDs from Step 5. Make no code change in this task.

---

### Task 2: Explicit keyword-only filter parameters on both entry points

**Files:**
- Modify: `src/ormah/engine/memory_engine.py` — `recall_search_structured` signature at lines 928-933 and its body; `recall_search` signature at lines 1070-1077 and its body
- Create: `tests/test_engine/test_recall_filter_contract.py`

**Interfaces:**
- Consumes: the worktree path and baseline IDs from Task 1.
- Produces: `MemoryEngine.recall_search_structured(self, query: str, limit: int = 10, default_space: str | None = None, *, types: list[str] | None = None, tiers: list[str] | None = None, spaces: list[str] | None = None, tags: list[str] | None = None, created_after: str | None = None, created_before: str | None = None, min_relevance: float | None = None, auto_temporal: bool = True, spread_activation: bool = True, query_vec: Any | None = None) -> list[dict]` and `MemoryEngine.recall_search(self, query: str, limit: int = 10, default_space: str | None = None, session_id: str | None = None, *, types: list[str] | None = None, tiers: list[str] | None = None, spaces: list[str] | None = None, tags: list[str] | None = None, created_after: str | None = None, created_before: str | None = None) -> str`. Return types and behaviour for every accepted key are unchanged.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_engine/test_recall_filter_contract.py` with exactly this content:

```python
"""Contract tests for issue #232: the recall boundary rejects unknown filter keys.

Both entry points and both search backends must agree. Before this contract an
unknown key raised TypeError on the hybrid path (HybridSearch.search declares no
**kwargs) and was silently dropped on the FTS fallback, so a typo either crashed
or quietly returned unfiltered results depending on whether the embeddings extra
happened to be installed in that environment.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ormah.models.node import CreateNodeRequest

# Both public recall entry points on MemoryEngine carry the same filter contract.
ENTRY_POINTS = ("recall_search_structured", "recall_search")

# The realistic typo: one transposed character away from `tiers`.
UNKNOWN_KEY = "tierz"


def _make_nodes(engine, count=3):
    """Seed nodes that match the query used throughout this file."""
    ids = []
    for i in range(count):
        node_id, _ = engine.remember(CreateNodeRequest(
            content=f"caching architecture note number {i}",
            title=f"Caching {i}",
            type="fact",
            tier="working",
        ))
        ids.append(node_id)
    return ids


@pytest.fixture
def fts_only(engine):
    """Force the FTS fallback path by removing hybrid search."""
    with patch.object(engine, "_get_hybrid_search", return_value=None):
        yield engine


@pytest.mark.parametrize("method_name", ENTRY_POINTS)
def test_unknown_filter_raises_on_fts_fallback(fts_only, method_name):
    """The defect: on the FTS fallback an unknown key was dropped in silence.

    Before this contract the call below returned results as though no filter had
    been requested, and nothing in the return value distinguished that from a
    legitimately broad match — the caller had no signal that the constraint it
    asked for was never applied.
    """
    engine = fts_only
    _make_nodes(engine)

    with pytest.raises(TypeError) as excinfo:
        getattr(engine, method_name)(
            "caching architecture", limit=10, **{UNKNOWN_KEY: ["working"]},
        )

    assert UNKNOWN_KEY in str(excinfo.value), (
        f"raised, but not about the unknown key: {excinfo.value}"
    )


@pytest.mark.parametrize("method_name", ENTRY_POINTS)
def test_unknown_filter_raises_on_hybrid_path(engine, method_name):
    """Regression guard: the hybrid path already rejected unknown keys.

    Once the keys are explicit parameters the raise happens at the function
    header, before the backend branch, so this test and the FTS one converge on
    one behaviour. It earns its place by failing if anyone reintroduces a
    **filters bag on either entry point.
    """
    _make_nodes(engine)

    with pytest.raises(TypeError) as excinfo:
        getattr(engine, method_name)(
            "caching architecture", limit=10, **{UNKNOWN_KEY: ["working"]},
        )

    assert UNKNOWN_KEY in str(excinfo.value), (
        f"raised, but not about the unknown key: {excinfo.value}"
    )


@pytest.mark.parametrize("method_name", ENTRY_POINTS)
@pytest.mark.parametrize("use_fts", [False, True])
def test_known_filters_accepted_on_both_paths(engine, method_name, use_fts):
    """All six accepted keys stay accepted, on either backend.

    Four are passed as None deliberately: a name that is not a parameter raises
    TypeError even when its value is None, so this asserts each of the six names
    exists — not merely that the two populated ones work.
    """
    _make_nodes(engine)
    ctx = (
        patch.object(engine, "_get_hybrid_search", return_value=None)
        if use_fts else patch.object(engine, "_hybrid_search", engine._hybrid_search)
    )
    expected_type = list if method_name == "recall_search_structured" else str

    with ctx:
        result = getattr(engine, method_name)(
            "caching architecture",
            limit=10,
            types=["fact"],
            tiers=["working"],
            spaces=None,
            tags=None,
            created_after=None,
            created_before=None,
        )

    assert isinstance(result, expected_type)


def test_positional_contract_unchanged(engine):
    """The positional arity each entry point has today survives the change.

    `recall_search_structured` keeps 3 positional slots and `recall_search`
    keeps 4, so no call site changes. The fourth-slot TypeError is issue #220's
    keyword-only contract, which must still hold.
    """
    _make_nodes(engine)

    assert isinstance(
        engine.recall_search_structured("caching architecture", 10, None), list
    )
    assert isinstance(
        engine.recall_search("caching architecture", 10, None, None), str
    )

    with pytest.raises(TypeError):
        engine.recall_search_structured("caching architecture", 10, None, False)
```

- [ ] **Step 2: Run the new file and record which tests fail**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/python -m pytest tests/test_engine/test_recall_filter_contract.py -v )
```

Expected: the two `test_unknown_filter_raises_on_fts_fallback` cases **FAIL** with `Failed: DID NOT RAISE <class 'TypeError'>`. That failure is the defect made visible — the unknown key was accepted and dropped.

The two `test_unknown_filter_raises_on_hybrid_path` cases are expected to **PASS** already, because that path raises today. This is inferred from an existing unpatched hybrid test that passes (`tests/test_engine/test_confirmed_use_contract.py:60-65`), not measured here — **observe and record the actual result.** If they also fail with `DID NOT RAISE`, hybrid search is unavailable in this environment; that is not a blocker, note it in your report and continue.

If any test fails with an error other than `DID NOT RAISE` (an import error, a fixture error, a `KeyError`), stop — the test is not reaching its target.

- [ ] **Step 3: Make `recall_search_structured`'s filters explicit**

In `src/ormah/engine/memory_engine.py`, replace the signature at lines 928-933:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        *, min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

with:

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

Then, in the same method, insert the dict rebuild immediately after the closing `"""` of the docstring and **before** the comment line `# Auto-extract temporal filters from query when none provided. Typed`:

```python
        # The six keys this boundary accepts, rebuilt as the dict the rest of
        # this method (and _supplement_temporal, and HybridSearch.search) already
        # consumes. Declaring them as parameters is what makes an unknown key a
        # TypeError here, before the backend branch, instead of a crash on one
        # backend and silence on the other (#232).
        filters = {k: v for k, v in (
            ("types", types), ("tiers", tiers), ("spaces", spaces), ("tags", tags),
            ("created_after", created_after), ("created_before", created_before),
        ) if v is not None}
```

Change nothing else in the method — not the docstring, not a single line of the body below that insertion.

- [ ] **Step 4: Make `recall_search`'s filters explicit**

Replace the signature at lines 1070-1077 (line numbers refer to the file *before* Step 3 added lines; locate it by content):

```python
    def recall_search(
        self,
        query: str,
        limit: int = 10,
        default_space: str | None = None,
        session_id: str | None = None,
        **filters,
    ) -> str:
```

with:

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

The `*` goes after `session_id`, not before it: that preserves this method's four existing positional slots. Then insert the same rebuild immediately after the closing `"""` of its docstring and **before** the line `query_for_log = query`:

```python
        # Same six-key contract as recall_search_structured — see #232.
        filters = {k: v for k, v in (
            ("types", types), ("tiers", tiers), ("spaces", spaces), ("tags", tags),
            ("created_after", created_after), ("created_before", created_before),
        ) if v is not None}
```

- [ ] **Step 5: Run the new file and confirm every test passes**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/python -m pytest tests/test_engine/test_recall_filter_contract.py -v )
```

Expected: **9 passed** (2 + 2 + 4 parametrized cases + 1 positional test). The message on the unknown-key raises is now the interpreter's own, of the form `MemoryEngine.recall_search_structured() got an unexpected keyword argument 'tierz'`.

- [ ] **Step 6: Lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/ruff check src/ormah/engine/memory_engine.py \
    tests/test_engine/test_recall_filter_contract.py )
```

Expected: `All checks passed!`

- [ ] **Step 7: Run the full suite and compare test IDs against Task 1's baseline**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  ./.venv/bin/python -m pytest tests/ -q 2>&1 | tail -30 )
```

Compare the failing IDs against `/tmp/ormah-232-baseline.txt` from Task 1 Step 5. **Any failing ID not on the baseline list is a regression from this task — stop and report it.** A different failure *count* with an identical ID list is not a regression. Do not compare counts.

Pay particular attention to `tests/test_engine/test_confirmed_use_contract.py`, `tests/test_engine/test_memory_engine.py`, `tests/test_engine/test_temporal_search.py` and `tests/test_engine/test_scoring_signals.py`: they exercise the filter paths most heavily, and a mistake in the dict rebuild surfaces there first.

- [ ] **Step 8: Commit by exact path**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && \
  git add src/ormah/engine/memory_engine.py \
    tests/test_engine/test_recall_filter_contract.py && \
  git commit -m "fix(engine): reject unknown filter keys at the recall boundary

recall_search_structured and recall_search both collected their filters into
an untyped **filters bag, and the two backends disagreed about an unknown key.
The hybrid path forwards the bag to HybridSearch.search, which declares no
**kwargs and raises TypeError; the FTS fallback never forwards it and only
reads the keys it knows, so an unknown key was silently dropped and the search
returned unfiltered results as though the filter had been applied.

A mistyped filter name therefore crashed or quietly widened the result set
depending on whether the embeddings extra was installed. Nothing in the return
value distinguished the silent case from a legitimately broad match.

Declaring the six accepted keys as explicit keyword-only parameters makes the
interpreter the validator, at the function header, before the backend branch --
so an unknown key never reaches either backend and the two cannot disagree. The
accepted key set is unchanged and each method keeps its current positional
arity, so none of the 26 in-tree call sites change." )
```

- [ ] **Step 9: Verify the commit contains exactly two files**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-232 && git show --stat HEAD )
```

Expected: exactly 2 files changed — `src/ormah/engine/memory_engine.py` and `tests/test_engine/test_recall_filter_contract.py`. Nothing under `docs/`. If the count differs, stop and report.

---

## Out of scope

- **Issue #233** — `types`, `tiers` and `tags` remain ignored in the FTS fallback's enrichment loop. Do not fix it here; it has its own issue and fix.
- **The whisper's exception swallow** at `src/ormah/engine/context_builder.py:573-575`, which turns any `TypeError` from the whisper search into a logged warning and an empty whisper. Documented as a known limitation in the spec; no issue is opened for it and no change is made.
- **Do not push to `fork` and do not open a PR.** Both need explicit authorization that this plan does not carry.

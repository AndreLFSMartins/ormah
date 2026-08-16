# recall_search_structured Keyword-Only Tuning Parameters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a positional call that would silently reinterpret an old 4th argument as `min_relevance` fail loudly with `TypeError` instead.

**Architecture:** One bare `*` in the signature of `MemoryEngine.recall_search_structured`, pinned by one contract test. `query`, `limit` and `default_space` stay positional; every tuning parameter after them becomes keyword-only. No behaviour changes for any existing caller.

**Tech Stack:** Python 3.11+, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-16-recall-search-structured-keyword-only-design.md`

## Global Constraints

- **Working directory is the worktree**, not the main tree: `/Users/andre/Documents/GitHub/Tools/ormah-wt-220`, branch `fix/220-confirmed-use`. Anchor every Bash call with an absolute path or a subshell `( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && ... )`.
- **Always invoke Python as `./.venv/bin/python`.** Never bare `python`, never `make test`. Measured: bare `python` resolves to `/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python` and imports the *main tree's* `ormah`, producing a false green against code you did not edit.
- **Never run `git checkout` inside `/Users/andre/Documents/GitHub/Tools/ormah`** — a Beta server serves that tree. **Nothing under `docs/` may be committed to `fix/220-confirmed-use`**; this plan and its spec live on `local-main` and stay there.
- **Ruff:** `target-version = py311`, `line-length = 100`.
- Do **not** reintroduce the `touch_access` parameter (#220 removed it deliberately), and do **not** modify any call site — all 14 in-repo call sites already comply; if one needs changing, the change is wrong, so stop and report.

---

### Task 1: Keyword-only tuning parameters on `recall_search_structured`

**Files:**
- Modify: `src/ormah/engine/memory_engine.py:730-735`
- Test: `tests/test_engine/test_confirmed_use_contract.py` (append at end of file, currently 677 lines)

**Interfaces:**
- Consumes: nothing from earlier tasks — this is the only task.
- Produces: `MemoryEngine.recall_search_structured(self, query, limit=10, default_space=None, *, min_relevance=None, auto_temporal=True, spread_activation=True, query_vec=None, **filters) -> list[dict]`. Positional arity drops from 8 to 4 (counting `self`). No return-type or behaviour change.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/test_engine/test_confirmed_use_contract.py`:

```python
def test_recall_search_structured_rejects_positional_tuning_args(engine):
    """Contract 14: tuning parameters are keyword-only, so a stale positional
    call cannot silently redefine itself.

    #220 removed the `touch_access` parameter, which held the 4th positional
    slot. `min_relevance` inherited that slot, so a pre-existing positional
    call passing False in position 4 would mean min_relevance=0 — silently
    dropping the deliberate-recall relevance floor and admitting results below
    it. The bare `*` turns that silent redefinition into an immediate TypeError.
    """
    _make_nodes(engine, count=1)

    with pytest.raises(TypeError) as excinfo:
        # The exact shape of a stale caller: `False` where touch_access used to be.
        engine.recall_search_structured("caching architecture", 10, None, False)

    assert "positional" in str(excinfo.value), (
        f"raised for the wrong reason: {excinfo.value}"
    )

    # The supported shapes must keep working — this is the other half of the
    # contract. `isinstance(..., list)` rather than `is not None`: the point is
    # that the call completes and still returns the documented type.
    assert isinstance(engine.recall_search_structured("caching architecture"), list)
    assert isinstance(engine.recall_search_structured("caching architecture", limit=4), list)
    assert isinstance(engine.recall_search_structured("caching architecture", 4, None), list)
    assert isinstance(engine.recall_search_structured(
        "caching architecture", limit=4, min_relevance=0.0, spread_activation=False,
    ), list)
```

- [ ] **Step 2: Run the test and confirm it fails for the right reason**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  ./.venv/bin/python -m pytest \
  tests/test_engine/test_confirmed_use_contract.py::test_recall_search_structured_rejects_positional_tuning_args -v )
```

Expected: **FAIL** with `Failed: DID NOT RAISE <class 'TypeError'>`.

This is the defect made visible: without the `*`, the call is accepted and `min_relevance=False` coerces to `0.0`. If it fails with any *other* message, or passes, stop — the test is not reaching the target.

- [ ] **Step 3: Add the keyword-only marker**

In `src/ormah/engine/memory_engine.py`, replace the signature at lines 730-735:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

with:

```python
    def recall_search_structured(
        self, query: str, limit: int = 10, default_space: str | None = None,
        *, min_relevance: float | None = None,
        auto_temporal: bool = True, spread_activation: bool = True,
        query_vec: Any | None = None, **filters,
    ) -> list[dict]:
```

The only change is `*, ` before `min_relevance`. Touch nothing else — not the docstring, not the body.

- [ ] **Step 4: Run the test and confirm it passes**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  ./.venv/bin/python -m pytest \
  tests/test_engine/test_confirmed_use_contract.py::test_recall_search_structured_rejects_positional_tuning_args -v )
```

Expected: **PASS**. The raised message is `recall_search_structured() takes from 2 to 4 positional arguments but 5 were given` (measured, not recalled).

- [ ] **Step 5: Run the whole contract file**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  ./.venv/bin/python -m pytest tests/test_engine/test_confirmed_use_contract.py -q )
```

Expected: **30 passed** (29 before this task, plus the new one). Any other number means something regressed — stop and report.

- [ ] **Step 6: Lint**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  ./.venv/bin/ruff check src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py )
```

Expected: `All checks passed!`

- [ ] **Step 7: Run the full suite and compare test IDs, never counts**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  ./.venv/bin/python -m pytest tests/ -q 2>&1 | tail -20 )
```

Expected: **12 failed, 1862 passed, 1 deselected** (12 failed + 1861 passed measured at `81d2677`; the new test adds one pass).

The 12 failures are pre-existing and environmental, and their IDs must be exactly this list — compare the IDs, not the count:

```
tests/test_background/test_consolidator.py::test_consolidation_settings_defaults
tests/test_background/test_hippocampus.py::test_new_file_triggers_ingestion
tests/test_background/test_session_watcher.py::test_record_whisper_usage_signal_keeps_unreferenced_neutral
tests/test_background/test_session_watcher.py::test_llm_judge_disabled_by_default
tests/test_config.py::test_llm_provider_defaults_to_none
tests/test_config.py::test_affinity_defaults
tests/test_setup.py::TestConfigureCodexMcp::test_writes_mcp_config_to_codex_toml
tests/test_setup.py::TestConfigureCodexMcp::test_preserves_existing_toml_content
tests/test_setup.py::TestConfigureCodexMcp::test_replaces_existing_ormah_block
tests/test_setup.py::TestRemoveFastembedCache::test_deletes_known_model_dirs
tests/test_setup.py::TestRemoveFastembedCache::test_removes_cache_dir_when_empty_after_cleanup
tests/test_setup.py::TestRemoveFastembedCache::test_uses_default_fastembed_cache_dir
```

Any ID not on this list is a regression from this task — stop and report it. A differing *count* with an identical ID list is not.

- [ ] **Step 8: Commit by exact path**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add src/ormah/engine/memory_engine.py tests/test_engine/test_confirmed_use_contract.py && \
  git commit -m "fix(engine): make recall_search_structured tuning params keyword-only

Removing touch_access in #220 freed the 4th positional slot, which
min_relevance silently inherited. A stale positional call passing False
there now means min_relevance=0, dropping the deliberate-recall relevance
floor with no error. Keyword paths already fail loudly (HybridSearch.search
takes no **kwargs) or correctly ignore the key on the FTS fallback; only the
positional path corrupts.

A bare * makes it a TypeError at call time. All 14 in-repo call sites pass
at most query positionally, so none of them change." )
```

- [ ] **Step 9: Verify the commit contains exactly two files**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && git show --stat HEAD )
```

Expected: exactly 2 files changed — `src/ormah/engine/memory_engine.py` and `tests/test_engine/test_confirmed_use_contract.py`. Nothing under `docs/`. If the count differs, stop.

- [ ] **Step 10: Refresh the code graph**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && graphify update . )
```

---

## Out of scope

- The `**filters` swallowing problem (unknown keys, and known `types`/`tiers`/`tags` dropped on the FTS fallback) is tracked upstream in its own issues. Do not fix it here.
- Do not push to `fork` and do not open a PR — both are unauthorized, and issue #229 still declares `Closes #220–#223`.

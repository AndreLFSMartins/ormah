# Task 1: The error seam — `LlmCancelledError` and `LlmTimeoutError`

**Files:**
- Create: `src/ormah/background/llm_errors.py` (outside `llm/` so the Beta's own layering
  stays clean — the `llm/` package holds adapters, not shared types)
- Modify: `src/ormah/background/llm_client.py:119-140` (`llm_generate`)
- Test: `tests/test_background/test_claude_cli_adapter.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ormah.background.llm_errors.LlmCancelledError(Exception)` — the host cancelled the
    call (shutdown/stop). Says nothing about the payload.
  - `ormah.background.llm_errors.LlmTimeoutError(Exception)` — the provider call exceeded
    its budget. **Nothing raises it in this slice**; it is defined here so the seam ships
    complete in one file and slice 3 only has to add the raise site. Do not add behavior
    for it here.
  - `llm_generate()` (the maintenance path) swallows BOTH and returns `None`, keeping the
    five maintenance consumers (consolidator, pair_batch, conflict_detector,
    duplicate_merger, auto_linker) behaviourally unchanged.
  - `ingest_llm_generate()` propagates both — its sole caller is
    `memory_engine._extract_memories_llm` (L2842), which slice 3 teaches to fully classify.
    **🔴 CORRECTED 2026-07-23 (merged slice 1):** the original plan said a cancelled ingest
    call could surface through the engine's broad handler as a generic error "because nothing
    consumes a per-slice failure budget yet." **That is now false.** Slice 1 shipped
    `_ingest_session._record_extract_failure` (`session_watcher.py:947-1001`), a per-slice cap
    that SKIPS a slice (advances the cursor, "observable data loss") after
    `MAX_EXTRACT_FAILURES`. A raised `LlmCancelledError` reaching `_extract_memories_llm`'s
    generic `except Exception` (`memory_engine.py:2903`) returns the generic "LLM extraction
    failed" string — NOT `EXTRACT_ERR_CALL_FAILED` — which `_ingest_session` (L1044) counts
    toward that cap. So repeated restarts during one slice's extraction would skip a healthy
    slice. **Task 2 therefore MUST add `except LlmCancelledError: return
    EXTRACT_ERR_CALL_FAILED` to `_extract_memories_llm`** (before the generic handler),
    mapping cancel → provider-wide transient → `IngestResult.TRANSIENT` → requeue, no cap.
    This is not deferrable to slice 3; it is what makes slice 2's own durability claim ("a
    killed extraction never advances the cursor") true. Slice 3 later refines this into a
    dedicated classification but the safe mapping ships here.

- [ ] **Step 1: Write the failing test**

Mirror the existing mocking style in `tests/test_background/test_claude_cli_adapter.py`
(read its constructor helper/fixture first):

```python
from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError


def test_llm_generate_swallows_cancel_and_timeout(monkeypatch):
    """The maintenance path keeps its None-on-failure contract, so consolidator,
    auto_linker & co. are untouched by the new exception types."""
    from ormah.background import llm_client

    for exc in (LlmCancelledError("stopped"), LlmTimeoutError("slow")):
        class _Raising:
            def generate(self, *a, **k):
                raise exc
        monkeypatch.setattr(llm_client, "_get_or_create_adapter", lambda s: _Raising())
        assert llm_client.llm_generate(object(), "prompt") is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py -k swallows -v`
Expected: FAIL — `ModuleNotFoundError: ormah.background.llm_errors`.

- [ ] **Step 3: Implement**

Create `src/ormah/background/llm_errors.py`:

```python
"""Shared LLM adapter error types."""


class LlmCancelledError(Exception):
    """The call was cancelled by the host (shutdown/stop), not by the provider.

    Says NOTHING about the payload being processed: callers must treat it like any
    other transient provider failure and never count it against per-slice budgets.
    """


class LlmTimeoutError(Exception):
    """The provider call exceeded its time budget.

    Distinct from a fast failure (missing binary, connection refused). Raised by the
    claude_cli adapter; classification lives with the ingest path (ADR-0004 slice 3).
    """
```

In `llm_client.py`, import both and wrap the adapter call in `llm_generate` (L133-140):

```python
    try:
        return adapter.generate(
            prompt,
            json_mode=json_mode,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_hint_seconds=timeout_hint_seconds,
        )
    except (LlmCancelledError, LlmTimeoutError):
        return None
```

`ingest_llm_generate` (L101-107): **no change** — it propagates by construction.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py tests/test_background/test_ingest_provider.py -v`
Expected: PASS, including the untouched neighbours.

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/ tests/
git add src/ormah/background/llm_errors.py src/ormah/background/llm_client.py \
        tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): LlmCancelledError/LlmTimeoutError seam; maintenance path swallows both (ADR-0004)"
```

# Task 1: `LlmTimeoutError` — distinct timeout signal at the adapter boundary

**Files:**
- Create: `src/ormah/background/llm_errors.py` (outside `llm/` so the Beta's own
  layering stays clean)
- Modify: `src/ormah/background/llm/claude_cli_adapter.py:141-143`
- Modify: `src/ormah/background/llm_client.py:119-140` (`llm_generate`)
- Test: `tests/test_background/test_claude_cli_adapter.py` (existing `test_returns_none_on_timeout` at ~L90 changes meaning)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `ormah.background.llm_errors.LlmTimeoutError(Exception)` — raised by
  `ClaudeCliAdapter.generate()` on `subprocess.TimeoutExpired` — and
  `LlmCancelledError(Exception)` (raised only by Task 7's shutdown cancellation;
  defined here so the seam ships complete in one upstream file). `ingest_llm_generate()`
  PROPAGATES it (Task 2 catches it in the engine); `llm_generate()` (maintenance path)
  swallows it and returns `None` (unchanged behavior for the 5 maintenance consumers).

**Beta-only (council R4/R5).** `upstream/main` has no ingest-provider seam
(`llm_client.py` there exposes only `llm_generate`, and `memory_engine` calls it directly at
upstream L2316-2320) and no `claude_cli` adapter at all. Sending this seam upstream would
ship code no upstream adapter can ever raise. Like every other task in this plan, all files here stay
on `local-main`: `llm_errors.py`, the `llm_client.py` hunk, the adapter, and their tests.

- [ ] **Step 1: Write the failing tests**

In `tests/test_background/test_claude_cli_adapter.py`, replace the timeout test and add one
for the maintenance boundary (mirror the file's existing mocking style — it patches
`subprocess.run`; read the current `test_returns_none_on_timeout` (~L90) first and reuse its
fixture/monkeypatch pattern verbatim):

```python
import subprocess
import pytest

from ormah.background.llm_errors import LlmTimeoutError


def test_raises_llm_timeout_error_on_timeout(monkeypatch):
    adapter = _make_adapter()  # reuse the module's existing constructor helper/fixture
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)
    monkeypatch.setattr("ormah.background.llm.claude_cli_adapter.subprocess.run", fake_run)
    with pytest.raises(LlmTimeoutError):
        adapter.generate("prompt")


def test_llm_generate_swallows_timeout(monkeypatch):
    # maintenance path keeps None-on-timeout so consolidator/auto_linker/etc. are untouched
    from ormah.background import llm_client

    class _TimeoutAdapter:
        def generate(self, *a, **k):
            raise LlmTimeoutError("boom")

    monkeypatch.setattr(llm_client, "_get_or_create_adapter", lambda s: _TimeoutAdapter())
    assert llm_client.llm_generate(object(), "prompt") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: ormah.background.llm_errors`.

- [ ] **Step 3: Implement**

Create `src/ormah/background/llm_errors.py`:

```python
"""Shared LLM adapter error types."""


class LlmTimeoutError(Exception):
    """The provider call exceeded its extraction time budget.

    Distinct from a fast failure (missing binary, connection refused): a timeout is
    evidence about the slice being processed (genuinely slow/toxic), so the ingest
    path may count it toward the per-slice quarantine cap (ADR-0004). Fast failures
    stay uncapped TRANSIENT (a provider outage must never quarantine real data).
    """


class LlmCancelledError(Exception):
    """The call was cancelled by the host (shutdown/stop), not by the provider.

    Says NOTHING about the slice: it must never count toward the quarantine cap
    (council R2). Ingest classifies it like a provider-wide transient failure.
    """
```

In `claude_cli_adapter.py`, add `from ormah.background.llm_errors import LlmTimeoutError`
to the imports and change L141-143:

```python
            except subprocess.TimeoutExpired:
                logger.warning("claude -p timed out after %ss", timeout)
                raise LlmTimeoutError(f"claude -p timed out after {timeout}s") from None
```

(The generic `except Exception` at L144-146 stays as-is — that IS the fast-failure branch.
`LlmTimeoutError` is raised from inside the `except` handler so it does not get re-caught.)

In `llm_client.py` `llm_generate` (L133-140), wrap the adapter call:

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
    except (LlmTimeoutError, LlmCancelledError):
        return None
```

`ingest_llm_generate` (L101-107): NO change — it propagates by construction. Its sole
caller is `memory_engine._extract_memories_llm` (Task 2 adds the catch there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py tests/test_background/test_ingest_provider.py -v`
Expected: PASS (all — including untouched neighbors).

- [ ] **Step 5: Lint + commit**

Provenance-PURE commits (codex R3 — never mix upstream and fork-only files in one commit;
the publish step cherry-picks whole commits):

One commit (everything in this plan lands on the Beta — no provenance split):

```bash
ruff check src/ tests/
git add src/ormah/background/llm_errors.py src/ormah/background/llm_client.py \
        src/ormah/background/llm/claude_cli_adapter.py \
        tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): LlmTimeoutError/LlmCancelledError seam raised by claude_cli (ADR-0004, Beta-only)"
```

# Task 1: raise `LlmTimeoutError` on a real provider timeout

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` — the `TimeoutExpired` branch
  (L141-143 pre-slice-2; after slice 2 it lives inside the `communicate()` handler and
  currently `return None`s)
- (Only if slice 2 was skipped) Create `src/ormah/background/llm_errors.py` and adjust
  `llm_client.llm_generate` to swallow both error types — otherwise both already exist.
- Test: `tests/test_background/test_claude_cli_adapter.py` (existing `test_returns_none_on_timeout` at ~L90 changes meaning)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `ormah.background.llm_errors.LlmTimeoutError(Exception)` — raised by
  `ClaudeCliAdapter.generate()` on `subprocess.TimeoutExpired` — and
  `LlmCancelledError(Exception)` (raised by slice 2's shutdown cancellation; already
  defined and already handled by the maintenance path — this task only adds the timeout
  raise site). `ingest_llm_generate()`
  PROPAGATES it (Task 2 catches it in the engine); `llm_generate()` (maintenance path)
  swallows it and returns `None` (unchanged behavior for the 5 maintenance consumers).

**Beta-only.** ⚠️ **Verify slice 2 landed first**: `grep -n "LlmTimeoutError"
src/ormah/background/llm_errors.py` and confirm the adapter already uses a tracked
`Popen`. If not, do slice 2's Task 1 + the `Popen` migration before this. `upstream/main` has no ingest-provider seam
(`llm_client.py` there exposes only `llm_generate`, and `memory_engine` calls it directly at
upstream L2316-2320) and no `claude_cli` adapter at all. Sending this seam upstream would
ship code no upstream adapter can ever raise. Like every other task in this plan, all files here stay
on `local-main`: `llm_errors.py`, the `llm_client.py` hunk, the adapter, and their tests.

- [ ] **Step 1: Write the failing tests**

In `tests/test_background/test_claude_cli_adapter.py`, replace the timeout test and add one
for the maintenance boundary (mirror the file's existing mocking style — it patches
`subprocess.run`; read the current `test_returns_none_on_timeout` (~L90) first and reuse its
fixture/monkeypatch pattern verbatim):

Use the fake-`Popen` helper slice 2 introduced in this file (it implements `communicate`,
`wait`, `poll`, `terminate`, `kill`, `returncode`) — do NOT patch `subprocess.run`, which
this code path no longer uses:

```python
import subprocess
import pytest

from ormah.background.llm_errors import LlmCancelledError, LlmTimeoutError


def test_raises_llm_timeout_error_on_timeout(monkeypatch):
    """A real provider timeout becomes a distinct signal instead of a None."""
    adapter = _make_adapter()
    _patch_fake_popen(monkeypatch, communicate_raises=subprocess.TimeoutExpired(
        cmd="claude", timeout=1))
    with pytest.raises(LlmTimeoutError):
        adapter.generate("prompt")


def test_cancel_still_wins_over_timeout(monkeypatch):
    """Slice 2's contract must survive: a shutdown kill surfacing as TimeoutExpired is a
    cancellation, never a timeout — otherwise a restart spends the slice's budget."""
    adapter = _make_adapter()
    adapter.cancel_active()
    _patch_fake_popen(monkeypatch, communicate_raises=subprocess.TimeoutExpired(
        cmd="claude", timeout=1))
    with pytest.raises(LlmCancelledError):
        adapter.generate("prompt")


def test_fast_failures_still_return_none(monkeypatch):
    """Regression guard: a missing binary must NOT become a timeout — a fast failure is
    provider-wide and must stay uncapped."""
    adapter = _make_adapter()
    _patch_fake_popen(monkeypatch, construct_raises=FileNotFoundError("no claude"))
    assert adapter.generate("prompt") is None
```

(`_patch_fake_popen` is illustrative — reuse whatever slice 2 actually named its helper.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py -v -k "timeout or cancel_still or fast_failures"`
Expected: `test_raises_llm_timeout_error_on_timeout` FAILS (that branch still returns
`None`, so nothing is raised); the other two already pass from slice 2.

- [ ] **Step 3: Implement**

In `claude_cli_adapter.py`, the timeout branch currently ends with `return None` (slice 2
left it that way deliberately). Turn that into the signal — keeping slice 2's
cancel-wins-over-timeout check, which must stay FIRST:

```python
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                if self._cancel_event.is_set():
                    # A shutdown kill surfacing as TimeoutExpired is NOT a provider
                    # timeout — a restart must never spend a slice's failure budget.
                    raise LlmCancelledError("claude -p cancelled during shutdown") from None
                logger.warning("claude -p timed out after %ss", timeout)
                raise LlmTimeoutError(f"claude -p timed out after {timeout}s") from None
```

Import `LlmTimeoutError` alongside the `LlmCancelledError` import slice 2 added. Every
OTHER failure path in `generate()` stays exactly as it is — a non-zero exit, a non-JSON
envelope, an `is_error` envelope and a failed process creation all keep returning `None`
(fast failures must never look slice-specific).

`llm_generate` already swallows both types (slice 2), so the maintenance consumers are
unaffected. `ingest_llm_generate` propagates — Task 2 classifies it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_background/test_claude_cli_adapter.py tests/test_background/test_ingest_provider.py -v`
Expected: PASS — the three new cases plus every slice-2 cancellation test still green.

- [ ] **Step 5: Lint + commit**

Provenance-PURE commits (codex R3 — never mix upstream and fork-only files in one commit;
the publish step cherry-picks whole commits):

One commit:

```bash
ruff check src/ tests/
git add src/ormah/background/llm/claude_cli_adapter.py \
        tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): claude_cli raises LlmTimeoutError on a real provider timeout (ADR-0004 slice 3)"
```

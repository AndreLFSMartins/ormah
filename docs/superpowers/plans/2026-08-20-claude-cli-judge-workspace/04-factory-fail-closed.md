### Task 3: The factory resolves the route and degrades fail-closed

**Goal:** `get_adapter` owns the settings-to-path resolution, so the adapter never needs a
`settings` object, and an unsafe workspace takes the route down instead of running the judge.

**Files:**
- Modify: `src/ormah/background/llm/__init__.py` (lines 1–14 imports, `get_adapter` signature at
  line 17, the `claude_cli` branch at lines 55–63)
- Test: `tests/test_background/test_llm_adapters.py`

**Interfaces:**
- Consumes, from Task 1: `ensure_workspace(settings, name) -> Path` and
  `CliWorkspaceUnsafeError`. From Task 2:
  `ClaudeCliAdapter(..., *, workspace_dir: Path)`.
- Produces: `get_adapter(settings, provider=None, model=None, num_ctx=None, workspace="judge")`.
  Returns `None` when the workspace is unsafe.

Why `None` and not a raised exception: `None` is the established "no LLM available" contract in this
codebase — it is exactly what the `provider == "none"` branch returns, and every caller already
handles it. Raising would re-fire on every job because `_get_or_create_adapter` only caches on
success. The cost is that a configuration error becomes a quiet `None`, so the ERROR log is the only
signal and its wording matters.

Why `workspace` lives here and not on the adapter: the 2026-08-19 brainstorming (recorded as
DECISÃO 1) established that cache stability is *per route*, because the prefix is what the cache
keys on. Both routes take the default today; splitting them later is passing an argument.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_llm_adapters.py`:

```python
# --- claude_cli: workspace resolution and fail-closed degradation ---

class _FakeClaudeSettings:
    llm_provider: str = "claude_cli"
    llm_model: str = "claude-haiku-4-5"
    claude_cli_timeout_seconds: int = 160
    claude_cli_bin: str = "/bin/claude"
    claude_cli_max_concurrency: int = 1

    def __init__(self, memory_dir):
        self.memory_dir = memory_dir


def test_get_adapter_hands_the_resolved_workspace_to_the_adapter(tmp_path):
    settings = _FakeClaudeSettings(memory_dir=tmp_path / "data" / "memory")

    adapter = get_adapter(settings)

    expected = tmp_path / "data" / "cli-workspace" / "judge"
    assert adapter.workspace_dir == expected
    # The factory does the materialising, so the file is on disk before any call is made.
    assert (expected / "CLAUDE.md").exists()


def test_get_adapter_uses_the_route_name_for_the_workspace(tmp_path):
    settings = _FakeClaudeSettings(memory_dir=tmp_path / "data" / "memory")

    adapter = get_adapter(settings, workspace="ingest")

    assert adapter.workspace_dir == tmp_path / "data" / "cli-workspace" / "ingest"


def test_get_adapter_returns_none_and_logs_when_the_workspace_is_unsafe(tmp_path, caplog):
    import logging

    settings = _FakeClaudeSettings(memory_dir=tmp_path / "data" / "memory")
    unsafe = tmp_path / "data" / "cli-workspace" / "judge" / ".claude"
    unsafe.mkdir(parents=True)

    with caplog.at_level(logging.ERROR, logger="ormah.background.llm"):
        adapter = get_adapter(settings)

    # None is the established "no LLM available" contract -- the same thing provider="none"
    # returns -- so the route degrades through a path every caller already handles.
    assert adapter is None
    assert str(unsafe) in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_llm_adapters.py -q 2>&1 | tail -6
```

Expected: failures. The first two fail with
`TypeError: __init__() missing 1 required keyword-only argument: 'workspace_dir'` (the factory does
not pass it yet); the third fails on `assert adapter is None` because no exception is caught yet.

- [ ] **Step 3: Write the minimal implementation**

In `src/ormah/background/llm/__init__.py`:

**(a)** Add a module logger. After the existing imports at the top of the file:

```python
import logging

from ormah.background.llm.base import LLMAdapter
from ormah.background.llm.normalize import normalize_conflict_type, normalize_link_type

logger = logging.getLogger(__name__)
```

**(b)** Add the parameter to the signature (line 17), keeping the existing ones unchanged:

```python
def get_adapter(settings, provider: str | None = None, model: str | None = None,
                num_ctx: int | None = None, workspace: str = "judge") -> LLMAdapter | None:
```

**(c)** Replace the whole `claude_cli` branch:

```python
    if provider == "claude_cli":
        from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
        from ormah.background.llm.cli_workspace import CliWorkspaceUnsafeError, ensure_workspace

        # Resolution lives HERE, not in the adapter: the adapter then never needs a settings
        # object, and the guard runs once per cached adapter rather than once per call.
        try:
            workspace_dir = ensure_workspace(settings, workspace)
        except CliWorkspaceUnsafeError as exc:
            # Fail closed by degrading the route, not by raising: None is what provider="none"
            # returns, so every caller already handles it, and _get_or_create_adapter caches it
            # instead of re-raising on every job. This log is the ONLY signal -- keep it loud.
            logger.error("claude_cli route disabled: %s", exc)
            return None

        return ClaudeCliAdapter(
            model=model or settings.llm_model,
            timeout=settings.claude_cli_timeout_seconds,
            bin_path=settings.claude_cli_bin,
            max_concurrency=settings.claude_cli_max_concurrency,
            workspace_dir=workspace_dir,
        )
```

Also extend the factory's existing docstring with one sentence, so the next reader learns the
contract without opening this plan:

```python
    ``workspace`` names the judge workspace (hence the cache prefix) for this route; the two
    call sites in ``llm_client.py`` share the default today. Returns ``None`` when the resolved
    workspace is unsafe, which takes the route down rather than running the judge.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_llm_adapters.py -q 2>&1 | tail -3
```

Expected: all tests in the file pass, including the 3 new ones.

- [ ] **Step 5: Run the full suite — this is the first task that can break unrelated callers**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `1 failed, 2642 passed, 12 deselected`, the single failure being the known baseline one
from `test_conflict_claims_investigation.py`. Tasks 1–3 add 14 passing tests (8 + 3 + 3) to the
2628 baseline.

Any *other* FAILED line means a caller elsewhere constructs `ClaudeCliAdapter` directly and now
misses `workspace_dir`. Find it and route it through `get_adapter` rather than adding a default:

```bash
grep -rn "ClaudeCliAdapter(" src/ tests/
```

- [ ] **Step 6: Confirm ruff is clean**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
git add src/ormah/background/llm/__init__.py tests/test_background/test_llm_adapters.py
git commit -m "feat(llm): resolve the judge workspace in the factory, fail closed on unsafe

get_adapter owns the settings-to-path resolution so the adapter never needs a
settings object and the guard runs once per cached adapter. An unsafe workspace
returns None -- the same contract provider=none already returns -- so the route
degrades through a path every caller handles.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git show --stat HEAD | head -6
```

Expected: exactly 2 files in the commit stat.

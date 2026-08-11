### Task 03: Ingest-only provider routing + config

Route extraction through a SEPARATE `ingest_llm_provider` so setting it to `claude_cli` does NOT
migrate the maintenance jobs (auto_linker/consolidator/conflict_detector/duplicate_merger), which
keep using the global `llm_provider`. `_extract_memories_llm` switches to a dedicated
`ingest_llm_generate` with its own cached adapter.

**Files:**
- Modify: `src/ormah/config.py` (settings ~line 44–50; enum `_llm_provider_enum` ~line 251–256)
- Modify: `src/ormah/background/llm/__init__.py` (`get_adapter`, line 16–42)
- Modify: `src/ormah/background/llm_client.py` (add ingest adapter cache + `ingest_llm_generate`)
- Modify: `src/ormah/engine/memory_engine.py` (`_extract_memories_llm`, ~line 1975)
- Test: `tests/test_background/test_ingest_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_background/test_ingest_provider.py
from ormah.background.llm import get_adapter
from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter
from ormah.background.llm.ollama_adapter import OllamaAdapter
from ormah.config import Settings


def test_get_adapter_provider_override_beats_settings():
    s = Settings(llm_provider="ollama")
    assert isinstance(get_adapter(s, provider="claude_cli"), ClaudeCliAdapter)
    assert isinstance(get_adapter(s), OllamaAdapter)  # unchanged when no override


def test_settings_accepts_claude_cli_and_ingest_provider():
    s = Settings(llm_provider="ollama", ingest_llm_provider="claude_cli")
    assert s.ingest_llm_provider == "claude_cli"


def test_ingest_provider_falls_back_to_llm_provider_when_empty():
    from ormah.background.llm_client import _resolve_ingest_provider
    assert _resolve_ingest_provider(Settings(llm_provider="ollama")) == "ollama"
    assert _resolve_ingest_provider(
        Settings(llm_provider="ollama", ingest_llm_provider="claude_cli")
    ) == "claude_cli"


def test_extraction_uses_ingest_adapter_not_maintenance(monkeypatch):
    # ingest_llm_generate must build from ingest_llm_provider, leaving llm_provider for maintenance.
    from ormah.background import llm_client
    llm_client.reset_adapter()
    s = Settings(llm_provider="ollama", ingest_llm_provider="claude_cli")
    captured = {}
    monkeypatch.setattr(llm_client, "get_adapter",
                        lambda settings, provider=None: captured.setdefault("provider", provider))
    llm_client.ingest_llm_generate(s, "prompt")
    assert captured["provider"] == "claude_cli"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_background/test_ingest_provider.py -v`
Expected: FAIL — `ingest_llm_provider` field missing, `get_adapter` has no `provider` kwarg,
`ingest_llm_generate` / `_resolve_ingest_provider` do not exist.

- [ ] **Step 3a: Config — settings + enum**

In `src/ormah/config.py`, after the `llm_*` fields:

```python
    # Extraction LLM — routed separately from llm_provider so enabling claude_cli for ingest
    # does NOT migrate the maintenance jobs. Empty string falls back to llm_provider.
    ingest_llm_provider: str = ""
    # Claude CLI extractor settings (provider="claude_cli").
    claude_cli_model: str = "haiku"
    claude_cli_timeout_seconds: int = 120
    claude_cli_bin: str | None = None
    claude_cli_workdir: str = "/tmp/ormah-extractor"
    claude_cli_max_concurrency: int = 1
```

In `_llm_provider_enum` (~line 254), change `allowed = {"ollama", "litellm", "none"}` to
`allowed = {"ollama", "litellm", "claude_cli", "none"}`. Add the same validator for
`ingest_llm_provider` allowing the same set plus `""`:

```python
    @field_validator("ingest_llm_provider")
    @classmethod
    def _ingest_llm_provider_enum(cls, v: str) -> str:
        allowed = {"", "ollama", "litellm", "claude_cli", "none"}
        if v not in allowed:
            raise ValueError(f"ingest_llm_provider must be one of {allowed}, got {v!r}")
        return v
```

- [ ] **Step 3b: `get_adapter` — optional provider override**

In `src/ormah/background/llm/__init__.py`, change the signature and first line, and add the
`claude_cli` branch:

```python
def get_adapter(settings, provider: str | None = None) -> LLMAdapter | None:
    """Build an adapter. When *provider* is given it overrides ``settings.llm_provider``."""
    provider = provider or settings.llm_provider
    timeout = getattr(settings, "llm_timeout_seconds", 60)
    ...
    if provider == "claude_cli":
        from ormah.background.llm.claude_cli_adapter import ClaudeCliAdapter

        return ClaudeCliAdapter(
            model=settings.claude_cli_model,
            timeout=settings.claude_cli_timeout_seconds,
            bin_path=settings.claude_cli_bin,
            workdir=settings.claude_cli_workdir,
            max_concurrency=settings.claude_cli_max_concurrency,
        )
```

- [ ] **Step 3c: `llm_client` — separate ingest adapter + generate**

In `src/ormah/background/llm_client.py`, add alongside the existing cache:

```python
_cached_ingest_adapter = None
_ingest_adapter_initialised = False


def _resolve_ingest_provider(settings) -> str:
    return settings.ingest_llm_provider or settings.llm_provider


def _get_or_create_ingest_adapter(settings):
    global _cached_ingest_adapter, _ingest_adapter_initialised
    if not _ingest_adapter_initialised:
        _cached_ingest_adapter = get_adapter(settings, provider=_resolve_ingest_provider(settings))
        _ingest_adapter_initialised = True
    return _cached_ingest_adapter


def ingest_llm_generate(settings, prompt, json_mode=True, **kwargs):
    """Generate for server-side extraction, using ingest_llm_provider (not llm_provider)."""
    adapter = _get_or_create_ingest_adapter(settings)
    if adapter is None:
        return None
    return adapter.generate(prompt, json_mode=json_mode, **kwargs)
```

Extend the existing `reset_adapter()` to also clear `_cached_ingest_adapter` /
`_ingest_adapter_initialised` (so tests re-resolve).

- [ ] **Step 3d: Route extraction through it**

In `src/ormah/engine/memory_engine.py`, `_extract_memories_llm` (~line 1975), change the import +
call from `llm_generate` to `ingest_llm_generate`:

```python
            from ormah.background.llm_client import ingest_llm_generate
            ...
            raw = ingest_llm_generate(self.settings, prompt, json_mode=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_background/test_ingest_provider.py -v`
Expected: PASS (4 tests). Then `.venv/bin/python -m pytest tests/ -m 'not integration' -q` — no regression.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/config.py src/ormah/background/llm/__init__.py \
        src/ormah/background/llm_client.py src/ormah/engine/memory_engine.py \
        tests/test_background/test_ingest_provider.py
git commit -m "feat(llm): route extraction via ingest_llm_provider (maintenance stays on llm_provider)"
```

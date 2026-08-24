### Task 5: Give Ollama an input window, and pin it only for consolidation

**Files:**
- Modify: `src/ormah/background/llm/ollama_adapter.py` (accept and emit `num_ctx`)
- Modify: `src/ormah/background/llm/__init__.py` (thread `num_ctx` through `get_adapter`)
- Modify: `src/ormah/background/llm_client.py` (chars→tokens, dedicated adapter, `route=`)
- Modify: `src/ormah/background/consolidator.py` (one call site)
- Create: `tests/test_background/test_llm_client.py`

**Interfaces:**
- Consumes: `Settings.consolidation_max_prompt_chars` (Task 2); `Settings.llm_num_predict`
  (exists upstream, default 4096).
- Produces:
  - `OllamaAdapter(..., num_ctx: int | None = None)` — emits `options["num_ctx"]` only when set
  - `get_adapter(settings, num_ctx: int | None = None)`
  - `llm_generate(..., route: str = "maintenance")` — `route="consolidation"` selects a dedicated
    adapter with `num_ctx = int(consolidation_max_prompt_chars / 2.0) + llm_num_predict`
    (**16096** with the defaults)

**Context you need — this is the half of #192 that is easy to miss.** Removing `content[:300]`
fixes what *our code* truncates. It does not fix what the *provider* truncates.

`OllamaAdapter` today sets only `num_predict`, which bounds the **output**. The **input** window
is `num_ctx`, and because the adapter never sends it, Ollama uses the server/Modelfile default —
commonly 4096 tokens, historically 2048. With the old 300-char cap the consolidation prompt was
~3,700 chars (~950 tokens) and always fit. Carrying full content, it can reach ~12,000 chars on
real data, and Ollama would silently drop the overflow: the same bug as #192, one level down and
invisible to our code, since the HTTP call still returns 200 with a plausible summary.

So the budget and the window must be the same number. But `_get_or_create_adapter` builds the
adapter **shared** by `auto_linker`, `conflict_detector` and `duplicate_merger`, which judge small
pairs — giving all of them a 16k-token KV cache would be a real memory cost for no benefit. Hence
a second, dedicated adapter for the one route that needs it.

`num_ctx=None` must mean **omit the key**, not substitute a default of our own: for every other
caller that leaves the operator's server setting in charge, exactly as today.

Upstream has no `estimated_tokens` helper, so this task defines a local constant.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background/test_llm_client.py`:

```python
"""Tests for the shared LLM facade — adapter routing and input windows."""

from __future__ import annotations

import pytest

from ormah.background import llm_client
from ormah.background.llm.ollama_adapter import OllamaAdapter


class _StubAdapter:
    def generate(self, prompt, **kwargs):
        return "{}"


@pytest.fixture
def captured_num_ctx(monkeypatch):
    """Capture the num_ctx get_adapter is called with, with a clean adapter cache."""
    seen = {}

    def fake_get_adapter(settings, num_ctx=None):
        seen["num_ctx"] = num_ctx
        return _StubAdapter()

    monkeypatch.setattr(llm_client, "get_adapter", fake_get_adapter)
    llm_client.reset_adapter()
    yield seen
    llm_client.reset_adapter()


class TestConsolidationRoute:
    """#192: only the consolidation route pins an input window it can prove."""

    def test_consolidation_route_derives_num_ctx_from_the_budget(self, settings, captured_num_ctx):
        settings.llm_provider = "ollama"
        settings.consolidation_max_prompt_chars = 24000
        settings.llm_num_predict = 4096

        llm_client.llm_generate(settings, "prompt", route="consolidation")

        assert captured_num_ctx["num_ctx"] == 16096  # 24000/2 chars-per-token + 4096 output

    def test_shared_maintenance_adapter_still_omits_num_ctx(self, settings, captured_num_ctx):
        """auto_linker, conflict_detector and duplicate_merger share this adapter and must not
        pay the consolidation KV cache."""
        settings.llm_provider = "ollama"

        llm_client.llm_generate(settings, "prompt")

        assert captured_num_ctx["num_ctx"] is None

    def test_reset_adapter_clears_the_consolidation_cache(self, settings, captured_num_ctx):
        settings.llm_provider = "ollama"
        settings.consolidation_max_prompt_chars = 24000
        settings.llm_num_predict = 4096
        llm_client.llm_generate(settings, "prompt", route="consolidation")

        llm_client.reset_adapter()
        settings.consolidation_max_prompt_chars = 40000
        llm_client.llm_generate(settings, "prompt", route="consolidation")

        assert captured_num_ctx["num_ctx"] == 24096, "the cache was not rebuilt after reset"


class TestOllamaInputWindow:
    """num_ctx=None must OMIT the key, never substitute a default of our own."""

    def test_num_ctx_is_absent_from_the_payload_when_unset(self):
        adapter = OllamaAdapter(model="m")
        assert adapter.num_ctx is None

    def test_num_ctx_reaches_the_ollama_options(self, monkeypatch):
        sent = {}

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "{}"}

        def fake_post(url, json=None, timeout=None):
            sent.update(json)
            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "post", fake_post)

        OllamaAdapter(model="m", num_ctx=16096).generate("p")
        assert sent["options"]["num_ctx"] == 16096

        sent.clear()
        OllamaAdapter(model="m").generate("p")
        assert "num_ctx" not in sent["options"]
```

- [ ] **Step 2: Run them and verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_llm_client.py -v > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL — `TypeError: OllamaAdapter.__init__() got an unexpected keyword argument
'num_ctx'` and `TypeError: llm_generate() got an unexpected keyword argument 'route'`.

- [ ] **Step 3: Teach OllamaAdapter the input window**

In `src/ormah/background/llm/ollama_adapter.py`, change `__init__` to:

```python
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: int = 60,
        num_predict: int = 4096,
        num_ctx: int | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.num_predict = num_predict
        # INPUT window. num_predict bounds the OUTPUT only; leaving num_ctx unset inherits the
        # server's default, which we neither control nor version. A default below the payload
        # truncates the prompt SILENTLY -- the HTTP call still returns 200 with a plausible
        # answer, so nothing surfaces.
        #
        # None means OMIT the key, NOT "substitute a default of our own": a number invented here
        # would silently NARROW every caller that today leaves the operator's server/Modelfile
        # setting in charge. Only the consolidation route opts in (#192), because it is the one
        # route whose prompt carries full source content.
        self.num_ctx = num_ctx
```

and in `generate`, change the options block to:

```python
        options: dict = {"num_predict": max_tokens or self.num_predict}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if temperature is not None:
            options["temperature"] = temperature
```

- [ ] **Step 4: Thread it through get_adapter**

In `src/ormah/background/llm/__init__.py`, change the signature and the Ollama branch:

```python
def get_adapter(settings, num_ctx: int | None = None) -> LLMAdapter | None:
    """Build an adapter from the application settings.

    Returns ``None`` when ``llm_provider`` is ``"none"``.

    ``num_ctx`` is a parameter rather than a settings read on purpose: this factory builds the
    adapter SHARED by every maintenance job, and wiring a large input window unconditionally
    would give small pair-judging calls a large KV cache for no benefit. Only the consolidation
    route opts in (#192).
    """
    provider = settings.llm_provider
    timeout = getattr(settings, "llm_timeout_seconds", 60)

    if provider == "ollama":
        from ormah.background.llm.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=timeout,
            num_predict=getattr(settings, "llm_num_predict", 4096),
            num_ctx=num_ctx,
        )
```

Leave the `litellm` and `none` branches untouched — a remote provider errors on an oversized
prompt instead of truncating it, so it needs no window of ours.

- [ ] **Step 5: Add the dedicated adapter and the route**

In `src/ormah/background/llm_client.py`, next to `_cached_adapter`, add:

```python
_cached_consolidation_adapter: LLMAdapter | None = None
_consolidation_adapter_initialised: bool = False

# Chars per token assumed when converting a character budget into an input window. English prose
# runs ~4 chars/token; 2.0 is a deliberate 2x safety margin, so a denser payload (hex digests,
# base64, CJK) still fits the window we ask for. Erring large costs KV cache; erring small costs
# a silently truncated prompt, which is the failure #192 exists to remove.
_CHARS_PER_TOKEN = 2.0
```

Replace `reset_adapter` with:

```python
def reset_adapter() -> None:
    """Clear the cached adapters (useful for test isolation)."""
    global _cached_adapter, _adapter_initialised
    global _cached_consolidation_adapter, _consolidation_adapter_initialised
    _cached_adapter = None
    _adapter_initialised = False
    _cached_consolidation_adapter = None
    _consolidation_adapter_initialised = False
```

After `_get_or_create_adapter`, add:

```python
def _consolidation_num_ctx(settings) -> int:
    """The input window the consolidation route needs, derived from the budget it packs against.

    Both sides of the call use the same number: the splitter fills at most
    ``consolidation_max_prompt_chars``, and this converts that to tokens, leaving room for the
    model's own output budget.
    """
    return int(settings.consolidation_max_prompt_chars / _CHARS_PER_TOKEN) + (
        settings.llm_num_predict
    )


def _get_or_create_consolidation_adapter(settings) -> LLMAdapter | None:
    global _cached_consolidation_adapter, _consolidation_adapter_initialised
    if not _consolidation_adapter_initialised:
        # Consolidation is the ONE maintenance route whose prompt carries full source content
        # (#192), and its output DISPLACES that content: every source is demoted to archival the
        # moment the summary is written. Inheriting the operator's server default here would let
        # Ollama truncate the prompt silently -- exactly the bug #192 fixes, one level down. The
        # SHARED adapter above deliberately passes no num_ctx: auto_linker, conflict_detector and
        # duplicate_merger judge small pairs and must not pay this KV cache.
        _cached_consolidation_adapter = get_adapter(
            settings, num_ctx=_consolidation_num_ctx(settings)
        )
        _consolidation_adapter_initialised = True
    return _cached_consolidation_adapter
```

Replace `llm_generate` with:

```python
def llm_generate(
    settings,
    prompt: str,
    json_mode: bool = True,
    *,
    response_format: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    route: str = "maintenance",
) -> str | None:
    """Call configured LLM. Returns raw response text, or None on failure.

    ``route="consolidation"`` selects the adapter that pins its own input window (#192); every
    other route shares the maintenance adapter, which leaves the window to the operator.
    """
    adapter = (
        _get_or_create_consolidation_adapter(settings)
        if route == "consolidation"
        else _get_or_create_adapter(settings)
    )
    if adapter is None:
        return None
    return adapter.generate(
        prompt,
        json_mode=json_mode,
        response_format=response_format,
        temperature=temperature,
        max_tokens=max_tokens,
    )
```

- [ ] **Step 6: Use the route from the consolidator**

In `src/ormah/background/consolidator.py`, in `_consolidate_cluster`, change:

```python
    raw = llm_generate(engine.settings, prompt, json_mode=True)
```

to:

```python
    raw = llm_generate(engine.settings, prompt, json_mode=True, route="consolidation")
```

- [ ] **Step 7: Run the new tests and verify they pass**

Same command as Step 2. Expected: 5 passed, `PYTEST_EXIT=0`.

- [ ] **Step 8: Run the whole suite and lint, with the import gate**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; tail -30 out.txt
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -m ruff check src/ tests/
```

Expected: the import path contains `ormah-wt-192/`, `PYTEST_EXIT=0`, ruff clean. Cite this output
when reporting completion — a `DONE` without it is not evidence.

- [ ] **Step 9: Commit**

```bash
git add src/ormah/background/llm/ollama_adapter.py src/ormah/background/llm/__init__.py \
        src/ormah/background/llm_client.py src/ormah/background/consolidator.py \
        tests/test_background/test_llm_client.py
git commit -m "fix(llm): give Ollama an input window and pin it for consolidation (#192)

Removing content[:300] is only half the fix. OllamaAdapter set num_predict
(output) but never num_ctx (input), so the server's own default decided how
much of the prompt was read — and silently dropped the rest. With the 300-char
cap the prompt always fit; carrying full content it does not.

get_adapter now threads an optional num_ctx, and llm_generate gains
route='consolidation', which selects a dedicated adapter whose window is
derived from consolidation_max_prompt_chars — the same budget the splitter
packs against. num_ctx=None still omits the key entirely, so every other
caller keeps the operator's server setting."
```

- [ ] **Step 10: Verify the island is clean before pushing**

```bash
git log --oneline upstream/main..HEAD
```

Expected: exactly the five commits from Tasks 1–5 and nothing else. Anything you did not write
means the branch was cut from the wrong base — rebuild the island before pushing.

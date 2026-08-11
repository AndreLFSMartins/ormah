# Task 5: Make the bigger payload safe on any provider

**Files:**
- Modify: `src/ormah/config.py` (two new settings + validators)
- Modify: `src/ormah/engine/memory_engine.py:2849-2868` (payload-derived timeout)
- Modify: `src/ormah/background/llm/ollama_adapter.py:13-50` (pin `num_ctx`)
- Create: `src/ormah/ingest_capacity.py` (shared capacity arithmetic)
- Modify: `CONTEXT.md` (the minimum-window requirement)
- Test: `tests/test_engine/test_ingest_extraction.py`
- Do **not** touch `docs/adr/0001-batch-size-and-ordering.md` here — Task 7 owns every ADR edit.

**Interfaces:**
- Consumes: Task 3/4's settings.
- Produces:
  - `Settings.ingest_timeout_per_10k_chars: float = 60.0` (provisional — Task 6 measures it)
  - `Settings.ingest_timeout_max_seconds: int = 900`
  - `Settings.ollama_num_ctx: int = 65536`
  - `OllamaAdapter(model, base_url, timeout, num_predict, num_ctx=65536)`
  - `_ingest_adapter_baseline_timeout(settings) -> int` in `memory_engine.py`

## ⛔ The hint must never LOWER the provider's own timeout (council R1, both peers)

Verified: `llm/__init__.py:47` builds `ClaudeCliAdapter(timeout=settings.claude_cli_timeout_seconds)`
= **120**, while `ollama`/`litellm` get `llm_timeout_seconds` = **60**. And every adapter does
`timeout = timeout_hint_seconds or self.timeout` (`claude_cli_adapter.py:199`) — a hint **replaces**
the default, it never raises it.

So a naive `llm_timeout_seconds + rate * size` gives a 4K chunk **84s under `claude_cli`**, below
today's 120s. That is a regression on the *common short-flush path* (idle flush, SessionEnd nudge)
while only helping full batches — strictly worse than doing nothing. The hint is therefore a
**floor-raising** formula, and the floor is the **active adapter's own baseline**:

```
hint = min(max(baseline, base + rate * len(rendered_prompt) / 10000), ingest_timeout_max_seconds)
```

Two further consequences, both load-bearing:

- The size term uses `len(prompt)` — the **rendered** prompt after `_INGEST_LLM_PROMPT.format(...)` —
  not `len(chunk)`. The template and schema are real tokens the provider must read.
- `baseline` is resolved from the **ingest** provider (`ingest_llm_provider` falling back to
  `llm_provider`), not from a global constant.

**The problem this closes.** `_extract_memories_llm` sends a **variable** payload against a **fixed**
provider timeout and never uses the `timeout_hint_seconds` seam — even though that seam is in the base
protocol (`llm/base.py:20`) and honoured by all three adapters. Today's payload is ~3.4K chars, so it
never bites. After Task 1 it is ~60000 chars. This is provider-agnostic: `claude_cli_timeout_seconds`
is 120 and `llm_timeout_seconds` is 60, and a local model measured 24.7s of prompt evaluation alone for
a 56K-char prompt before generating a single token.

The idiom already exists in this repo — copy it, do not invent one (`llm/pair_batch.py:86`):

```python
hint = settings.llm_timeout_seconds + settings.maintenance_timeout_per_pair_seconds * len(idx)
```

**Two axes, do not conflate them.** *Latency* varies per provider and is handled by the derived
timeout. *Capacity* (context window) is NOT handled by resizing the batch — ADR-0001 Amendment 1
rejects window-fraction sizing. 60000 chars ≈ 15K tokens, so the requirement is a modest
"≥16K tokens of usable input window", documented, and — for Ollama only — pinned rather than inherited.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine/test_ingest_extraction.py`:

```python
def test_extraction_passes_a_payload_proportional_timeout_hint(tmp_path):
    """A variable payload against a fixed provider timeout is the bug. The hint must grow with
    the payload, using the same base+rate idiom as pair_batch."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 1000)
            small = hints[-1]
            engine._extract_memories_llm("x" * 50000)
            large = hints[-1]
    finally:
        engine.shutdown()

    assert small is not None, "ingest still sends no timeout hint at all"
    assert large > small, "the hint does not scale with the payload"


def test_timeout_hint_never_lowers_the_active_provider_baseline(tmp_path):
    """Council R1, both peers: adapters treat the hint as a REPLACEMENT
    (`timeout_hint_seconds or self.timeout`), and claude_cli's own baseline is 120s while
    llm_timeout_seconds is 60s. A hint derived from the 60s base would hand a short flush 84s --
    a regression on the most common path. The hint must be a floor-raiser, never a reducer."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(
        memory_dir=tmp_path, ingest_llm_provider="claude_cli", ingest_llm_model="haiku",
    )
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 1000)   # tiny: the derived term is negligible
    finally:
        engine.shutdown()

    assert hints[-1] >= settings.claude_cli_timeout_seconds, (
        f"hint {hints[-1]}s is BELOW the claude_cli baseline "
        f"{settings.claude_cli_timeout_seconds}s -- this regresses short flushes"
    )


def test_extraction_timeout_hint_is_bounded(tmp_path):
    """A hung provider must not be waited on indefinitely just because the payload was big."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path, ingest_timeout_max_seconds=100)
    engine = MemoryEngine(settings)
    engine.startup()
    hints = []

    def fake_generate(settings, prompt, **kwargs):
        hints.append(kwargs.get("timeout_hint_seconds"))
        return '{"memories": []}'

    try:
        with patch(
            "ormah.background.llm_client.ingest_llm_generate", side_effect=fake_generate,
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            engine._extract_memories_llm("x" * 60000)
    finally:
        engine.shutdown()

    assert hints[-1] <= 100


def test_ollama_adapter_pins_the_input_window():
    """num_predict bounds OUTPUT; num_ctx bounds INPUT. Leaving num_ctx unset inherits the
    Ollama server's default, which we neither control nor version -- and a default below the
    payload truncates the prompt SILENTLY, killing recall with no signal."""
    from ormah.background.llm.ollama_adapter import OllamaAdapter

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _Resp()

    import httpx
    original = httpx.post
    httpx.post = fake_post
    try:
        OllamaAdapter(model="gemma3:12b-it-qat", num_ctx=70000).generate("hello")
    finally:
        httpx.post = original

    assert captured["options"]["num_ctx"] == 70000
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/test_engine/test_ingest_extraction.py -k "timeout_hint or num_ctx" -v
```

Expected: FAIL — `assert None is not None` (no hint sent), `AttributeError` for the new settings, and
`KeyError: 'num_ctx'`.

- [ ] **Step 3: Add the settings**

In `src/ormah/config.py`, next to `ingest_chunk_chars`:

```python
    # The ingest payload is variable (a Batch is sized to the recall sweet spot), so the provider
    # timeout must be DERIVED from it rather than fixed -- otherwise the batch size is silently
    # capped by whichever provider is configured. Same base+rate idiom as pair_batch.py.
    ingest_timeout_per_10k_chars: float = 60.0   # provisional; measured in Task 6
    ingest_timeout_max_seconds: int = 900        # absolute bound for a hung provider
```

And next to the other Ollama settings:

```python
    ollama_num_ctx: int = 65536   # INPUT window; never inherit the server default (silent truncation)
```

Add the validators:

```python
    @field_validator("ingest_timeout_per_10k_chars")
    @classmethod
    def _ingest_timeout_rate_non_negative(cls, v: float) -> float:
        # >= 0, NOT > 0 (council R2, Cursor): Task 6 legitimately derives a rate of 0.0 when the
        # provider completes a full batch inside its own baseline. Rejecting 0 would make the
        # measured default unlandable and push the operator into inventing a positive number.
        # 0.0 means "no size term" -- max(baseline, ...) from the hint formula then governs.
        if v < 0:
            raise ValueError(f"ingest_timeout_per_10k_chars must be >= 0, got {v}")
        return v

    @field_validator("ingest_timeout_max_seconds")
    @classmethod
    def _ingest_timeout_max_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"ingest_timeout_max_seconds must be >= 1, got {v}")
        return v
```

⛔ **The `min` cap must not defeat the floor** (council R3, Codex). `min(max(baseline, derived), max)`
still returns `max` when `max < baseline` — e.g. `claude_cli` (baseline 120) with
`ingest_timeout_max_seconds=100` emits a 100s hint, recreating the exact regression this section
exists to remove. Add the cross-field guard to the same `model_validator` Task 3/4 built:

```python
        _baseline = (
            self.claude_cli_timeout_seconds
            if (self.ingest_llm_provider or self.llm_provider) == "claude_cli"
            else self.llm_timeout_seconds
        )
        if self.ingest_timeout_max_seconds < _baseline:
            raise ValueError(
                f"ingest_timeout_max_seconds ({self.ingest_timeout_max_seconds}) must be >= the "
                f"active ingest provider's own timeout ({_baseline}); a lower cap makes the hint "
                "SHORTEN the provider's budget, which is the short-flush regression the derived "
                "timeout exists to prevent"
            )
```

with the matching test:

```python
def test_timeout_max_below_the_provider_baseline_is_rejected():
    with pytest.raises(ValidationError):
        Settings(ingest_llm_provider="claude_cli", ingest_llm_model="haiku",
                 ingest_timeout_max_seconds=100)   # claude_cli baseline is 120
```

- [ ] **Step 4: Derive the timeout in the ingest path**

In `src/ormah/engine/memory_engine.py`, inside `_extract_memories_llm`, replace the
`ingest_llm_generate(...)` call (`:2862-2868`) with:

First add the baseline resolver, next to `_extract_memories_llm`:

```python
def _ingest_adapter_baseline_timeout(settings) -> int:
    """The timeout the ACTIVE ingest adapter would use on its own.

    Adapters treat timeout_hint_seconds as a REPLACEMENT (`timeout_hint_seconds or self.timeout`),
    so a hint below this baseline silently shortens the provider's own budget. claude_cli is built
    with claude_cli_timeout_seconds (120) while ollama/litellm get llm_timeout_seconds (60), so the
    baseline is provider-specific and must be resolved, never assumed (llm/__init__.py:22,47).
    """
    provider = settings.ingest_llm_provider or settings.llm_provider
    if provider == "claude_cli":
        return settings.claude_cli_timeout_seconds
    return settings.llm_timeout_seconds
```

Then the call site — note the size term uses the **rendered** prompt, not the bare chunk:

```python
                baseline = _ingest_adapter_baseline_timeout(self.settings)
                derived = (
                    self.settings.llm_timeout_seconds
                    + self.settings.ingest_timeout_per_10k_chars * (len(prompt) / 10000)
                )
                # max(): the hint must RAISE the provider's budget, never lower it.
                hint = min(
                    max(float(baseline), derived),
                    float(self.settings.ingest_timeout_max_seconds),
                )
                raw = ingest_llm_generate(
                    self.settings, prompt, json_mode=True,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"schema": _INGEST_RESPONSE_SCHEMA},
                    },
                    timeout_hint_seconds=hint,
                )
```

Verify `ingest_llm_generate` forwards the keyword; if its signature lacks
`timeout_hint_seconds`, add it there mirroring `llm_generate` (`llm_client.py:161-182`).

- [ ] **Step 5: Pin the Ollama input window**

In `src/ormah/background/llm/ollama_adapter.py`, extend `__init__`:

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
        # INPUT window. num_predict bounds output only; leaving num_ctx unset inherits the
        # server's default, which is neither controlled nor versioned by us. A default below the
        # payload truncates the prompt SILENTLY -- recall dies with no error, which is the exact
        # failure class ADR-0001/0003/0004 exist to eliminate.
        self.num_ctx = num_ctx
```

and the options dict in `generate` (`:37`):

```python
        options: dict = {
            "num_predict": max_tokens or self.num_predict,
            "num_ctx": self.num_ctx,
        }
```

⛔ **The large window belongs to INGEST only** (council R3, Codex). `get_adapter` builds *both* the
maintenance adapter and the ingest adapter, so wiring `ollama_num_ctx` unconditionally would give every
maintenance pair-judging call a 65536-token KV cache — a large memory cost, and a plausible OOM on a
local machine, even for users whose ingest runs on `claude_cli`. Thread it as a parameter and let only
the ingest path opt in:

```python
def get_adapter(settings, provider: str | None = None, model: str | None = None,
                num_ctx: int | None = None) -> LLMAdapter | None:
    ...
    if provider == "ollama":
        from ormah.background.llm.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=model or settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=timeout,
            num_predict=getattr(settings, "llm_num_predict", 4096),
            # None -> the adapter's modest default. Maintenance judges small pairs and must not
            # pay for the ingest window.
            num_ctx=num_ctx,
        )
```

and in `llm_client.py`, only the **ingest** adapter factory passes it:

```python
    adapter = get_adapter(
        settings, provider=ingest_provider, model=ingest_model,
        num_ctx=getattr(settings, "ollama_num_ctx", None),
    )
```

`OllamaAdapter.__init__` therefore keeps a modest default and only raises it when told:

```python
        num_ctx: int | None = None,
```

```python
        self.num_ctx = num_ctx or 8192   # ingest overrides via settings.ollama_num_ctx
```

```bash
grep -rn "OllamaAdapter(" src/ --include='*.py'
```

⛔ **The factory must be in the commit** (council, Codex): an earlier draft told you to wire it but
omitted `llm/__init__.py` from the `git add`, so the shipped adapter would keep its constructor default
while the preflight read the configured value. An operator who follows the error message and raises
`ORMAH_OLLAMA_NUM_CTX` would then get a prompt the preflight admits and the real adapter truncates —
the exact silent loss this guard exists to stop. A direct-constructor test cannot catch it; test the
factory:

```python
def test_factory_passes_configured_num_ctx_to_the_request():
    """The constructor default must never be what ships -- the value an operator sets has to reach
    the actual HTTP request."""
    from ormah.background.llm import get_adapter
    from ormah.config import Settings

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    import httpx
    original = httpx.post
    httpx.post = lambda url, json=None, timeout=None: (captured.update(json), _Resp())[1]
    try:
        # 70000, not 8192: the boot validator rejects a window too small for the worst
        # payload, so an 8192 fixture would ValidationError before reaching the factory.
        settings = Settings(llm_provider="ollama", llm_model="gemma3:12b-it-qat", ollama_num_ctx=70000)
        get_adapter(settings).generate("hello")
    finally:
        httpx.post = original

    assert captured["options"]["num_ctx"] == 70000

- [ ] **Step 5b: Fail loud instead of truncating silently (council R3, Codex — conceded)**

I challenged Codex to name a concrete provider + content combination where a 32768-token window
truncates this batch. It did: **token-dense content** — base64, minified blobs, hashes, non-Latin
script — tokenizes far worse than ~4 chars/token, so 60000 chars can exceed the ~28K usable input
(32768 minus the 4096 output reserve). `litellm` can also be pointed at a model below the requirement.
And crucially: **after this change such payloads are far more reachable than under the old byte
budget**, because batches are ~18x larger. If Ollama truncates and still returns valid JSON, the
extraction looks successful and the cursor advances — facts lost with no error.

That is the plan's own worst failure mode, so the documentation-only stance does not hold. The fix is
**not** token-exact budgeting (still out of scope, ADR-0001 Amendment 1): it is a **preflight that
refuses to send** a call that cannot fit.

**Two numbers, both forced by the council's arithmetic.** At 2.5 chars/token against the original
32768 window (usable 28672), a 60000-char prompt estimates 24000 and is accepted — so anything denser
than `60000/28672 ≈ 2.09` chars/token still overflows, which is precisely the token-dense class this
guard targets. Tightening the divisor alone does not work: at 2.0 chars/token a full batch estimates
30000 > 28672 and **every** full batch would be refused. The window is what has to move:

- `_DENSE_CHARS_PER_TOKEN = 2.0` — below the 2.09 overflow threshold, so the estimate is an upper
  bound for realistic dense content rather than an average.
- `ollama_num_ctx` default rises **32768 → 65536** (usable 61440). A full rendered batch estimates
  ~31500 at 2.0, leaving ~2x headroom; even implausibly dense 1.5 chars/token content fits.

**Cost, stated plainly:** a 65536-token KV cache is a real memory cost on the local machine for a 12B
model. It is a *default*, tunable down — and the boot validator below makes tuning it down fail loudly
instead of silently truncating. Users on `claude_cli` (the current ingest provider) are unaffected.

Both the boot validator and the runtime preflight must use the **same** estimator, or the boot
guarantee is fiction. Put it in a neutral module — `config.py` cannot import `memory_engine` (that
module already imports `Settings`, so it would cycle). Create `src/ormah/ingest_capacity.py`:

```python
"""Shared capacity arithmetic for ingest payloads.

Deliberately dependency-free: `config.py` and `engine/memory_engine.py` both import it, and
importing either from the other would cycle. The boot validator and the runtime preflight MUST
use the same numbers — a boot check computed differently from the runtime check guarantees
nothing.
"""

# Upper bound for token-dense content (base64, minified blobs, hashes, non-Latin script, heavy
# PT-BR diacritics), NOT the ~4 chars/token average used for documentation. Chosen below the
# 60000/28672 ≈ 2.09 overflow threshold the council computed.
_DENSE_CHARS_PER_TOKEN = 2.0


def prompt_overhead_chars() -> int:
    """Chars the extraction template and schema add around the conversation.

    Computed from the template itself rather than hardcoded, so it cannot go stale when the
    prompt is edited.
    """
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT  # local: avoids an import cycle

    return len(_INGEST_LLM_PROMPT.format(conversation=""))


def estimated_tokens(chars: int) -> int:
    return int(chars / _DENSE_CHARS_PER_TOKEN)


def usable_input_tokens(settings) -> int:
    return settings.ollama_num_ctx - settings.llm_num_predict
```

with a staleness test:

```python
def test_prompt_overhead_tracks_the_real_template():
    """If the extraction prompt grows and this drifts, the boot guarantee silently weakens."""
    from ormah.engine.memory_engine import _INGEST_LLM_PROMPT
    from ormah.ingest_capacity import prompt_overhead_chars

    assert prompt_overhead_chars() == len(_INGEST_LLM_PROMPT.format(conversation=""))
    assert prompt_overhead_chars() > 100   # a plausible template, not an empty string
```

```python
def _prompt_exceeds_provider_capacity(settings, prompt: str) -> int | None:
    """Usable input tokens the prompt would overflow, or None when it fits / is unknown.

    Deliberately conservative and estimate-based: the goal is to convert a SILENT truncation into
    a LOUD, retryable failure, not to be exact. Only providers whose window we actually control
    are checked -- for the rest, capacity stays a documented requirement (there is nothing to
    introspect, and inventing a limit would reject valid work).
    """
    from ormah.ingest_capacity import estimated_tokens, usable_input_tokens

    provider = settings.ingest_llm_provider or settings.llm_provider
    if provider != "ollama":
        return None
    usable = usable_input_tokens(settings)
    estimated = estimated_tokens(len(prompt))
    return estimated if estimated > usable else None
```

Wire it in `_extract_memories_llm`, before the call:

```python
                overflow = _prompt_exceeds_provider_capacity(self.settings, prompt)
                if overflow is not None:
                    logger.error(
                        "ingest extraction: rendered prompt ~%d tokens exceeds the usable input "
                        "window (%d); REFUSING to send rather than let the provider truncate "
                        "silently and advance the cursor over unextracted content. Lower "
                        "ORMAH_SESSION_WATCHER_FLUSH_CHARS or raise ORMAH_OLLAMA_NUM_CTX.",
                        overflow, self.settings.ollama_num_ctx - self.settings.llm_num_predict,
                    )
                    return EXTRACT_ERR_CALL_FAILED   # retryable; the cursor must NOT advance
```

Test it:

```python
def test_capacity_preflight_refuses_an_oversized_prompt():
    """Unit-test the estimator directly.

    It cannot be driven through Settings any more: the boot validator now rejects any config whose
    window is too small for the largest emittable payload, which is exactly what makes the runtime
    refusal unreachable in normal operation. The preflight stays as a guard against paths that
    bypass validation (mutated engine.settings, a future config route) and against content denser
    than the estimator's bound.
    """
    from types import SimpleNamespace

    from ormah.engine.memory_engine import _prompt_exceeds_provider_capacity

    tight = SimpleNamespace(
        ingest_llm_provider="ollama", llm_provider="ollama",
        ollama_num_ctx=8192, llm_num_predict=4096,   # usable 4096 tokens
    )
    assert _prompt_exceeds_provider_capacity(tight, "x" * 60000) is not None
    assert _prompt_exceeds_provider_capacity(tight, "x" * 100) is None

    # Non-ollama providers are not introspectable, so the guard must stay silent rather than
    # invent a limit and reject valid work.
    other = SimpleNamespace(ingest_llm_provider="claude_cli", llm_provider="claude_cli")
    assert _prompt_exceeds_provider_capacity(other, "x" * 10_000_000) is None


def test_refusal_returns_the_retryable_sentinel_and_sends_nothing(tmp_path):
    """When the guard does fire, nothing may reach the provider and the cursor must not advance."""
    from unittest.mock import patch

    from ormah.config import Settings
    from ormah.engine.memory_engine import EXTRACT_ERR_CALL_FAILED, MemoryEngine

    (tmp_path / "nodes").mkdir()
    settings = Settings(memory_dir=tmp_path)   # boot-valid
    engine = MemoryEngine(settings)
    engine.startup()
    calls = []

    try:
        # Bypass validation deliberately: this is the path the guard exists to cover.
        engine.settings.ingest_llm_provider = "ollama"
        engine.settings.ollama_num_ctx = 8192
        with patch(
            "ormah.background.llm_client.ingest_llm_generate",
            side_effect=lambda *a, **k: calls.append(1) or '{"memories": []}',
        ), patch(
            "ormah.engine.memory_engine.ingest_provider_configured", return_value=True,
        ):
            out = engine._extract_memories_llm("x" * 60000)
    finally:
        engine.shutdown()

    assert not calls, "the oversized prompt was SENT — the provider will truncate it silently"
    assert out == EXTRACT_ERR_CALL_FAILED, "must return the retryable sentinel, not any string"
```

⛔ **Boot-validate the WORST payload, so the runtime refusal is unreachable.** A capacity refusal
returns `EXTRACT_ERR_CALL_FAILED`, which `session_watcher.py:1044-1047` maps to `TRANSIENT` — the
cursor is held (correct) but the failure never counts toward `MAX_EXTRACT_FAILURES`, so a
*deterministic* overflow requeues that transcript forever. Rather than invent a new terminal failure
state (which would reopen the quarantine design the owner descoped on 2026-07-25), make the
misconfiguration unreachable. Validate against `ingest_max_content_chars`, **not** `flush_chars`: an
oversized single turn bypasses the batch budget via the progress guard and `_split_for_extraction`
then emits chunks up to the hard cap (`memory_engine.py:83-123`).

Add to the same `model_validator` Task 3/4 built:

```python
        if (self.ingest_llm_provider or self.llm_provider) == "ollama":
            from ormah.ingest_capacity import (
                estimated_tokens, prompt_overhead_chars, usable_input_tokens,
            )

            _usable = usable_input_tokens(self)
            _needed = estimated_tokens(self.ingest_max_content_chars + prompt_overhead_chars())
            if _needed > _usable:
                raise ValueError(
                    f"the largest payload ingest can emit (~{_needed} tokens, from "
                    f"ingest_max_content_chars={self.ingest_max_content_chars}) exceeds the usable "
                    f"Ollama input window ({_usable} = ollama_num_ctx {self.ollama_num_ctx} - "
                    f"llm_num_predict {self.llm_num_predict}). Raise ORMAH_OLLAMA_NUM_CTX or lower "
                    "ORMAH_INGEST_MAX_CONTENT_CHARS. Starting anyway would let such a payload fail "
                    "extraction deterministically and retry forever."
                )
```

with both tests:

```python
def test_ollama_window_too_small_for_the_worst_payload_fails_at_boot():
    """Deterministic capacity failure must surface at startup, not as a transcript that retries
    forever (the refusal is TRANSIENT and never reaches the failure cap)."""
    with pytest.raises(ValidationError):
        Settings(ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat",
                 ollama_num_ctx=8192)


def test_default_ollama_window_admits_the_worst_payload():
    """The shipped default must not fail its own boot check."""
    from ormah.ingest_capacity import estimated_tokens, prompt_overhead_chars, usable_input_tokens

    s = Settings(ingest_llm_provider="ollama", ingest_llm_model="gemma3:12b-it-qat")
    worst = estimated_tokens(s.ingest_max_content_chars + prompt_overhead_chars())
    assert worst <= usable_input_tokens(s)
```

**Residual 1 — the char estimate is not a proof.** `len(prompt)` counts Unicode code points, and a
tokenizer can spend *more than one token* on a single code point (emoji, rare scripts). No
chars-per-token divisor is a true upper bound; 2.0 is a strong heuristic, not a guarantee, and the
boot check inherits that limitation. Closing this properly needs model-aware token counting before
dispatch, which means a tokenizer dependency and per-model handling — a separate change. Until then,
an adversarially emoji-dense transcript can still overflow an `ollama` window. Say so in the ADR
(Task 7); do not describe the guard as airtight.

**Residual 2, stated honestly:** this covers `ollama`, the only provider whose window we pin. For
`claude_cli` and `litellm` the window is not introspectable and the requirement stays documentation —
so a `litellm` model below the requirement can still truncate silently, and a boot check cannot be
written for it. That is a **narrowed**, not a closed, risk, and it must be written as such in the ADR
(Task 7). A `litellm` capacity guard needs a model-registry lookup, which is its own change.

- [ ] **Step 6: Document the minimum window**

Add to `CONTEXT.md`, under the ingest section:

```markdown
### Provider requirement for ingest

A Batch is sized to ~15K tokens of conversation (ADR-0001) — a **quality** bound from context rot on
multi-item extraction, not a capacity bound.

The window a provider must have is **not** the batch size: the model also reads the extraction
template and the response schema. Compute the requirement from the **rendered** prompt:

```
required_tokens ≈ (session_watcher_flush_chars + len(_INGEST_LLM_PROMPT) + len(schema)) / 4
```

with the ~4 chars/token ratio labelled for what it is — an **estimate**. Token density varies by
language (this project's conversations are heavily PT-BR, which tokenizes less efficiently than
English), so treat the figure as needing headroom, not as a bound. At the current 60000-char batch
this lands near **16–18K tokens** at the ~4 chars/token average. The runtime guard does NOT use that
average — it estimates at 2.0 chars/token (see Step 5b), and the `ollama` default of 65536 is sized so
a full batch fits even at that dense bound. Keep the two numbers distinct: ~4 is documentation of
typical headroom, 2.0 is the enforced safety bound.

Enforcement is not uniform, because the window is not uniformly introspectable:

- `ollama` — the window is pinned by `ORMAH_OLLAMA_NUM_CTX` (default 65536) rather than inherited from
  the server default. Raising `ORMAH_SESSION_WATCHER_FLUSH_CHARS` without raising this truncates the
  prompt silently. Note that `num_ctx` covers input **and** output: with `num_predict = 4096` the real
  input headroom is ~61K tokens, not 65K. A boot validator refuses to start when a full batch cannot
  fit, so lowering this is a loud failure rather than silent truncation.
- `claude_cli`, `litellm` — the window is not introspectable from here; the requirement is
  documentation. Every current Claude tier satisfies it by a wide margin.

Do **not** size the batch from the model's advertised window (ADR-0001 Amendment 1): a bigger window
does not buy cleaner multi-item extraction.
```

- [ ] **Step 6b: Fix the EXISTING adapter tests that adding `num_ctx` breaks**

Verified in the repo (council, Cursor): `tests/test_background/test_llm_adapters.py:34` and `:53` assert
**exact equality** on the options dict — `assert ... ["options"] == {"num_predict": 4096}` — so adding
`num_ctx` fails them. Update both to include the new key:

```python
    assert call_kwargs[1]["json"]["options"] == {"num_predict": 4096, "num_ctx": 8192}
```

```python
    assert payload["options"] == {"num_predict": 1024, "num_ctx": 8192}
```

Also check `test_get_adapter_ollama` in the same file: it builds a `_FakeSettings` stub that has no
`ollama_num_ctx`, so a factory reading `settings.ollama_num_ctx` directly raises `AttributeError`. Use
the defensive read the factory already uses for `llm_num_predict`:

```python
            num_ctx=num_ctx,   # threaded param, not read off settings here
```

- [ ] **Step 7: Run the tests**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: PASS — the **whole** suite, not just two directories. This task touches the LLM factory,
which reaches far beyond `test_engine`/`test_background`.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src/ tests/
git add src/ormah/config.py src/ormah/engine/memory_engine.py \
        src/ormah/ingest_capacity.py \
        src/ormah/background/llm/ollama_adapter.py \
        src/ormah/background/llm/__init__.py \
        CONTEXT.md tests/
git commit -m "fix(ingest): derive the provider timeout from the payload; pin the Ollama input window

The ingest path sent a variable payload against a fixed timeout and never used the
timeout_hint_seconds seam, though the seam is in the base protocol and honoured by all three
adapters. Harmless while payloads were ~3.4K chars; after ADR-0001 Amendment 3 they are ~60K.
Uses the same base+rate idiom as pair_batch.py, bounded so a hung provider is not waited on
forever.

OllamaAdapter set num_predict (output) but never num_ctx (input), so the effective input window
was the server's default -- a default below the payload truncates the prompt silently. Pin it."
```

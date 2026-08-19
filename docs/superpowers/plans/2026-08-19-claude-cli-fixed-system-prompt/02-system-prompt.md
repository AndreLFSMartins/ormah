# Task 2: Fixed `_SYSTEM_PROMPT` constant in argv (TDD)

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (constant near `_HARDENED_SETTINGS` ~L50; argv block L207–215)
- Test: `tests/test_background/test_claude_cli_adapter.py`

**Interfaces:**
- Produces: module constant `_SYSTEM_PROMPT: str` in `ormah.background.llm.claude_cli_adapter`; argv gains the adjacent pair `"--system-prompt", _SYSTEM_PROMPT`. Task 5 greps daemon logs assuming this flag is live after restart.

- [ ] **Step 1: Write the failing test** — append to `tests/test_background/test_claude_cli_adapter.py`, next to `test_argv_pins_model_and_json_output`. Also extend the existing top-of-file import to `from ormah.background.llm.claude_cli_adapter import _CANCEL_POLL_INTERVAL, _SYSTEM_PROMPT, ClaudeCliAdapter`.

```python
def test_argv_pins_fixed_system_prompt(monkeypatch):
    # Stable cache prefix: the Claude Code default system prompt injects per-call dynamic
    # sections (cwd, git status, env) that cost ~7.7k cache_write tokens EVERY call.
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    ClaudeCliAdapter(model="haiku").generate("hi")
    i = popen.argv.index("--system-prompt")
    assert popen.argv[i + 1] == _SYSTEM_PROMPT
```

- [ ] **Step 2: Run it — must fail on the import**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -x -q`
Expected: `ImportError: cannot import name '_SYSTEM_PROMPT'`

- [ ] **Step 3: Implement** — in `src/ormah/background/llm/claude_cli_adapter.py`, add below the `_HARDENED_SETTINGS` block:

```python
# Fixed system prompt: the Claude Code default injects per-call dynamic sections (cwd, git
# status, env info) that invalidate the prompt-cache prefix — measured 2026-08-19 at ~7.7k
# cache_write tokens EVERY call vs 110 with a constant prompt (3.0x cheaper: $0.0182 ->
# $0.0061/call; cache_write bills 1.25x, cache_read 0.1x). Both callers (pair_batch, ingest
# extraction) carry all task context in the user prompt, so nothing depends on the replaced
# default. Keep this a MODULE CONSTANT — any mutable source (env, constructor) reintroduces
# prefix variability, and every distinct value pays the full cache_write again.
_SYSTEM_PROMPT = (
    "You are a text-analysis engine used by Ormah's background memory jobs. "
    "Follow the instructions in the user message exactly. Output only the "
    "requested result — when a JSON schema is provided, reply with JSON that "
    "conforms to it and nothing else."
)
```

and extend the argv list (L207–215) with one line after `"--settings", _HARDENED_SETTINGS,`:

```python
            "--system-prompt", _SYSTEM_PROMPT,
```

- [ ] **Step 4: Run the adapter test file — all green**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q`
Expected: all pass, 0 failures.

- [ ] **Step 5: Commit (exact paths)**

```bash
git add src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): pin a fixed --system-prompt in ClaudeCliAdapter for a stable cache prefix" \
  -- src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
```

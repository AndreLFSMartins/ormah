# Task 3: Per-call usage/cost log line (TDD)

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (envelope parse, after the `isinstance(envelope, dict)` guard)
- Test: `tests/test_background/test_claude_cli_adapter.py`

**Interfaces:**
- Consumes: nothing from Task 2 beyond a green test file.
- Produces: one `logger.info` per call, message prefix `claude -p usage:` with fields `in= out= cache_read= cache_write= cost_usd=`. Task 5 greps exactly `"claude -p usage"` in `/tmp/ormah-dev.err`.

**Placement matters.** The log line goes *before* the `is_error` branch, because an `is_error` envelope is still a billed call — dropping it would understate the measured cost exactly when something is going wrong.

- [ ] **Step 1: Write the three failing tests** — append to the test file (`import logging` already exists at its top):

```python
def test_usage_logged_from_envelope(monkeypatch, caplog):
    envelope = json.dumps({
        "result": "ok", "is_error": False, "total_cost_usd": 0.0061,
        "usage": {"input_tokens": 3, "output_tokens": 9,
                  "cache_read_input_tokens": 25000, "cache_creation_input_tokens": 110},
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    with caplog.at_level(logging.INFO, logger="ormah.background.llm.claude_cli_adapter"):
        assert ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi") == "ok"
    lines = [r.message for r in caplog.records if "claude -p usage" in r.message]
    assert len(lines) == 1
    assert "cache_write=110" in lines[0] and "cost_usd=0.0061" in lines[0]


def test_usage_logged_even_for_is_error_envelope(monkeypatch, caplog):
    # An is_error envelope is still a BILLED call. Logging after the is_error return would
    # silently understate cost precisely when the provider is misbehaving.
    envelope = json.dumps({
        "result": "", "is_error": True, "subtype": "error_during_execution",
        "total_cost_usd": 0.0042,
        "usage": {"input_tokens": 3, "output_tokens": 0,
                  "cache_read_input_tokens": 25000, "cache_creation_input_tokens": 110},
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    with caplog.at_level(logging.INFO, logger="ormah.background.llm.claude_cli_adapter"):
        assert ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi") is None
    lines = [r.message for r in caplog.records if "claude -p usage" in r.message]
    assert len(lines) == 1
    assert "cost_usd=0.0042" in lines[0]


def test_missing_usage_never_breaks_parse(monkeypatch, caplog):
    envelope = json.dumps({"result": "ok", "is_error": False})
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    with caplog.at_level(logging.INFO, logger="ormah.background.llm.claude_cli_adapter"):
        assert ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi") == "ok"
    assert not [r for r in caplog.records if "claude -p usage" in r.message]
```

- [ ] **Step 2: Run them — the first two must fail on the log assertion**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q -k "usage or is_error_envelope"`
Expected: `test_usage_logged_from_envelope` and `test_usage_logged_even_for_is_error_envelope` FAIL (`assert len(lines) == 1` → 0); `test_missing_usage_never_breaks_parse` may already pass — that is fine, it is the regression guard.

- [ ] **Step 3: Implement** — in `generate()`, immediately after `if not isinstance(envelope, dict): return None` and BEFORE `_cleanup_persisted_stub(...)`:

```python
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            # Best-effort observability: the envelope already carries billing truth; without
            # this line, measuring cost needs an external shim around the binary. Logged
            # before the is_error branch below — a failed call still bills.
            logger.info(
                "claude -p usage: in=%s out=%s cache_read=%s cache_write=%s cost_usd=%s",
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens"),
                envelope.get("total_cost_usd"),
            )
```

- [ ] **Step 4: Run the whole adapter test file — all green**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q`
Expected: all pass, 0 failures.

- [ ] **Step 5: Commit (exact file paths, never a directory pathspec)**

```bash
git add src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): log per-call usage and cost from the claude -p envelope" \
  -- src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git show --stat HEAD
```
Expected from `git show --stat`: exactly 2 files. More than 2 → `git reset --soft HEAD~1` and recommit with the exact paths.

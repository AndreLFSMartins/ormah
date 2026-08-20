# Task 4: Per-call usage/cost log line (TDD)

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (envelope parse, right after the `isinstance(envelope, dict)` guard)
- Test: `tests/test_background/test_claude_cli_adapter.py`

**Interfaces:**
- Consumes: Task 3's green test file. Nothing else.
- Produces: one `logger.info` per call, message prefix `claude -p usage:`, fields `session= in= out= cache_read= cache_write= cost_usd=`. Task 6 greps exactly `claude -p usage` in `~/.local/share/ormah/logs/ormah.log`.

**Why `session=` is in the line.** Task 6 Step 7 has to tell a daemon `claude -p` transcript
on disk from the operator's own interactive Claude Code sessions, and a timestamp cannot:
whoever runs that task is inside such a session, so an unattributed `find` always returns
files and decides nothing. The envelope already carries `session_id`
(`tests/fixtures/claude_cli_envelope.json`), and the adapter already uses it for
`_cleanup_persisted_stub` (`claude_cli_adapter.py:344`) — logging it costs one format field
and turns that check from decorative into decisive. It is an id, not content.

**Why this is load-bearing and not nice-to-have.** It is what makes the cost claim re-verifiable in production. Without it, measuring cost needs an external shim wrapped around the binary — which is exactly how the withdrawn 3.0× number got recorded and never re-checked.

**Placement matters.** The log line goes *before* the `is_error` branch: an `is_error` envelope is still a billed call, and logging after that early return would understate measured cost precisely when something is going wrong.

**Field names come from the real envelope** (`tests/fixtures/claude_cli_envelope.json`): `usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`, and `total_cost_usd` at the envelope **root**, not inside `usage`.

- [ ] **Step 1: Write the three failing tests**

Append to `tests/test_background/test_claude_cli_adapter.py` (`import logging` already exists at its top):

```python
def test_usage_logged_from_envelope(monkeypatch, caplog):
    envelope = json.dumps({
        "result": "ok", "is_error": False, "total_cost_usd": 0.0061,
        "session_id": "4b8c1d2e-0000-4000-8000-abcdefabcdef",
        "usage": {"input_tokens": 3, "output_tokens": 9,
                  "cache_read_input_tokens": 25000, "cache_creation_input_tokens": 110},
    })
    monkeypatch.setattr(subprocess, "Popen", _fake_popen(stdout=envelope))
    with caplog.at_level(logging.INFO, logger="ormah.background.llm.claude_cli_adapter"):
        assert ClaudeCliAdapter(model="haiku", bin_path="/bin/claude").generate("hi") == "ok"
    lines = [r.message for r in caplog.records if "claude -p usage" in r.message]
    assert len(lines) == 1
    assert "cache_write=110" in lines[0] and "cost_usd=0.0061" in lines[0]
    # Task 6 Step 7 matches daemon transcripts on this id; without it that check cannot decide.
    assert "session=4b8c1d2e-0000-4000-8000-abcdefabcdef" in lines[0]


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

**This filter collects FOUR tests, not three** (council round 5, measured: `-k "usage or
is_error_envelope"` already collects `1/36` today). The pre-existing
`test_returns_none_on_is_error_envelope` matches `is_error_envelope` and is swept in. It is
unrelated to this task and must stay green throughout — do not "fix" it, and do not read its
presence as something having gone wrong.

Expected: `test_usage_logged_from_envelope` and `test_usage_logged_even_for_is_error_envelope` FAIL (`assert len(lines) == 1` → 0). `test_missing_usage_never_breaks_parse` may already pass — that is fine, it is the regression guard for the third case. `test_returns_none_on_is_error_envelope` passes, as it does today.

- [ ] **Step 3: Implement**

In `generate()`, immediately after `if not isinstance(envelope, dict): return None` and BEFORE `_cleanup_persisted_stub(...)`:

```python
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            # Best-effort observability: the envelope already carries billing truth. Logged
            # BEFORE the is_error branch below — a failed call still bills, and dropping it
            # would understate cost exactly when the provider is misbehaving. Log only, never
            # persisted; a missing `usage` key emits nothing and raises nothing.
            logger.info(
                "claude -p usage: session=%s in=%s out=%s cache_read=%s cache_write=%s "
                "cost_usd=%s",
                envelope.get("session_id"),
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens"),
                envelope.get("total_cost_usd"),
            )
```

- [ ] **Step 4: Run the three tests — all green**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q -k "usage or is_error_envelope"`
Expected: **4 passed** — this task's three, plus the pre-existing
`test_returns_none_on_is_error_envelope` the filter also matches (see Step 2). `3 passed`
here means one of the three new tests did not get collected.

- [ ] **Step 5: Run the whole adapter file — no regressions**

Run: `.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q`
Expected: all pass, 0 failures. Every existing failure path of `generate()` must be byte-for-byte unchanged — a failure in a cancel/timeout test means the insert landed in the wrong place.

- [ ] **Step 6: Lint**

Run: `.venv/bin/python -m ruff check src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit (exact file paths, never a directory pathspec)**

```bash
git add src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): log per-call usage and cost from the claude -p envelope" \
  -- src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git show --stat HEAD
```
Expected from `git show --stat`: exactly 2 files. More than 2 → `git reset --soft HEAD~1` and recommit with the exact paths.

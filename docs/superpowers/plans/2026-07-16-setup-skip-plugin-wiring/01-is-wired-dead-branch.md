# Task 1: Fix the dead matcher branch in `_claude_code_is_wired`

**Files:**
- Modify: `src/ormah/setup.py:2297-2315` (`_claude_code_is_wired`)
- Test: `tests/test_setup.py` (new class `TestClaudeCodeIsWired`)

**Interfaces:**
- Consumes: `_is_ormah_hook(entry: dict) -> bool` (`src/ormah/setup.py:161`) — already recognizes both the CLI form (`<...>/ormah whisper inject|store`) and the plugin wrapper form (`<...>/ormah-whisper-inject|store`).
- Produces: nothing new. `_claude_code_is_wired() -> bool` keeps its signature.

**Why this bug exists:** the function iterates `hooks.values()` and reads `entry.get("command")`, but in Claude Code's schema each event maps to a list of **matcher** dicts (`{"hooks": [...]}`), and the command lives one level deeper. So `entry.get("command")` is always `""` and the branch never matches — verified by executing it against the live config. Today the function only ever returns `True` via the `.claude.json` MCP fallback.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_setup.py`. Add `_claude_code_is_wired` to the existing `from ormah.setup import (...)` block first.

```python
class TestClaudeCodeIsWired:
    def _write_settings(self, tmp_path: Path, data: dict) -> Path:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
        return settings_path

    def test_detects_cli_hooks_when_no_mcp_entry_exists(self, tmp_path):
        """Regression: the hooks branch read entry.get("command") off the matcher
        dict, so it never matched; only the .claude.json MCP fallback could
        return True. No ~/.claude.json here, so the fallback cannot rescue it."""
        self._write_settings(tmp_path, {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/ormah whisper inject", "timeout": 10}]}
                ]
            }
        })

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is True

    def test_third_party_hook_is_not_mistaken_for_ormah(self, tmp_path):
        self._write_settings(tmp_path, {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/other-tool whisper inject"}]}
                ]
            }
        })

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is False

    def test_falls_back_to_mcp_entry_when_no_hooks(self, tmp_path):
        self._write_settings(tmp_path, {"hooks": {}})
        (tmp_path / ".claude.json").write_text(
            json.dumps({"mcpServers": {"ormah": {"command": "/usr/bin/ormah", "args": ["mcp"]}}}) + "\n"
        )

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is True

    def test_malformed_matcher_does_not_raise(self, tmp_path):
        self._write_settings(tmp_path, {
            "hooks": {"UserPromptSubmit": ["not-a-dict", {"no_hooks_key": True}, {"hooks": "not-a-list"}]}
        })

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is False
```

- [ ] **Step 2: Run the tests to verify the regression test fails**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeIsWired -v`

Expected: `test_detects_cli_hooks_when_no_mcp_entry_exists` **FAILS** with `assert False is True` — this is the dead branch, proven. The other three should already pass.

If that test *passes* before the fix, stop: the premise is wrong and the task needs re-examination.

- [ ] **Step 3: Fix the branch**

In `src/ormah/setup.py`, replace the hooks loop inside `_claude_code_is_wired`:

```python
def _claude_code_is_wired() -> bool:
    # Check for ormah whisper hooks in settings.json and ormah MCP in .claude.json
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(settings_path.read_text())
        hooks = data.get("hooks") or {}
        for matchers in hooks.values():
            if not isinstance(matchers, list):
                continue
            for matcher in matchers:
                if not isinstance(matcher, dict):
                    continue
                inner = matcher.get("hooks")
                if not isinstance(inner, list):
                    continue
                if any(_is_ormah_hook(entry) for entry in inner):
                    return True
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    claude_json = Path.home() / ".claude.json"
    try:
        data = json.loads(claude_json.read_text())
        return "ormah" in (data.get("mcpServers") or {})
    except (OSError, json.JSONDecodeError):
        return False
```

The command now comes from `matcher["hooks"][*]["command"]`, and `_is_ormah_hook` replaces the old `"ormah whisper" in cmd` substring test — which would have matched a third-party command containing that string.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeIsWired -v`
Expected: 4 passed.

Then confirm nothing else regressed:

Run: `python -m pytest tests/test_setup.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): _claude_code_is_wired never detected hooks — it read command off the matcher

The hooks branch iterated matcher dicts and read entry.get(\"command\"), but the
command lives at matcher[\"hooks\"][*][\"command\"]. The branch was dead: it always
saw \"\", so the function only returned True via the .claude.json MCP fallback.

Inspect the inner hooks list and reuse _is_ormah_hook, which is argv-aware and
already knows both the CLI and plugin-wrapper forms.

Refs #145"
```

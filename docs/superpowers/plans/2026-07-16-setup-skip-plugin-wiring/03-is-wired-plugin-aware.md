# Task 3: Make `_claude_code_is_wired` plugin-aware

**Files:**
- Modify: `src/ormah/setup.py:2297` (`_claude_code_is_wired`, as rewritten by Task 1)
- Test: `tests/test_setup.py` (extend `TestClaudeCodeIsWired` from Task 1)

**Interfaces:**
- Consumes: `_claude_code_plugin_provides_hooks() -> bool` (Task 2).
- Produces: nothing new.

**Why this task exists, and why it must land before Task 4:** Task 4 strips the ormah entry from `~/.claude.json`. `_claude_code_is_wired` is read by `list_agents()` (`src/ormah/setup.py:2542`) to render the desktop UI's agent panel. Without this task, the commit sequence would contain a state where the CLI wiring is stripped, no MCP entry remains, and the UI reports "Claude Code: not wired" on an install where the plugin provides everything and the whisper works. That is a regression **this change would introduce** — hence in scope, rather than adjacent cleanup.

- [ ] **Step 1: Write the failing test**

Append to the `TestClaudeCodeIsWired` class created in Task 1. It reuses the `_enable`/`_install` fixture shape from `TestClaudeCodePluginProvidesHooks` (Task 2) — a plugin only counts when it is enabled **and** installed.

```python
    def test_plugin_providing_hooks_counts_as_wired(self, tmp_path):
        """The plugin provides the hooks and MCP server; without this the UI
        would report a working install as not wired once Task 4 strips the CLI
        wiring."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"ormah@ormah": True}}, indent=2) + "\n"
        )
        install_path = claude_dir / "plugins" / "cache" / "ormah" / "ormah" / "0.13.3"
        (install_path / "hooks").mkdir(parents=True)
        (install_path / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {}}) + "\n")
        (claude_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {"ormah@ormah": [
                {"scope": "user", "installPath": str(install_path), "version": "0.13.3"}
            ]},
        }, indent=2) + "\n")
        # no ormah hooks in settings.json, no ~/.claude.json — the plugin is the only wiring

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is True

    def test_enabled_but_uninstalled_plugin_alone_is_not_wired(self, tmp_path):
        """Nothing would actually fire — reporting 'wired' would be a lie."""
        self._write_settings(tmp_path, {"enabledPlugins": {"ormah@ormah": True}})

        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_is_wired() is False
```

- [ ] **Step 2: Run the tests to verify the new one fails**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeIsWired -v`

Expected: `test_plugin_providing_hooks_counts_as_wired` **FAILS** with `assert False is True`. `test_enabled_but_uninstalled_plugin_alone_is_not_wired` already passes (nothing is wired, so `False` is correct for the wrong reason today — it stays green as a guard against the skip becoming eager).

- [ ] **Step 3: Write the implementation**

Add the plugin check as the first statement of `_claude_code_is_wired` in `src/ormah/setup.py`:

```python
def _claude_code_is_wired() -> bool:
    # The plugin ships the hooks and the MCP server — an install with a working
    # plugin is wired even when settings.json holds nothing of ours.
    if _claude_code_plugin_provides_hooks():
        return True
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeIsWired -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): a working ormah plugin counts as wired

list_agents() renders the desktop agent panel from _claude_code_is_wired. The
plugin ships the hooks and the MCP server, so an install carrying only the
plugin is wired — without this it would report 'not wired' once the redundant
CLI wiring is stripped.

Refs #145"
```

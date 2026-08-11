# Task 4: The `_claude_code_wire` guard — skip and strip

**Files:**
- Modify: `src/ormah/setup.py:2388-2395` (`_claude_code_wire`)
- Test: `tests/test_setup.py` (new class `TestClaudeCodeWirePluginGuard`)

**Interfaces:**
- Consumes: `_claude_code_plugin_provides_hooks() -> bool` (Task 2); the existing helpers `_remove_claude_hooks() -> None` (`setup.py:1585`), `_remove_mcp_from_json(config_path: Path) -> None` (`setup.py:1661`, made atomic by Task 0), `get_ormah_bin_path() -> str`, `configure_claude_hooks(ormah_bin: str) -> None` (`setup.py:337`), `configure_claude_code_mcp(ormah_bin: str) -> None` (`setup.py:381`), `install_claude_md(scope: str = "user", cwd: Path | None = None) -> None` (`setup.py:772`), `install_claude_agents() -> None`, `install_claude_commands() -> None`.
- Produces: nothing new. `_claude_code_wire() -> None` keeps its signature.

**This is the fix.** All three offending entry points route through this function: `install.sh:196` (plain `ormah setup`), `install.sh:191` (`ormah setup --update`), and `desktop/ui/src/InstallPanel.tsx:38` → `run_setup_json` (`setup.py:2585`). One guard, three paths.

## Strip only what duplicates runtime execution — **[council]**

An earlier revision of this plan stripped agents and slash commands too. That was wrong, and the council caught it:

| Surface | CLI installs | Plugin provides | Same registration? | Action |
| --- | --- | --- | --- | --- |
| hooks | `ormah whisper inject\|store` in `~/.claude/settings.json` | `hooks/hooks.json` | **yes** — both fire every turn | **strip** |
| MCP | `ormah` in `~/.claude.json` | `.mcp.json` | **yes** — two servers | **strip** |
| agent | `ormah-maintenance` | `ormah:ormah-maintenance` | no — different name | keep installing |
| slash command | `/ormah-maintenance` | `/ormah:maintenance` | no — different name | keep installing |
| CLAUDE.md | guidance block | *(nothing — plugins cannot write CLAUDE.md)* | no | keep installing |

Agents and commands do not execute on their own, so they contribute nothing to the duplicate-whisper defect. Removing `~/.claude/commands/ormah-maintenance.md` would delete a public invocation the plugin does **not** provide under that name — scope creep that breaks a user-facing surface.

**The strip is safe by construction:** the plugin's hooks live in `<installPath>/hooks/hooks.json`, a file `_remove_claude_hooks` never opens — it physically cannot delete them. Third-party hooks under the same events survive via the existing `_strip_ormah_hooks` matcher rules.

**Behaviour of the helpers this task relies on** (read from the source — assert against it):
- `_remove_claude_hooks` pops the `"hooks"` key entirely when nothing survives the strip, and preserves every other top-level key (including `enabledPlugins`).
- `_remove_mcp_from_json` deletes the whole `"mcpServers"` key when `ormah` was its only entry.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_setup.py`. Add `_claude_code_wire` to the `from ormah.setup import (...)` block.

```python
class TestClaudeCodeWirePluginGuard:
    def _seed_working_plugin(self, tmp_path: Path, *, enabled: bool = True, scope: str = "user") -> Path:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        install_path = claude_dir / "plugins" / "cache" / "ormah" / "ormah" / "0.13.3"
        (install_path / "hooks").mkdir(parents=True)
        (install_path / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {}}) + "\n")
        (claude_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {"ormah@ormah": [
                {"scope": scope, "installPath": str(install_path), "version": "0.13.3"}
            ]},
        }, indent=2) + "\n")
        (claude_dir / "settings.json").write_text(json.dumps({
            "enabledPlugins": {"ormah@ormah": enabled},
            "theme": "dark",
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/ormah whisper inject", "timeout": 10}]}
                ],
                "SessionEnd": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/ormah whisper store", "timeout": 300}]}
                ],
            },
        }, indent=2) + "\n")
        (tmp_path / ".claude.json").write_text(json.dumps({
            "mcpServers": {"ormah": {"type": "stdio", "command": "/usr/bin/ormah", "args": ["mcp"]}}
        }, indent=2) + "\n")
        return claude_dir

    def test_working_plugin_strips_hooks_and_mcp_and_writes_no_wiring(self, tmp_path):
        claude_dir = self._seed_working_plugin(tmp_path)

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.configure_claude_code_mcp") as configure_mcp,
            patch("ormah.setup.install_claude_agents") as install_agents,
            patch("ormah.setup.install_claude_commands") as install_commands,
            patch("ormah.setup.install_claude_md") as install_md,
        ):
            _claude_code_wire()

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert "hooks" not in settings                              # both ormah hooks stripped
        assert settings["enabledPlugins"] == {"ormah@ormah": True}  # untouched
        assert settings["theme"] == "dark"                          # co-tenant keys survive
        assert "mcpServers" not in json.loads((tmp_path / ".claude.json").read_text())

        configure_hooks.assert_not_called()
        configure_mcp.assert_not_called()
        # not duplicate registrations — the plugin namespaces these
        install_md.assert_called_once()
        install_agents.assert_called_once()
        install_commands.assert_called_once()

    def test_strip_preserves_third_party_hooks(self, tmp_path):
        claude_dir = self._seed_working_plugin(tmp_path)
        settings = json.loads((claude_dir / "settings.json").read_text())
        settings["hooks"]["UserPromptSubmit"][0]["hooks"].append(
            {"type": "command", "command": "/usr/bin/other-tool run"}
        )
        (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.install_claude_md"),
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
        ):
            _claude_code_wire()

        hooks = json.loads((claude_dir / "settings.json").read_text())["hooks"]
        surviving = hooks["UserPromptSubmit"][0]["hooks"]
        assert len(surviving) == 1
        assert surviving[0]["command"] == "/usr/bin/other-tool run"

    def test_enabled_but_uninstalled_plugin_wires_normally(self, tmp_path):
        """A stale enabled flag must not cost the user the whisper."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"ormah@ormah": True}}, indent=2) + "\n"
        )  # no installed_plugins.json

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.get_ormah_bin_path", return_value="/usr/bin/ormah"),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.configure_claude_code_mcp") as configure_mcp,
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
            patch("ormah.setup.install_claude_md"),
        ):
            _claude_code_wire()

        configure_hooks.assert_called_once_with("/usr/bin/ormah")
        configure_mcp.assert_called_once_with("/usr/bin/ormah")

    def test_project_scoped_plugin_wires_normally(self, tmp_path):
        """Deliberate: the CLI hooks are global and serve every other project."""
        self._seed_working_plugin(tmp_path, scope="project")

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.get_ormah_bin_path", return_value="/usr/bin/ormah"),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.configure_claude_code_mcp"),
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
            patch("ormah.setup.install_claude_md"),
        ):
            _claude_code_wire()

        configure_hooks.assert_called_once_with("/usr/bin/ormah")

    def test_plugin_disabled_wires_normally(self, tmp_path):
        self._seed_working_plugin(tmp_path, enabled=False)

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.get_ormah_bin_path", return_value="/usr/bin/ormah"),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.configure_claude_code_mcp"),
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
            patch("ormah.setup.install_claude_md"),
        ):
            _claude_code_wire()

        configure_hooks.assert_called_once_with("/usr/bin/ormah")

    def test_unreadable_settings_wires_normally(self, tmp_path):
        """Fail-open: an unparseable config must not silently disable the whisper."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{not json")

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.get_ormah_bin_path", return_value="/usr/bin/ormah"),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.configure_claude_code_mcp"),
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
            patch("ormah.setup.install_claude_md"),
        ):
            _claude_code_wire()

        configure_hooks.assert_called_once_with("/usr/bin/ormah")

    def test_fresh_plugin_install_removes_nothing(self, tmp_path):
        """Working plugin, no CLI wiring ever done — the guard is idempotent."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        install_path = claude_dir / "plugins" / "cache" / "ormah" / "ormah" / "0.13.3"
        (install_path / "hooks").mkdir(parents=True)
        (install_path / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {}}) + "\n")
        (claude_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {"ormah@ormah": [
                {"scope": "user", "installPath": str(install_path), "version": "0.13.3"}
            ]},
        }, indent=2) + "\n")
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"ormah@ormah": True}}, indent=2) + "\n"
        )

        with (
            patch("ormah.setup.Path.home", return_value=tmp_path),
            patch("ormah.setup.configure_claude_hooks") as configure_hooks,
            patch("ormah.setup.install_claude_md") as install_md,
            patch("ormah.setup.install_claude_agents"),
            patch("ormah.setup.install_claude_commands"),
        ):
            _claude_code_wire()

        assert json.loads((claude_dir / "settings.json").read_text()) == {
            "enabledPlugins": {"ormah@ormah": True}
        }
        configure_hooks.assert_not_called()
        install_md.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeWirePluginGuard -v`

Expected: `test_working_plugin_strips_hooks_and_mcp_and_writes_no_wiring`, `test_strip_preserves_third_party_hooks` and `test_fresh_plugin_install_removes_nothing` **FAIL** — today `_claude_code_wire` calls `configure_claude_hooks` unconditionally, so `configure_hooks.assert_not_called()` raises `AssertionError: Expected 'configure_claude_hooks' to not have been called`. The four "wires normally" tests already pass (that is current behaviour, and they exist to prove it stays).

- [ ] **Step 3: Write the implementation**

Replace `_claude_code_wire` in `src/ormah/setup.py`:

```python
def _claude_code_wire() -> None:
    # The plugin registers the same UserPromptSubmit/PreCompact/SessionEnd hooks
    # and the same MCP server. Wiring them again in ~/.claude/settings.json runs
    # both copies: the whisper fires twice per human turn, and no merge can dedupe
    # across the two files. The agent and slash command are namespaced by the
    # plugin (ormah:maintenance vs ormah-maintenance), so they are not duplicate
    # registrations — they stay installed, as does CLAUDE.md, which no plugin can
    # write.
    if _claude_code_plugin_provides_hooks():
        _remove_claude_hooks()
        _remove_mcp_from_json(Path.home() / ".claude.json")
        info(
            "Claude Code plugin already provides the hooks and MCP server "
            "— removed redundant CLI wiring"
        )
    else:
        ormah_bin = get_ormah_bin_path()
        configure_claude_hooks(ormah_bin)
        configure_claude_code_mcp(ormah_bin)

    install_claude_md()
    install_claude_agents()
    install_claude_commands()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodeWirePluginGuard -v`
Expected: 7 passed.

Then the whole file plus the JSON setup path, to confirm no existing wiring test regressed:

Run: `python -m pytest tests/test_setup.py tests/test_setup_json.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): skip the Claude Code hooks and MCP the ormah plugin already provides

With the plugin installed, ormah setup wired the same three hooks a second time
into ~/.claude/settings.json. Both fired, so every human turn ran the whisper
twice — two encodes, two hybrid searches, two cross-encoder reranks, and two
retrieval_events rows biasing every per-event metric. The MCP server was
registered twice for the same reason.

_install_hooks merges within settings.json, but the plugin's hooks live in a
different file, so no merge can dedupe across the two. --skip-client-setup
existed but was opt-in, and install.sh, the --update path and the desktop
button never passed it.

Skip the redundant work when a user-scoped plugin is enabled AND installed,
stripping any CLI wiring a previous setup left behind so existing installs
self-heal. The agent and slash command are namespaced by the plugin, so they
are not duplicates and are still installed, as is CLAUDE.md. When no working
user-scoped plugin is present, behaviour is unchanged.

Closes #145"
```

# Task 2: Add `_claude_code_plugin_provides_hooks()`

**Files:**
- Modify: `src/ormah/setup.py` — insert immediately **above** `_claude_code_detected()` (`src/ormah/setup.py:2293`), so the Claude Code predicates sit together.
- Test: `tests/test_setup.py` (new class `TestClaudeCodePluginProvidesHooks`)

**Interfaces:**
- Consumes: `_plugin_enabled_in_settings(settings_path: Path, plugin_name: str) -> bool` (`src/ormah/setup.py:687`) — existing helper; matches `key == plugin_name or key.startswith(f"{plugin_name}@")` with `enabled is True`, and returns False on a missing or unparseable file.
- Produces: `_claude_code_plugin_provides_hooks() -> bool` — used by Task 3 (`_claude_code_is_wired`) and Task 4 (`_claude_code_wire`).

**Note:** an earlier revision of this plan called this `_claude_code_plugin_active()` and read only `enabledPlugins`. The council rejected that. The name changed with the contract: the predicate licenses *deleting the user's working wiring*, so it must mean "the plugin's hooks will actually fire", not "a flag says enabled".

## The two states this predicate must AND together — **[council]**

Claude Code keeps *enabled* and *installed* in **two different files**. An enabled flag is not proof that a working plugin exists:

| State | File | Shape (read from the live install) |
| --- | --- | --- |
| enabled | `~/.claude/settings.json` | `{"enabledPlugins": {"ormah@ormah": true}}` |
| installed | `~/.claude/plugins/installed_plugins.json` | `{"plugins": {"ormah@ormah": [{"scope": "user", "installPath": "/Users/…/plugins/cache/ormah/ormah/0.13.3", "version": "0.13.3"}]}}` |

A stale flag, a missing cache dir, an interrupted update or an incomplete package would otherwise make setup delete the only working integration and leave the user with **no whisper at all** — silently. So: enabled **and** a user-scoped registry entry **and** `installPath/hooks/hooks.json` on disk.

## Why user scope only — **[council]**

`configure_claude_hooks` writes to the **global** `~/.claude/settings.json`, which serves every project. A **project**- or **local**-scoped plugin covers one project, so deleting the global wiring for its sake would break the whisper in every *other* project. Global-active ↔ global-wired is the only safe symmetry. The project-scoped case therefore keeps its duplication and gets a follow-up issue; the test below pins that as deliberate.

**Fail-open:** any unreadable or unparseable config returns `False`, so setup wires exactly as it does today.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_setup.py`. Add `_claude_code_plugin_provides_hooks` to the `from ormah.setup import (...)` block.

```python
class TestClaudeCodePluginProvidesHooks:
    def _enable(self, tmp_path: Path, value=True, key: str = "ormah@ormah") -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {key: value}}, indent=2) + "\n"
        )

    def _install(self, tmp_path: Path, *, scope: str = "user", with_hooks: bool = True,
                 key: str = "ormah@ormah", install_path: Path | None = None) -> Path:
        plugins_dir = tmp_path / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        target = install_path if install_path is not None else plugins_dir / "cache" / "ormah" / "ormah" / "0.13.3"
        if with_hooks:
            (target / "hooks").mkdir(parents=True, exist_ok=True)
            (target / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {}}) + "\n")
        (plugins_dir / "installed_plugins.json").write_text(json.dumps({
            "version": 2,
            "plugins": {key: [{"scope": scope, "installPath": str(target), "version": "0.13.3"}]},
        }, indent=2) + "\n")
        return target

    def test_true_when_enabled_and_installed_with_hooks(self, tmp_path):
        self._enable(tmp_path)
        self._install(tmp_path)
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is True

    def test_true_for_any_marketplace_name(self, tmp_path):
        self._enable(tmp_path, key="ormah@some-other-market")
        self._install(tmp_path, key="ormah@some-other-market")
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is True

    def test_false_when_enabled_but_not_installed(self, tmp_path):
        """A stale enabled flag must never license deleting the working wiring."""
        self._enable(tmp_path)
        # no installed_plugins.json at all
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_false_when_registry_lists_plugin_but_install_path_is_gone(self, tmp_path):
        self._enable(tmp_path)
        self._install(tmp_path, install_path=tmp_path / "vanished", with_hooks=False)
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_false_when_install_exists_but_hooks_json_is_missing(self, tmp_path):
        """An interrupted update can leave the dir without its hooks manifest."""
        self._enable(tmp_path)
        target = self._install(tmp_path, with_hooks=False)
        target.mkdir(parents=True, exist_ok=True)
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_false_when_installed_but_disabled(self, tmp_path):
        self._enable(tmp_path, value=False)
        self._install(tmp_path)
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_false_when_plugin_is_project_scoped(self, tmp_path):
        """Deliberate: the CLI hooks are global and serve every other project.
        Stripping them for a one-project plugin would break the whisper there."""
        self._enable(tmp_path)
        self._install(tmp_path, scope="project")
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_false_for_another_plugin(self, tmp_path):
        self._enable(tmp_path, key="superpowers@claude-plugins-official")
        self._install(tmp_path, key="superpowers@claude-plugins-official")
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_fails_open_on_corrupt_registry(self, tmp_path):
        self._enable(tmp_path)
        plugins_dir = tmp_path / ".claude" / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "installed_plugins.json").write_text("{not json")
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False

    def test_fails_open_on_missing_settings(self, tmp_path):
        self._install(tmp_path)
        with patch("ormah.setup.Path.home", return_value=tmp_path):
            assert _claude_code_plugin_provides_hooks() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodePluginProvidesHooks -v`
Expected: collection error — `ImportError: cannot import name '_claude_code_plugin_provides_hooks' from 'ormah.setup'`.

- [ ] **Step 3: Write the implementation**

Insert in `src/ormah/setup.py` directly above `def _claude_code_detected()`:

```python
def _claude_code_plugin_provides_hooks() -> bool:
    """True when a user-scoped ormah plugin is enabled AND actually installed.

    Claude Code keeps the two states in two different files, and an enabled flag
    is not proof that a working plugin exists:
      - enabled:   ``enabledPlugins`` in ~/.claude/settings.json
      - installed: ``plugins[]`` in ~/.claude/plugins/installed_plugins.json,
                   carrying the scope and the resolved installPath.

    This predicate licenses deleting the user's own wiring, so it requires both,
    plus hooks/hooks.json under that installPath. A stale flag pointing at a
    missing cache dir or a half-finished update would otherwise leave the user
    with no whisper at all — silently.

    Only a user-scoped plugin counts: configure_claude_hooks writes to the global
    ~/.claude/settings.json, which serves every project, so those hooks are
    redundant only when the plugin is global too. A project-scoped plugin keeps
    its duplication rather than break the whisper everywhere else.

    Fails open: any unreadable or unparseable config returns False, so setup
    wires exactly as it does today.
    """
    if not _plugin_enabled_in_settings(Path.home() / ".claude" / "settings.json", "ormah"):
        return False

    registry_path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return False

    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return False

    for key, entries in plugins.items():
        if not isinstance(key, str) or key.split("@")[0] != "ormah":
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("scope") != "user":
                continue
            install_path = entry.get("installPath")
            if not isinstance(install_path, str) or not install_path:
                continue
            if (Path(install_path) / "hooks" / "hooks.json").is_file():
                return True
    return False
```

`_plugin_enabled_in_settings` is reused rather than re-implemented — it already handles the `ormah` / `ormah@<marketplace>` key shapes, the `enabled is True` strictness, and a missing or corrupt file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup.py::TestClaudeCodePluginProvidesHooks -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "feat(setup): detect a user-scoped ormah plugin that is enabled AND installed

Claude Code stores enabled (settings.json enabledPlugins) and installed
(plugins/installed_plugins.json, with scope and installPath) separately. The
predicate that licenses deleting the user's wiring requires both, plus
hooks/hooks.json under the resolved installPath — a stale flag over a missing
or half-updated install must not cost the user the whisper.

User scope only: the CLI hooks are global, so they are redundant only when the
plugin is global too. Reuses _plugin_enabled_in_settings.

No callers yet.

Refs #145"
```

# Task 0: Make `_remove_mcp_from_json` write atomically

**Files:**
- Modify: `src/ormah/setup.py:1661-1683` (`_remove_mcp_from_json`)
- Test: `tests/test_setup.py` (new class `TestRemoveMcpFromJson`)

**Interfaces:**
- Consumes: `_atomic_write(path: str, text: str, mode: int | None = None) -> None` (`src/ormah/setup.py:271`) — writes via a temp file in the same directory + `os.replace`, and resolves symlinks so the link itself survives.
- Produces: nothing new. `_remove_mcp_from_json(config_path: Path) -> None` keeps its signature.

**Why this is Task 0 (council finding, medium):** `_remove_claude_hooks` already writes through `_atomic_write` (`setup.py:1609`), but its sibling `_remove_mcp_from_json` ends in a bare `config_path.write_text(...)` (`setup.py:1681`). Today that path runs only on uninstall. Task 4 makes it run on **every** `ormah setup --update` for plugin users, against `~/.claude.json` — a file that holds the user's entire Claude Code config. A crash mid-write truncates it. Land the crash-safety fix before the change that makes the path hot.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_setup.py`. Add `_remove_mcp_from_json` to the existing `from ormah.setup import (...)` block if it is not already there.

```python
class TestRemoveMcpFromJson:
    def _write_config(self, tmp_path: Path, data: dict) -> Path:
        config_path = tmp_path / ".claude.json"
        config_path.write_text(json.dumps(data, indent=2) + "\n")
        return config_path

    def test_write_is_atomic(self, tmp_path):
        """~/.claude.json holds the user's whole Claude Code config, and Task 4
        makes this path run on every setup --update for plugin users. A bare
        write_text truncates it on a crash mid-write."""
        config_path = self._write_config(tmp_path, {
            "mcpServers": {"ormah": {"command": "/usr/bin/ormah"}, "other": {"command": "/usr/bin/other"}}
        })

        with patch("ormah.setup._atomic_write") as atomic_write:
            _remove_mcp_from_json(config_path)

        atomic_write.assert_called_once()
        written_path = atomic_write.call_args[0][0]
        assert str(written_path) == str(config_path)
        payload = json.loads(atomic_write.call_args[0][1])
        assert payload["mcpServers"] == {"other": {"command": "/usr/bin/other"}}

    def test_removes_ormah_and_keeps_co_tenants(self, tmp_path):
        config_path = self._write_config(tmp_path, {
            "mcpServers": {"ormah": {"command": "/usr/bin/ormah"}, "other": {"command": "/usr/bin/other"}},
            "theme": "dark",
        })

        _remove_mcp_from_json(config_path)

        result = json.loads(config_path.read_text())
        assert result["mcpServers"] == {"other": {"command": "/usr/bin/other"}}
        assert result["theme"] == "dark"

    def test_drops_mcp_servers_key_when_ormah_was_the_only_entry(self, tmp_path):
        config_path = self._write_config(tmp_path, {"mcpServers": {"ormah": {"command": "/usr/bin/ormah"}}})

        _remove_mcp_from_json(config_path)

        assert "mcpServers" not in json.loads(config_path.read_text())

    def test_no_write_when_ormah_absent(self, tmp_path):
        config_path = self._write_config(tmp_path, {"mcpServers": {"other": {"command": "/usr/bin/other"}}})

        with patch("ormah.setup._atomic_write") as atomic_write:
            _remove_mcp_from_json(config_path)

        atomic_write.assert_not_called()

    def test_missing_file_is_a_no_op(self, tmp_path):
        _remove_mcp_from_json(tmp_path / "nope.json")  # must not raise

    def test_corrupt_file_is_left_untouched(self, tmp_path):
        config_path = tmp_path / ".claude.json"
        config_path.write_text("{not json")

        _remove_mcp_from_json(config_path)

        assert config_path.read_text() == "{not json"
```

- [ ] **Step 2: Run the tests to verify the atomicity test fails**

Run: `python -m pytest tests/test_setup.py::TestRemoveMcpFromJson -v`

Expected: `test_write_is_atomic` **FAILS** with `AssertionError: Expected '_atomic_write' to have been called once. Called 0 times.` — the function still uses `write_text`. The other five pass (current behaviour, kept as a guard).

- [ ] **Step 3: Write the implementation**

In `src/ormah/setup.py`, change the final write of `_remove_mcp_from_json`:

```python
def _remove_mcp_from_json(config_path: Path) -> None:
    """Remove ormah entry from mcpServers in a JSON config file."""
    if not config_path.exists():
        return
    try:
        data = json.loads(config_path.read_text())
    except (json.JSONDecodeError, ValueError):
        warn(f"Could not parse {config_path} — skipping")
        return

    mcp_servers = data.get("mcpServers", {})
    if "ormah" not in mcp_servers:
        return

    del mcp_servers["ormah"]
    if not mcp_servers:
        del data["mcpServers"]
    else:
        data["mcpServers"] = mcp_servers

    _atomic_write(str(config_path), json.dumps(data, indent=2) + "\n")
    ok(f"Removed ormah from {config_path}")
```

Only the write changes — `_atomic_write` takes a `str` path, hence `str(config_path)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup.py::TestRemoveMcpFromJson -v`
Expected: 6 passed.

Then confirm no existing uninstall test regressed:

Run: `python -m pytest tests/test_setup.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): write ~/.claude.json atomically when removing the ormah MCP entry

_remove_claude_hooks already writes through _atomic_write; its sibling
_remove_mcp_from_json ended in a bare write_text against ~/.claude.json — the
file holding the user's whole Claude Code config. A crash mid-write truncates
it.

Refs #145"
```

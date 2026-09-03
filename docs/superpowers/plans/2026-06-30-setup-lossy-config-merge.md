# Setup Lossy Config Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ormah setup` preserve pre-existing user content (third-party hooks under shared events, and `.env` comments/ordering) instead of clobbering it.

**Architecture:** Promote the existing nested `_is_ormah_hook` to a module-level helper — made **argv-aware** (parses the command, matches `<…>/ormah whisper inject|store`) so a third-party command that merely contains the substring is never misclassified. Add a pure `_merge_hooks` that strips prior Ormah entries per event and appends current ones (preserving co-tenants), route both `configure_*_hooks` through a shared `_install_hooks` reader/merger/writer that is **fail-closed on unparseable JSON** (warns and aborts without writing, mirroring uninstall), and rewrite `_write_env_file` to edit the existing file in place. `_merge_json_file` is unchanged (still correct for `mcpServers`).

**Branch:** implemented on `fix/setup-lossy-config-merge` off synced `main` (= origin/main) — NOT local-main — for a clean upstream PR to r-spade/ormah#70.

**Council revisions (2026-06-30):** Run 1 (53053253) — both peers converged on 3 issues now folded in: (HIGH) fail-closed on corrupt JSON; (MEDIUM) argv-aware hook detection; (MEDIUM) inline-comment scope on `.env`. Run 2 (b02d98de) on the revised plan caught 2 more, also folded in: (HIGH) `_install_hooks` must return success so `configure_*_hooks` never report "installed" after a fail-closed abort; (MEDIUM) `_is_ormah_hook` must also recognize the plugin wrapper form (`ormah-whisper-inject`/`-store`, see integrations/claude-plugin/hooks/hooks.json), which neither the old substring nor the first argv-aware version matched. See `.council/council-result.md`.

**Tech Stack:** Python 3.11, pytest, `unittest.mock.patch`. Tests live in `tests/test_setup.py`.

Spec: `docs/superpowers/specs/2026-06-30-setup-lossy-config-merge-design.md` · Issue: r-spade/ormah#70.

**Run tests with the project venv:** `.venv/bin/python -m pytest tests/test_setup.py -v`

---

## File structure

- Modify `src/ormah/setup.py`:
  - Add module-level `_is_ormah_hook` and `_merge_hooks` and `_install_hooks`.
  - Remove the two nested `_is_ormah_hook` defs (`:691-693`, `:1250-1252`) — use the module-level one.
  - Rewire `configure_claude_hooks` (`:155-197`) and `configure_codex_hooks` (`:275-307`) to `_install_hooks`.
  - Rewrite `_write_env_file` (`:769-776`).
- Modify `tests/test_setup.py`: new tests for `_merge_hooks`, co-tenant/idempotency for both hook configs, and `.env` preservation.

---

## Task 1: `_is_ormah_hook` + `_merge_hooks` (pure helpers)

**Files:**
- Modify: `src/ormah/setup.py` (add module-level helpers near `_merge_json_file`, ~`:130`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_setup.py` (import `_merge_hooks` from `ormah.setup` in the existing import block):

```python
class TestMergeHooks:
    ORMAH = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "/x/ormah whisper inject"}]}]}

    def test_preserves_cotenant_under_same_event(self):
        from ormah.setup import _merge_hooks
        existing = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other-tool"}]}]}
        merged = _merge_hooks(existing, self.ORMAH)
        cmds = [h["command"] for m in merged["UserPromptSubmit"] for h in m["hooks"]]
        assert "other-tool" in cmds
        assert "/x/ormah whisper inject" in cmds

    def test_idempotent_no_duplicate_ormah(self):
        from ormah.setup import _merge_hooks
        once = _merge_hooks({}, self.ORMAH)
        twice = _merge_hooks(once, self.ORMAH)
        cmds = [h["command"] for m in twice["UserPromptSubmit"] for h in m["hooks"]]
        assert cmds.count("/x/ormah whisper inject") == 1

    def test_leaves_unclaimed_events_untouched(self):
        from ormah.setup import _merge_hooks
        existing = {"PreToolUse": [{"hooks": [{"type": "command", "command": "rtk hook claude"}]}]}
        merged = _merge_hooks(existing, self.ORMAH)
        assert merged["PreToolUse"] == existing["PreToolUse"]

    def test_substring_collision_not_stripped(self):
        # Council HIGH/MEDIUM: a third-party command merely CONTAINING the
        # substring "whisper inject" must survive (argv-aware detection).
        from ormah.setup import _merge_hooks
        existing = {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "/opt/whisper inject-backup run"}]}]}
        merged = _merge_hooks(existing, self.ORMAH)
        cmds = [h["command"] for m in merged["UserPromptSubmit"] for h in m["hooks"]]
        assert "/opt/whisper inject-backup run" in cmds


class TestIsOrmahHook:
    def test_matches_real_ormah_hook(self):
        from ormah.setup import _is_ormah_hook
        assert _is_ormah_hook({"command": "/usr/bin/ormah whisper inject"})
        assert _is_ormah_hook({"command": "/abs/path/ormah whisper store"})

    def test_matches_plugin_wrapper_form(self):
        # Council MEDIUM: the Claude plugin installs wrapper scripts, not the CLI form.
        from ormah.setup import _is_ormah_hook
        assert _is_ormah_hook({"command": "/x/plugin/bin/ormah-whisper-inject"})
        assert _is_ormah_hook({"command": "/x/plugin/bin/ormah-whisper-store"})

    def test_rejects_substring_collision(self):
        from ormah.setup import _is_ormah_hook
        assert not _is_ormah_hook({"command": "/opt/whisper inject-backup run"})
        assert not _is_ormah_hook({"command": "tools/whisper store-archive"})

    def test_rejects_malformed_command(self):
        from ormah.setup import _is_ormah_hook
        assert not _is_ormah_hook({"command": ""})
        assert not _is_ormah_hook({})
        assert not _is_ormah_hook({"command": "unterminated 'quote"})
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestMergeHooks -v`
Expected: FAIL — `ImportError: cannot import name '_merge_hooks'`.

- [ ] **Step 3: Implement helpers**

Add `import shlex` to the imports at the top of `src/ormah/setup.py` (next to the existing `import os` / `import json`). `Path` is already imported from `pathlib`.

In `src/ormah/setup.py`, add at module level (after `_merge_json_file`):

```python
def _is_ormah_hook(entry: dict) -> bool:
    """True when a hook entry is one Ormah installs (argv-aware, not substring).

    Recognizes BOTH install forms:
      - CLI (ormah setup): `<...>/ormah whisper inject|store`
      - Plugin wrapper: `<...>/ormah-whisper-inject` | `<...>/ormah-whisper-store`
        (see integrations/claude-plugin/hooks/hooks.json)
    A third-party command that merely contains the substring "whisper inject"/
    "whisper store" is never misclassified. Works for install dedup and uninstall
    alike, and is resilient to the ormah binary path changing between runs.
    """
    try:
        parts = shlex.split(entry.get("command", ""))
    except ValueError:
        return False
    if not parts:
        return False
    name = Path(parts[0]).name
    if name in ("ormah-whisper-inject", "ormah-whisper-store"):
        return True  # plugin wrapper form
    return (
        len(parts) >= 3
        and name == "ormah"
        and parts[1] == "whisper"
        and parts[2] in ("inject", "store")
    )  # CLI form


def _merge_hooks(existing: dict, ormah_hooks: dict) -> dict:
    """Merge Ormah hook groups into an existing hooks dict, preserving co-tenants.

    For each event Ormah claims: strip prior Ormah entries (via _is_ormah_hook),
    keep every third-party hook, then append Ormah's matchers. Events Ormah does
    not claim are left untouched. Idempotent.
    """
    merged = dict(existing)
    for event, ormah_matchers in ormah_hooks.items():
        current = merged.get(event)
        if not isinstance(current, list):
            current = []
        cleaned = []
        for matcher in current:
            if not isinstance(matcher, dict):
                cleaned.append(matcher)
                continue
            kept = [h for h in matcher.get("hooks", []) if not _is_ormah_hook(h)]
            if kept:
                cleaned.append({**matcher, "hooks": kept})
        merged[event] = cleaned + list(ormah_matchers)
    return merged
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestMergeHooks tests/test_setup.py::TestIsOrmahHook -v`
Expected: PASS (TestMergeHooks: 4 tests, TestIsOrmahHook: 4 tests).

- [ ] **Step 5: Remove the two nested `_is_ormah_hook` defs**

Delete the local `def _is_ormah_hook(entry: dict) -> bool:` blocks at `src/ormah/setup.py:691-693` and `:1245-1247` (the surrounding loops already call `_is_ormah_hook`, now resolved at module level). Note: the promoted predicate is stricter (argv-aware) than the old substring match — verified safe because every existing uninstall test uses the `…/ormah whisper inject|store` form, which the new predicate still matches.

Also add a regression test in the existing uninstall test class (`TestRemoveClaudeHooks`) proving the promoted predicate now removes the **plugin wrapper form** (the old substring `"whisper inject" in "ormah-whisper-inject"` was false, so uninstall never cleaned it):

```python
    def test_removes_plugin_wrapper_hook(self, tmp_path):
        # _is_ormah_hook is now argv/basename-aware, so uninstall cleans the
        # plugin form too. Use the same patching/entry point as the sibling
        # uninstall tests in this class.
        import json
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "/x/plugin/bin/ormah-whisper-inject"}]}]}}))
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            _remove_claude_hooks()  # match the actual uninstall entry point used by siblings
        data = json.loads(sp.read_text())
        cmds = [h["command"] for m in data.get("hooks", {}).get("UserPromptSubmit", []) for h in m["hooks"]]
        assert "/x/plugin/bin/ormah-whisper-inject" not in cmds
```

> Implementer note: mirror the exact patch targets and uninstall function name (`_remove_claude_hooks` or equivalent) used by the other tests in `TestRemoveClaudeHooks` — confirm by reading that class first.

Run: `.venv/bin/python -m pytest tests/test_setup.py -k "hook or Hook" -v`
Expected: PASS (existing uninstall tests still green + the new plugin-form test).

- [ ] **Step 6: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "refactor(setup): module-level _is_ormah_hook + _merge_hooks helper"
```

---

## Task 2: Route `configure_claude_hooks` through `_install_hooks`

**Files:**
- Modify: `src/ormah/setup.py` (add `_install_hooks`; edit `configure_claude_hooks` `:155-197`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests**

```python
class TestConfigureClaudeHooksMerge:
    def test_preserves_existing_userpromptsubmit_hook(self, tmp_path):
        from ormah.setup import configure_claude_hooks
        import json
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "other-tool"}]}]}}))
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            configure_claude_hooks("/abs/ormah")
        data = json.loads(sp.read_text())
        cmds = [h["command"] for m in data["hooks"]["UserPromptSubmit"] for h in m["hooks"]]
        assert "other-tool" in cmds
        assert "/abs/ormah whisper inject" in cmds

    def test_rerun_does_not_duplicate(self, tmp_path):
        from ormah.setup import configure_claude_hooks
        import json
        sp = tmp_path / "settings.json"
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            configure_claude_hooks("/abs/ormah")
            configure_claude_hooks("/abs/ormah")
        data = json.loads(sp.read_text())
        cmds = [h["command"] for m in data["hooks"]["UserPromptSubmit"] for h in m["hooks"]]
        assert cmds.count("/abs/ormah whisper inject") == 1

    def test_preserves_existing_precompact_and_sessionend(self, tmp_path):
        # Council: co-tenant coverage must include every event Ormah claims.
        from ormah.setup import configure_claude_hooks
        import json
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({"hooks": {
            "PreCompact": [{"hooks": [{"type": "command", "command": "other-precompact"}]}],
            "SessionEnd": [{"hooks": [{"type": "command", "command": "other-sessionend"}]}],
        }}))
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            configure_claude_hooks("/abs/ormah")
        data = json.loads(sp.read_text())
        pre = [h["command"] for m in data["hooks"]["PreCompact"] for h in m["hooks"]]
        end = [h["command"] for m in data["hooks"]["SessionEnd"] for h in m["hooks"]]
        assert "other-precompact" in pre and "/abs/ormah whisper store" in pre
        assert "other-sessionend" in end and "/abs/ormah whisper store" in end

    def test_corrupt_json_left_unchanged_and_no_false_success(self, tmp_path, capsys):
        # Council HIGH: unparseable settings.json must NOT be overwritten, and
        # setup must NOT report success when the write was aborted.
        from ormah.setup import configure_claude_hooks
        sp = tmp_path / "settings.json"
        sp.write_text('{ "theme": "dark", BROKEN')
        before = sp.read_text()
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            configure_claude_hooks("/abs/ormah")
        assert sp.read_text() == before  # byte-for-byte unchanged
        # Council MEDIUM: assert the specific SUCCESS marker is absent — do NOT
        # match on "installed" (the abort warning itself contains that word).
        assert "Whisper hooks installed" not in capsys.readouterr().out

    def test_non_object_json_left_unchanged(self, tmp_path):
        # Council HIGH: a valid-but-non-object JSON root (list/string) must
        # fail closed, not raise AttributeError nor overwrite.
        from ormah.setup import configure_claude_hooks
        sp = tmp_path / "settings.json"
        sp.write_text('["not", "an", "object"]')
        before = sp.read_text()
        with patch("ormah.setup.os.path.expanduser", return_value=str(sp)):
            configure_claude_hooks("/abs/ormah")
        assert sp.read_text() == before
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestConfigureClaudeHooksMerge -v`
Expected: FAIL — `test_preserves_existing_userpromptsubmit_hook` fails (`other-tool` missing: list was replaced).

- [ ] **Step 3: Add `_install_hooks` and rewire**

Add at module level (after `_merge_hooks`):

Add `import tempfile` to the imports at the top of `src/ormah/setup.py` (next to `import shlex`).

```python
def _atomic_write(path: str, text: str, mode: int | None = None) -> None:
    """Write text to `path` atomically (temp file in the same dir + os.replace).

    Prevents a crash mid-write from leaving a truncated/corrupt config — the
    target is either the old bytes or the full new bytes, never a partial file.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _install_hooks(path: str, ormah_hooks: dict) -> bool:
    """Read a JSON hooks config, merge Ormah hooks preserving co-tenants, write back.

    Returns True if the merged config was written, False if it aborted without
    writing. Fail-closed: if the file exists but does not parse OR does not hold a
    JSON object, warn and abort (mirrors the uninstall no-op) so a hand-edited
    config with a transient syntax error is never replaced by a hooks-only file,
    losing theme/permissions. The write is atomic (no partial-write corruption).
    """
    existing: dict = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            warn(f"Could not parse {path} — leaving it unchanged; hooks not configured")
            return False
        if not isinstance(existing, dict):
            warn(f"{path} is not a JSON object — leaving it unchanged; hooks not configured")
            return False
    current = existing.get("hooks")
    if not isinstance(current, dict):
        current = {}
    existing["hooks"] = _merge_hooks(current, ormah_hooks)
    _atomic_write(path, json.dumps(existing, indent=2) + "\n")
    return True
```

In `configure_claude_hooks`, replace the final two lines — `_merge_json_file(settings_path, {"hooks": hooks})` (`:196`) and the `ok(...)` (`:197`) — with a success-gated report (Council HIGH: never report success when the write was aborted):

```python
    if _install_hooks(settings_path, hooks):
        ok("Whisper hooks installed — memories flow before every message")
```

(Leave the `hooks = {...}` construction unchanged. The `warn(...)` inside `_install_hooks` already explains the abort.)

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestConfigureClaudeHooksMerge -v`
Expected: PASS (5 tests). Also run existing: `.venv/bin/python -m pytest tests/test_setup.py -k claude -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): preserve co-tenant Claude hooks on install (#70)"
```

---

## Task 3: Route `configure_codex_hooks` through `_install_hooks`

**Files:**
- Modify: `src/ormah/setup.py` (edit `configure_codex_hooks` `:275-307`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests**

```python
class TestConfigureCodexHooksMerge:
    def test_preserves_existing_stop_hook(self, tmp_path):
        from ormah.setup import configure_codex_hooks
        import json
        codex = tmp_path / ".codex"
        codex.mkdir()
        hp = codex / "hooks.json"
        hp.write_text(json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "other-stop"}]}]}}))
        with patch("ormah.setup.Path.home", return_value=tmp_path), \
             patch("ormah.setup._enable_codex_feature"):
            configure_codex_hooks("/abs/ormah")
        data = json.loads(hp.read_text())
        cmds = [h["command"] for m in data["hooks"]["Stop"] for h in m["hooks"]]
        assert "other-stop" in cmds
        assert "/abs/ormah whisper store" in cmds

    def test_rerun_does_not_duplicate(self, tmp_path):
        from ormah.setup import configure_codex_hooks
        import json
        with patch("ormah.setup.Path.home", return_value=tmp_path), \
             patch("ormah.setup._enable_codex_feature"):
            configure_codex_hooks("/abs/ormah")
            configure_codex_hooks("/abs/ormah")
        data = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
        cmds = [h["command"] for m in data["hooks"]["UserPromptSubmit"] for h in m["hooks"]]
        assert cmds.count("/abs/ormah whisper inject") == 1

    def test_corrupt_hooks_json_no_false_success(self, tmp_path, capsys):
        # Council MEDIUM: symmetry with Claude — corrupt hooks.json must not be
        # overwritten, the feature flag must NOT be enabled, and no success report.
        from ormah.setup import configure_codex_hooks
        codex = tmp_path / ".codex"
        codex.mkdir()
        hp = codex / "hooks.json"
        hp.write_text('{ BROKEN')
        before = hp.read_text()
        with patch("ormah.setup.Path.home", return_value=tmp_path), \
             patch("ormah.setup._enable_codex_feature") as enable:
            configure_codex_hooks("/abs/ormah")
        assert hp.read_text() == before          # unchanged
        enable.assert_not_called()               # feature flag not enabled
        assert "Codex hooks installed" not in capsys.readouterr().out
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestConfigureCodexHooksMerge -v`
Expected: FAIL — `other-stop` missing (list replaced).

- [ ] **Step 3: Rewire**

In `configure_codex_hooks`, replace `_merge_json_file(str(hooks_path), {"hooks": hooks})` (`:305`) and the following `_enable_codex_feature(...)` / `ok(...)` lines with a success-gated block (Council HIGH: don't enable the feature flag or report success when the write was aborted):

```python
    if _install_hooks(str(hooks_path), hooks):
        _enable_codex_feature("hooks", deprecated_feature_names=("codex_hooks",))
        ok("Codex hooks installed — memories flow before every message")
```

(Leave the `hooks_path` / `hooks = {...}` construction unchanged.)

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestConfigureCodexHooksMerge -v`
Expected: PASS (3 tests). Also: `.venv/bin/python -m pytest tests/test_setup.py -k codex -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): preserve co-tenant Codex hooks on install (#70)"
```

---

## Task 4: Rewrite `_write_env_file` to preserve comments/order

**Files:**
- Modify: `src/ormah/setup.py` (`_write_env_file` `:769-776`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests**

```python
class TestWriteEnvPreservation:
    def test_preserves_comments_and_manual_key(self, tmp_path):
        from ormah.setup import _write_env_file, _read_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("# header comment\nMANUAL_KEY=keep\n\nORMAH_X=old\n")
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            _write_env_file({"MANUAL_KEY": "keep", "ORMAH_X": "new"})
        text = env_path.read_text()
        assert "# header comment" in text
        assert "MANUAL_KEY=keep" in text
        assert "ORMAH_X=new" in text
        assert "ORMAH_X=old" not in text

    def test_removed_key_dropped_comments_kept(self, tmp_path):
        from ormah.setup import _write_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("# keep me\nDROP=1\nKEEP=2\n")
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            _write_env_file({"KEEP": "2"})
        text = env_path.read_text()
        assert "# keep me" in text
        assert "KEEP=2" in text
        assert "DROP" not in text

    def test_new_key_appended(self, tmp_path):
        from ormah.setup import _write_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("# c\nA=1\n")
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            _write_env_file({"A": "1", "B": "2"})
        lines = [l for l in env_path.read_text().splitlines() if l.strip()]
        assert lines[-1] == "B=2"
        assert "# c" in env_path.read_text()

    def test_nonexistent_file_writes_dict_order(self, tmp_path):
        # Spec: non-existent file falls back to a plain dict-order write.
        from ormah.setup import _write_env_file
        env_path = tmp_path / ".env"
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            _write_env_file({"A": "1", "B": "2"})
        assert env_path.read_text() == "A=1\nB=2\n"

    def test_untouched_key_with_inline_comment_preserved(self, tmp_path):
        # Council MEDIUM (scoped): inline comment on an UNTOUCHED key survives,
        # because _read_env_file keeps it as part of the value. (A key whose
        # value Ormah rewrites loses its inline comment — documented non-goal.)
        from ormah.setup import _read_env_file, _write_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("MANUAL=val  # keep this note\n")
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            env = _read_env_file()
            _write_env_file(env)
        assert "# keep this note" in env_path.read_text()
```

Also add a regression test in the existing LLM-config test area to prove `configure_llm()` no longer strips block comments (it currently round-trips through `_read_env_file`/`_write_env_file`):

```python
    def test_configure_llm_preserves_block_comment(self, tmp_path, monkeypatch):
        # Council MEDIUM: real flow — a header comment in .env survives a config change.
        from ormah.setup import _write_env_file, _read_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("# my ormah config\nORMAH_LLM_PROVIDER=none\n")
        with patch("ormah.setup.ENV_PATH", env_path), patch("ormah.setup.ENV_DIR", tmp_path):
            env = _read_env_file()
            env["ORMAH_LLM_PROVIDER"] = "ollama"
            _write_env_file(env)
        text = env_path.read_text()
        assert "# my ormah config" in text
        assert "ORMAH_LLM_PROVIDER=ollama" in text
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestWriteEnvPreservation -v`
Expected: FAIL — comments stripped / `ORMAH_X=old` still present (whole-file rebuild from dict).

- [ ] **Step 3: Rewrite `_write_env_file`**

Replace the body of `_write_env_file` (`src/ormah/setup.py:769-776`) with:

```python
def _write_env_file(env: dict[str, str]) -> None:
    """Write env dict to the global config file, preserving comments and ordering.

    Existing KEY= lines are updated in place; keys absent from `env` are dropped;
    full-line comments, blank lines, and ordering are kept verbatim; new keys
    append at end.

    CONTRACT: callers MUST pass the FULL env (from `_read_env_file()`) unless they
    intentionally want absent keys removed — a partial dict deletes the missing
    user keys. Non-goal: an inline trailing comment on a key whose VALUE this call
    rewrites is dropped (full-line comments and untouched keys keep theirs).
    """
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    original = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in original:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in env:
                out.append(f"{key}={env[key]}")
                seen.add(key)
            # key removed by caller -> drop the line
        else:
            out.append(line)  # comment / blank / other -> verbatim
    for key, value in env.items():
        if key not in seen:
            out.append(f"{key}={value}")
    _atomic_write(str(ENV_PATH), "\n".join(out) + "\n", mode=0o600)
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_setup.py::TestWriteEnvPreservation -v`
Expected: PASS (5 tests + the `configure_llm` block-comment regression test).

- [ ] **Step 5: Full setup suite — no regression**

Run: `.venv/bin/python -m pytest tests/test_setup.py tests/test_setup_json.py -v`
Expected: PASS (all existing + new). If pre-existing environmental failures appear (see project memory on `.env` env leak), confirm they are unrelated to this change.

- [ ] **Step 6: Commit**

```bash
git add src/ormah/setup.py tests/test_setup.py
git commit -m "fix(setup): preserve .env comments and ordering on write (#70)"
```

---

## Self-review notes

- **Spec coverage:** goals 1-2 (hook preservation + idempotency) → Tasks 1-3; goal 3 (`.env` preservation) → Task 4. Non-goals untouched (MCP/TOML/CLAUDE.md/uninstall paths not edited; `_merge_json_file` retained for `mcpServers`).
- **Type consistency:** `_merge_hooks(existing, ormah_hooks) -> dict`, `_install_hooks(path: str, ormah_hooks: dict)`, `_is_ormah_hook(entry: dict) -> bool` used consistently across tasks.
- **Worktree note:** if executed in a git worktree, run pytest with `PYTHONPATH="$WT/src"` — the editable `.venv` otherwise imports the main checkout (project memory `700b0a52`).

### Task 2: The adapter runs in the workspace with thinking off

**Goal:** four small changes in the adapter so the child reads Ormah's `CLAUDE.md` instead of the
operator's, and never switches extended thinking on.

**Files:**
- Modify: `src/ormah/background/llm/claude_cli_adapter.py` (lines 12, 48–51, ~176–182, ~207–215, ~228)
- Test: `tests/test_background/test_claude_cli_adapter.py`

**Interfaces:**
- Consumes: nothing from Task 1 at import time — the adapter takes an already-resolved `Path`.
- Produces, for Task 3: `ClaudeCliAdapter(model, timeout, bin_path, max_concurrency, *, workspace_dir: Path)`.
  `workspace_dir` is **keyword-only and required**.

Why required with no default: a default of `None` meaning "use the tempdir" would silently restore
the contaminated behaviour, and a default that materialises a real workspace would make the test
suite write into the operator's real HOME. There is no safe default, so there is none.

Why `alwaysThinkingEnabled` matters: `34c41cd` was reverted because dropping the operator's settings
also dropped their `"alwaysThinkingEnabled": false`. The CLI fell back to its default, thinking
switched on, `output_tokens` went 742 → 14,203 (13,682 of it thinking), `ttft` went 9.6s → 152.4s,
and calls blew the 160s timeout. Passing it inline was measured to win under
`--setting-sources project`. This one key is the whole fix.

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_claude_cli_adapter.py`:

```python
def test_argv_pins_the_project_setting_source(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("hi")
    # "project" and never "": the empty value drops the operator's settings, and with them
    # alwaysThinkingEnabled:false -- the regression that got 34c41cd reverted.
    assert popen.argv[popen.argv.index("--setting-sources") + 1] == "project"


def test_the_child_runs_in_the_judge_workspace_not_the_tempdir(monkeypatch, tmp_path):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku", workspace_dir=tmp_path).generate("hi")
    # --setting-sources project resolves CLAUDE.md relative to cwd, so cwd IS the mechanism.
    assert popen.kwargs["cwd"] == tmp_path


def test_hardened_settings_switch_extended_thinking_off(monkeypatch):
    popen = _fake_popen(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(subprocess, "Popen", popen)
    _adapter(model="haiku").generate("hi")
    settings = json.loads(popen.argv[popen.argv.index("--settings") + 1])
    assert settings["alwaysThinkingEnabled"] is False
```

- [ ] **Step 2: Add the test helper and retarget the existing constructions**

The three new tests call `_adapter(...)`, which does not exist yet, and `workspace_dir` is about to
become required — which breaks all 32 existing direct constructions at once. Do both in one step.

First rewrite every construction, then add the helper (added afterwards, so the `sed` cannot
rewrite the helper's own body):

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
sed -i '' 's/ClaudeCliAdapter(/_adapter(/g' tests/test_background/test_claude_cli_adapter.py
grep -c "_adapter(" tests/test_background/test_claude_cli_adapter.py
```

Expected: `35` (the 32 pre-existing constructions plus the 3 new calls added in Step 1).

The import line survives untouched because it has no `(` after the class name — confirm:

```bash
grep -n "import ClaudeCliAdapter" tests/test_background/test_claude_cli_adapter.py
```

Expected: one line, still naming `ClaudeCliAdapter`.

Now add the helper immediately after the `_fake_popen` definition (which ends around line 99):

```python
# The tests never spawn a real child -- Popen is always faked -- so this path is only ever
# handed to the fake as `cwd`. It is deliberately NOT created on disk.
WORKSPACE = Path("/tmp/ormah-judge-workspace-under-test")


def _adapter(**kwargs):
    """Build the adapter with a stand-in workspace. `workspace_dir` is required and has no safe
    default in production, so every test supplies one; overriding it stays possible per call."""
    kwargs.setdefault("workspace_dir", WORKSPACE)
    return ClaudeCliAdapter(**kwargs)
```

If `Path` is not already imported in this test file, add `from pathlib import Path` to its imports.

- [ ] **Step 3: Run the tests to verify they fail**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q 2>&1 | tail -6
```

Expected: failures including
`TypeError: __init__() got an unexpected keyword argument 'workspace_dir'`.
That error appearing on *every* test is correct at this point — the helper now passes a keyword the
adapter does not accept yet.

- [ ] **Step 4: Write the minimal implementation**

Four edits in `src/ormah/background/llm/claude_cli_adapter.py`.

**(a)** Remove the now-unused import at line 12 — leaving it fails `ruff` with `F401`:

```python
import tempfile          # DELETE this line
```

**(b)** Add the thinking key to `_HARDENED_SETTINGS` (line 48):

```python
_HARDENED_SETTINGS = json.dumps({
    "disableAllHooks": True,
    # Without this the CLI falls back to its thinking-on default the moment the operator's
    # settings stop being read. Measured: 13,682 thinking tokens and ttft 9.6s -> 152.4s,
    # which is what blew the timeout and got 34c41cd reverted.
    "alwaysThinkingEnabled": False,
    "permissions": {"defaultMode": "default", "allow": [], "deny": _DENY_TOOLS},
})
```

**(c)** Accept and store the workspace in `__init__`:

```python
    def __init__(
        self,
        model: str,
        timeout: int = 120,
        bin_path: str | None = None,
        max_concurrency: int = 1,
        *,
        workspace_dir: Path,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.bin_path = bin_path or shutil.which("claude") or "claude"
        self.max_concurrency = max(1, max_concurrency)
        # Keyword-only and required: there is no safe default. None-means-tempdir would
        # silently restore the contaminated behaviour, and a real default would make the
        # test suite write into the operator's HOME.
        self.workspace_dir = workspace_dir
```

**(d)** Add the flag to `argv` and point `cwd` at the workspace:

```python
        argv = [
            self.bin_path, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--no-session-persistence",
            "--permission-mode", "default",
            "--settings", _HARDENED_SETTINGS,
            # "project" reads the CLAUDE.md in cwd (ours) instead of the operator's user-level
            # file. Never "" -- that drops the operator's settings wholesale, thinking included.
            "--setting-sources", "project",
        ]
```

and, in the `subprocess.Popen(...)` call:

```python
                    stderr=subprocess.PIPE, text=True, cwd=self.workspace_dir, env=env,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_claude_cli_adapter.py -q 2>&1 | tail -3
```

Expected: `31 passed, 8 deselected` — the file's 28 previously-selected tests plus the 3 new ones.

- [ ] **Step 6: Confirm ruff is clean**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`. An `F401 tempfile imported but unused` here means edit (a) was
skipped.

- [ ] **Step 7: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
git add src/ormah/background/llm/claude_cli_adapter.py tests/test_background/test_claude_cli_adapter.py
git commit -m "feat(llm): run claude -p in the judge workspace with thinking off

--setting-sources project makes the child read the workspace CLAUDE.md instead
of the operator's, so cwd becomes the mechanism and workspace_dir is required
with no safe default. alwaysThinkingEnabled:false is the missing key that made
34c41cd blow its timeout.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git show --stat HEAD | head -6
```

Expected: exactly 2 files in the commit stat.

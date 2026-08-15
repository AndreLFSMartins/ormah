# Task 3: Patch the seam the tests meant (group C — 3 tests)

Read `00-overview.md` first — its Global Constraints apply here.

Targets: `TestConfigureCodexMcp::{test_writes_mcp_config_to_codex_toml, test_preserves_existing_toml_content, test_replaces_existing_ormah_block}`.

**Files:**
- Modify: `tests/test_setup.py:811`, `:835`, `:860`

**Interfaces:**
- Consumes: nothing from Task 2. Independent — a reviewer can reject this task while approving Task 2.
- Produces: nothing consumed downstream.

**Why:** the tests patch `ormah.setup.shutil.which` → `None` to mean "codex is not installed". But `configure_codex_mcp` (`setup.py:629`) calls `_find_binary("codex")`, and `_find_binary` (`setup.py:36`) only *starts* at `shutil.which` (`:43`); on a miss it scans mise shims, nvm versions, `~/.local/bin`, `/usr/local/bin` and `/opt/homebrew/bin`. A machine with codex installed still resolves it, `subprocess.run` really runs, and `assert_not_called` fails.

That scan is deliberate and documented at `setup.py:37-42` — GUI apps launched from the system tray do not inherit the shell PATH. The function is right; the test picked the wrong seam.

- [ ] **Step 1: Confirm the 3 still fail**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso
$PY -m pytest tests/test_setup.py::TestConfigureCodexMcp -p no:randomly
```

Expected: `3 failed, 2 passed` (the class holds 5 tests), each failure reading `AssertionError: Expected 'run' to not have been called. Called 1 times.` with a call to `/opt/homebrew/bin/codex` in the detail.

- [ ] **Step 2: Repoint the three mocks**

In `tests/test_setup.py`, at lines 811, 835 and 860, replace this exact line:

```python
            patch("ormah.setup.shutil.which", return_value=None),
```

with:

```python
            patch("ormah.setup._find_binary", return_value=None),
```

**A naive "replace all" on that line is wrong — the string appears 5 times in the file**, not 3. Lines 326 and 344 also patch `shutil.which` to `None`, in unrelated passing tests, using a different syntax (`with patch(...), \`). Anchor the replacement on the three-line block instead, which is unique to this class:

```python
            patch("ormah.setup.shutil.which", return_value=None),
            patch("ormah.setup.subprocess.run") as mock_run,
            patch("ormah.setup.Path.home", return_value=tmp_path),
```

**Do not touch line 877.** That one belongs to `test_uses_codex_cli_when_available`, which patches `shutil.which` to *return* a path, passes today, and legitimately covers the PATH-hit route. Changing it would delete real coverage.

Verify the edit landed on exactly 3 lines before moving on: `git diff --stat tests/test_setup.py` must read `3 insertions(+), 3 deletions(-)`.

- [ ] **Step 3: Confirm green**

```bash
$PY -m pytest tests/test_setup.py::TestConfigureCodexMcp -p no:randomly
```

Expected: `5 passed`.

- [ ] **Step 4: Confirm the patched name really exists**

```bash
$PY -c "from ormah.setup import _find_binary; print(_find_binary)"
```

Expected: a function object. `unittest.mock.patch` raises `AttributeError` on a missing attribute, so Step 3 passing already proves this — this step just makes the reason explicit for the reviewer.

- [ ] **Step 5: Commit**

```bash
git add tests/test_setup.py
git diff --cached --stat
git commit -m "test(setup): patch _find_binary, not shutil.which

These tests mean 'codex is not installed', but configure_codex_mcp resolves
the binary through _find_binary, which falls back to absolute paths
(/opt/homebrew/bin among them) when shutil.which misses. On a machine with
codex installed the mock was bypassed and subprocess.run really ran.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Confirm `--stat` shows 1 file, 3 lines changed.

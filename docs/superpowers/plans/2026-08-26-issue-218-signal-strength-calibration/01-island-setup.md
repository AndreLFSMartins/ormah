### Task 1: Clean island + proven import gate

**Files:**
- Create: `../ormah-wt-218/` (git worktree, branch `fix/218-signal-strength-ladder`)

**Interfaces:**
- Consumes: nothing
- Produces: a working directory every later task runs in, and a pytest invocation whose numbers
  describe *this* tree

**Why this is a task and not a preamble:** `VIRTUAL_ENV` exported by the Beta's shell overrides the
island's interpreter, so `sys.path` resolves to the Beta's venv **plus `Tools/ormah/src`** and the
suite goes green against the wrong tree. This has already produced a retracted "98 passed" in this
repo. The gate below is what makes every later test number mean something.

- [ ] **Step 1: Cut the island from `upstream/main`**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/218-signal-strength-ladder ../ormah-wt-218 upstream/main
```

Expected: `Preparing worktree (new branch 'fix/218-signal-strength-ladder')` and `HEAD is now at
90c431e`.

Never `git checkout` this branch inside `Tools/ormah` — launchd `com.ormah.server.dev` serves that
tree.

- [ ] **Step 2: Give the island its own venv**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -q -e ".[dev]"
```

- [ ] **Step 3: Prove which tree you import — this is the gate**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
```

Expected: a path **containing `ormah-wt-218/`**.

If it prints anything under `Tools/ormah/`, STOP. Do not continue, do not run tests, do not report
numbers — the environment is importing the Beta's code and every result would be about the wrong
tree. Re-check that `VIRTUAL_ENV` and `PYTHONPATH` were stripped.

- [ ] **Step 4: Baseline the suite**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-218
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest tests/ -q > /tmp/218-baseline.txt 2>&1
echo "PYTEST_EXIT=$?" >> /tmp/218-baseline.txt
tail -5 /tmp/218-baseline.txt
```

Expected: `PYTEST_EXIT=0`.

`HOME` matters and `env -u` cannot strip it: `Settings.model_config` reads `~/.config/ormah/.env`
before the island's own, and the Beta's copy sets `ORMAH_LLM_PROVIDER=claude_cli`, which
`upstream/main` rejects — `conftest.py` then dies at import with `ValidationError: llm_provider
must be one of {'litellm', 'ollama', 'none'}` before a single test runs.

Never pipe pytest to `tail` directly: the exit code you read becomes `tail`'s, not pytest's.

- [ ] **Step 5: Record the baseline count**

Write the `N passed` figure from `/tmp/218-baseline.txt` into your task report. Every later task
compares against it; a drop means a regression, not a flake.

No commit — this task creates no tracked files.

### Task 4: The live smoke — `thinking_tokens == 0` on a real judge prompt

**Goal:** close the one claim this whole change rests on that has never been tested under load.
Every probe so far used a trivial prompt (`ping`, `17 times 23`). The regression that got `34c41cd`
reverted was thinking scaling on a *real* prompt.

**Files:**
- Create: `tests/test_background/test_claude_cli_live_smoke.py`
- Test: itself

**Interfaces:**
- Consumes, from Task 3: `get_adapter(settings, workspace=...)` returning a `ClaudeCliAdapter` whose
  `workspace_dir` is materialised. From Task 2: the argv and `cwd` the adapter builds.
- Produces: nothing later tasks depend on.

Design note you must not "simplify" away: the test does **not** re-declare the argv. It builds the
real adapter, captures the exact `argv`/`cwd`/`env` the adapter would spawn with, and then executes
*that*. A test that spells out its own flag list would pass while the adapter shipped something
else. The reason the assertion cannot go through `adapter.generate()` is that `generate()` returns
only the envelope's `result` string — usage extraction was reverted in `83351e9` and re-adding it is
out of scope here.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_background/test_claude_cli_live_smoke.py`:

```python
"""Live smoke: the real CLI, the real argv, a real judge prompt, thinking at zero.

Marked `integration`, so `pyproject.toml`'s `addopts = -m 'not integration'` keeps it out of the
fast run. It spawns a real `claude -p` and costs a real call -- run it explicitly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from ormah.background.auto_linker import _LLM_LINK_INSTRUCTIONS
from ormah.background.llm import get_adapter
from ormah.background.llm.pair_batch import build_batch_prompt

pytestmark = pytest.mark.integration

# A pair shaped like the ones the link judge actually sees: two real-length memory records,
# one of them in PT-BR, because the language of `reason` is the signal this change moves.
_PAIR = """PAIR 1
A: [decision] O adapter do claude CLI passa a rodar num workspace dedicado do ormah, com
   --setting-sources project, para o juiz deixar de herdar o CLAUDE.md do operador.
B: [fact] The judge workspace holds a Ormah-authored CLAUDE.md; a .claude directory inside it
   fails closed because a hook declared there executes arbitrary code."""


def _settings(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider="claude_cli",
        llm_model="claude-haiku-4-5",
        claude_cli_timeout_seconds=180,
        claude_cli_bin=shutil.which("claude") or "claude",
        claude_cli_max_concurrency=1,
        memory_dir=tmp_path / "data" / "memory",
    )


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_a_real_judge_prompt_produces_no_thinking_tokens(tmp_path, monkeypatch):
    adapter = get_adapter(_settings(tmp_path))
    assert adapter is not None, "the workspace guard rejected a clean tmp_path workspace"

    # Capture the EXACT argv/cwd/env the adapter would spawn with. Re-declaring the flag list
    # here would let the test pass while the adapter shipped something else.
    captured = {}

    class _Recorder:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            raise RuntimeError("captured")

    monkeypatch.setattr(subprocess, "Popen", _Recorder)
    adapter.generate("hi")          # fails fast inside the adapter; we only want the argv
    monkeypatch.undo()

    assert captured["argv"][captured["argv"].index("--setting-sources") + 1] == "project"
    assert captured["kwargs"]["cwd"] == adapter.workspace_dir

    prompt = build_batch_prompt(_LLM_LINK_INSTRUCTIONS, [_PAIR])
    proc = subprocess.run(
        captured["argv"], input=prompt, cwd=captured["kwargs"]["cwd"],
        env=captured["kwargs"]["env"], capture_output=True, text=True, timeout=180,
    )

    assert proc.returncode == 0, proc.stderr[:500]
    envelope = json.loads(proc.stdout)
    thinking = (envelope.get("usage", {}).get("output_tokens_details", {})
                .get("thinking_tokens", 0))

    # THE assertion. 34c41cd was reverted because this number went to 13,682 and ttft to 152.4s,
    # blowing the 160s timeout. Every probe before this one used a trivial prompt.
    assert thinking == 0, f"extended thinking is on: {thinking} tokens"
    assert envelope.get("result"), "the judge returned an empty result"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_claude_cli_live_smoke.py -q -m integration 2>&1 | tail -6
```

If Tasks 1–3 are landed, this test may pass on the first run — that is the expected outcome, not a
TDD failure. What must be verified here instead is that it **fails for the right reason** when the
fix is absent. Prove it by temporarily removing the key:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
sed -i '' 's/"alwaysThinkingEnabled": False,//' src/ormah/background/llm/claude_cli_adapter.py
.venv/bin/python -m pytest tests/test_background/test_claude_cli_live_smoke.py -q -m integration 2>&1 | tail -6
git checkout -- src/ormah/background/llm/claude_cli_adapter.py
```

Expected: `AssertionError: extended thinking is on: <N> tokens` with N in the thousands. If it
passes even without the key, this test does not detect the regression it exists for — stop and
report that, because it means the CLI's default changed and the fix's necessity must be re-measured.

**This step spends two real API calls.** That is the point of the task.

- [ ] **Step 3: Confirm the restore worked**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
git diff --stat
grep -n "alwaysThinkingEnabled" src/ormah/background/llm/claude_cli_adapter.py
```

Expected: `git diff --stat` shows no change to the adapter, and the grep finds the key present.

- [ ] **Step 4: Run the test for real and confirm it passes**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/test_background/test_claude_cli_live_smoke.py -q -m integration 2>&1 | tail -3
```

Expected: `1 passed`.

- [ ] **Step 5: Confirm the fast run still excludes it**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `1 failed, 2642 passed, 13 deselected`. The deselected count rises from 12 to 13 and the
passed count does not move — that is the proof the marker is doing its job and no one will pay for
a live call on every `make test`.

- [ ] **Step 6: Confirm ruff is clean**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
git add tests/test_background/test_claude_cli_live_smoke.py
git commit -m "test(llm): assert a real judge prompt produces no thinking tokens

Marked integration so it stays out of the fast run. It captures the adapter's
own argv rather than re-declaring it, so it cannot pass while the adapter ships
something else, and it was verified to fail with thousands of thinking tokens
when alwaysThinkingEnabled is removed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git show --stat HEAD | head -5
```

Expected: exactly 1 file in the commit stat.

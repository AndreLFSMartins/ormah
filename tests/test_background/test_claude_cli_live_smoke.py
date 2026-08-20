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

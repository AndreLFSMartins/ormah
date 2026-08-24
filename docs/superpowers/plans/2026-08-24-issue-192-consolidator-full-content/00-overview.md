# #192 — Consolidator must see full source content: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Each task file is self-contained — an implementer
> receives ONLY this overview plus their own task file.

**Goal:** The consolidation prompt carries the complete content of every source it summarizes;
a cluster that does not fit the prompt budget is split, never truncated — and the provider is
asked for an input window large enough to honor that budget.

**Architecture:** `_consolidate_cluster` drops the `content[:300]` cap. A new setting,
`consolidation_max_prompt_chars`, governs both a greedy cluster split and the Ollama input window
that the consolidation route pins on a dedicated adapter, so the truncation cannot reappear
inside the Ollama server.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode = auto`), pydantic-settings, ruff
(`line-length = 100`, `target-version = py311`).

**Spec:** `docs/superpowers/specs/2026-08-24-issue-192-consolidator-full-content-design.md`
(on `local-main`; not part of the PR — `docs/` is in the pre-push `PROTECTED` allowlist).

## ⚠️ The target tree is `upstream/main`, NOT `local-main`

Read this before anything else. The Beta (`Tools/ormah`, `local-main`) runs ~693 commits ahead,
and this plan was verified against the **upstream** file contents. In `upstream/main`:

- `content[:300]` is at `consolidator.py:216`.
- `run_consolidation(engine) -> None` — it returns nothing and there is no stats dict.
- There is **no** `_cluster_signature`, `consolidation_checked` table, `_record_signature`,
  `_CONSOLIDATE_RESPONSE_SCHEMA`, or `response_format=` on the LLM call.
- There is **no** `_mark_superseded` / `superseded_by` (that is #223, still open as PR #257).
- `llm_client.py` is 95 lines: no lock, no cancellation, no ingest adapter, no `_guarded_generate`.
- `get_adapter(settings)` takes **no** other parameters, and `OllamaAdapter` has **no** `num_ctx`.
- `ormah/ingest_capacity.py` and `estimated_tokens` **do not exist**.
- `tests/test_background/test_llm_client.py` **does not exist** — Task 5 creates it.

Anything you remember about these files from the Beta is not evidence. If a step's "replace
this" block does not match the file you have, STOP: you are on the wrong base.

## Global Constraints

- Line length 100, `target-version = py311`; `ruff check src/ tests/` must pass.
- `consolidation_max_prompt_chars` default **24000**, validator floor **4000**.
- Derived Ollama window: `int(consolidation_max_prompt_chars / 2.0) + llm_num_predict` =
  **16096** tokens with the defaults.
- The shared maintenance adapter (`_get_or_create_adapter`) MUST keep passing no `num_ctx`.
  `auto_linker`, `conflict_detector` and `duplicate_merger` share it and judge small pairs.
- `_apply_consolidation` is NOT modified.
- No source is ever truncated. A source that cannot fit is left `working`.

## Refinements decided while planning (deviations from the spec text)

1. **`route=` parameter instead of a new `consolidation_llm_generate`.** The spec proposed
   mirroring `ingest_llm_generate` — which does not exist upstream anyway. A keyword-only
   `route: str = "maintenance"` on `llm_generate` is smaller, keeps every existing
   `monkeypatch.setattr(...llm_generate...)` working, and is honest: the consolidation route has
   identical error semantics and differs only in which adapter it uses.
2. **No stats dict.** The spec named new stats keys, but `upstream/main`'s `run_consolidation`
   returns `None` and no caller reads a return value. Introducing one is an API change the issue
   did not ask for. The counts go into the existing INFO log line instead.
3. **A local `_CHARS_PER_TOKEN` constant** in `llm_client.py` rather than reusing
   `ingest_capacity.estimated_tokens`, which does not exist upstream. Same arithmetic, same
   16096 result.

## Known and deliberately out of scope: the Claude-in-the-loop path

`MemoryEngine.get_maintenance_batches` (Phase 1 of the `run_maintenance` two-call protocol) hands
consolidation clusters to the Claude maintenance agent after normalizing each node with
`content[:400]`, and `apply_maintenance_results` feeds the result to the **same**
`_apply_consolidation` — so that path demotes sources to archival from a 400-char view, exactly
the #192 damage on a different route.

This plan does **not** touch it. The fix there is different (there is no prompt budget of ours to
pack against — the limit is the agent's own context), and folding it in would double the PR's
surface. It is being tracked as its own issue. Do not "fix it while you are there".

One consequence to expect, not to fix: `get_maintenance_batches` lists **raw** clusters, so after
this PR a cluster it previews may become two consolidations. The preview is read-only and this
does not affect correctness.

## Setup — the clean island (do this before Task 1)

Per `FORK-WORKFLOW.md` Recipe A. `Tools/ormah` stays parked on `local-main` because the launchd
Beta serves from it.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git worktree add -b fix/192-consolidator-full-content ../ormah-wt-192 upstream/main
cd ../ormah-wt-192
python3 -m venv .venv
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
```

**Import gate — run before trusting ANY test number:**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH .venv/bin/python -c "import ormah; print(ormah.__file__)"
# the printed path MUST contain ormah-wt-192/ — if it does not, STOP.
```

**Every test command in every task file must be run in this form:**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest <args> > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt   # NEVER pipe pytest to tail — the exit code becomes tail's
```

`HOME` must be clean: `Settings` reads `~/.config/ormah/.env` first, and the Beta's
`ORMAH_LLM_PROVIDER=claude_cli` is rejected by `upstream/main`'s validator at conftest import.

**Test file prelude.** `tests/test_background/test_consolidator.py` upstream imports
`run_consolidation` inside test bodies. Tasks 1, 3 and 4 reference the module, so add once at the
top of that file, after the existing imports:

```python
from ormah.background import consolidator
```

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/ormah/background/consolidator.py` | full content in the prompt, INFO audit log, template constant, budget + split arithmetic, split wiring | 1, 3, 4 |
| `src/ormah/config.py` | `consolidation_max_prompt_chars` + validator | 2 |
| `src/ormah/background/llm/ollama_adapter.py` | accept and emit `num_ctx` | 5 |
| `src/ormah/background/llm/__init__.py` | thread `num_ctx` through `get_adapter` | 5 |
| `src/ormah/background/llm_client.py` | `route=`, dedicated consolidation adapter, chars→tokens | 5 |
| `tests/test_background/test_consolidator.py` | regression, split units, integration | 1, 2, 3, 4 |
| `tests/test_background/test_llm_client.py` (new) | adapter route + KV-cache non-regression | 5 |

## Tasks

| # | File | Deliverable |
|---|---|---|
| 1 | `01-remove-truncation.md` | The bug is fixed: full content reaches the prompt, plus the INFO audit log |
| 2 | `02-prompt-budget-setting.md` | `consolidation_max_prompt_chars` exists and is validated |
| 3 | `03-split-function.md` | Template as constant, `_prompt_overhead_chars()`, pure `_split_cluster_to_fit()` |
| 4 | `04-integrate-split.md` | `run_consolidation` splits; the cap counts sub-clusters |
| 5 | `05-adapter-route.md` | `num_ctx` exists and only the consolidation route pins it |

Task 1 comes first on purpose: it carries the load-bearing assumption (that a test can capture
the prompt the LLM receives). If that fails, it fails before anything is built on it.

## Done

`ruff check src/ tests/` clean and the full suite green from the island, with the import gate
proven and the output cited. Then `git log --oneline upstream/main..HEAD` must show ONLY your own
five commits before `git push fork fix/192-consolidator-full-content`.

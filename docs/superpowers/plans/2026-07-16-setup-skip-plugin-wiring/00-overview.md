# Setup: skip the Claude Code wiring the ormah plugin already provides — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `ormah setup` from re-wiring the hooks and MCP server that the ormah plugin already registers, so a human turn runs the whisper once instead of twice.

**Architecture:** One guard at the top of `_claude_code_wire()` — the single funnel all three offending entry points (`install.sh` plain, `install.sh --update`, desktop `run_setup_json`) pass through. The guard fires only for a **user-scoped plugin that is both enabled and installed**, and strips only what duplicates runtime execution: the hooks and the MCP server. `_claude_code_is_wired()` is corrected in the same PR because the strip would otherwise make the UI report a working install as "not wired".

**Tech Stack:** Python ≥3.11, pytest (`asyncio_mode = auto`), ruff (line-length 100, target py311).

**Spec:** `docs/superpowers/specs/2026-07-16-setup-skip-plugin-wiring-design.md`
**Issue:** [#145](https://github.com/r-spade/ormah/issues/145)
**Council review:** REV 1 rejected — this is REV 2. See `council-result.md`. The three corrections that shaped it are marked **[council]** below; do not revert them.

## Global Constraints

- **Branch:** `fix/setup-skip-plugin-wiring`, cut from `upstream/main` — **never** from `local-main` (`FORK-WORKFLOW.md`). Push to `fork`. PR base `r-spade:main`.
- **All code, comments, docstrings and commit messages in English.**
- Lint: ruff, line-length 100. Run `make lint` before the final commit.
- Only `src/ormah/setup.py` and `tests/test_setup.py` may be modified. No new files, no new dependencies.
- `docs/superpowers/` is gitignored in this repo — never `git add` the plan or the spec.
- Do not touch `--skip-client-setup`; it stays as an explicit override.
- Existing behaviour when the plugin is absent, disabled, **not installed**, or **not user-scoped** must be byte-for-byte unchanged.
- **[council] Reuse `_plugin_enabled_in_settings` (`setup.py:687`)** — do not write a second `enabledPlugins` parser.
- **[council] Never strip on an enabled flag alone.** Enabled and installed are two states in two files; require both.
- **[council] Strip only hooks + MCP.** Agents and slash commands are namespaced by the plugin (`ormah:maintenance` vs `ormah-maintenance`) — different names, no runtime duplication, still installed by setup.

## Task order and why

| # | Task | File | Rationale for the position |
| --- | --- | --- | --- |
| 0 | `_remove_mcp_from_json` → `_atomic_write` | `00-atomic-mcp-write.md` | **[council]** Task 4 makes this write a hot path; today it is a bare `write_text`. Land the crash-safety fix before the code that exercises it. |
| 1 | Fix the dead matcher branch in `_claude_code_is_wired` | `01-is-wired-dead-branch.md` | Independent of everything else; its test fails against current code today, proving the bug before any new concept is introduced. |
| 2 | Add `_claude_code_plugin_provides_hooks()` | `02-plugin-provides-hooks.md` | Pure detection, no callers yet. Tasks 3 and 4 both consume it. |
| 3 | Make `_claude_code_is_wired` plugin-aware | `03-is-wired-plugin-aware.md` | **Must land before Task 4.** Task 4 strips the MCP entry; if `is_wired` were still MCP-only at that commit, the tree would have a state where the UI lies about a working install. |
| 4 | The `_claude_code_wire` guard + strip | `04-wire-guard.md` | The actual fix. Depends on 2 and 3. |

## Interfaces introduced

- `_claude_code_plugin_provides_hooks() -> bool` (Task 2) — consumed by Tasks 3 and 4.

## Known limitation (deliberate, tested)

A **project-** or **local-scoped** plugin does not trigger the guard, so #145's duplication persists in that install. This is not an oversight: `configure_claude_hooks` writes to the **global** `~/.claude/settings.json`, which serves every project. Removing it because one project enabled the plugin would break the whisper everywhere else. Global-active ↔ global-wired is the only safe symmetry. Task 2 carries a test asserting the guard does **not** fire for a project-scoped plugin, so the behaviour is deliberate rather than accidental. A follow-up issue covers that case.

## Setup — before Task 0

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git fetch upstream
git checkout upstream/main -b fix/setup-skip-plugin-wiring
git status   # expect: on branch fix/setup-skip-plugin-wiring, clean tree
```

Confirm the branch is anchored on upstream's tip, not on the Beta:

```bash
git merge-base --is-ancestor upstream/main HEAD && echo "anchored on upstream/main OK"
git log --oneline -1 upstream/main
```

## Finishing — after Task 4

- [ ] **Full suite + lint** — **[council]** the whole suite, not just `test_setup.py`

```bash
python -m pytest tests/test_setup.py tests/test_setup_json.py -v
make test
make lint
```
Expected: all pass; ruff reports no findings. `tests/test_setup_json.py` matters specifically because `run_setup_json` is one of the three entry points that call `wire_fn()`.

- [ ] **Push and open the PR**

```bash
git push fork fix/setup-skip-plugin-wiring
```
Then `/council-pr` (base `r-spade:main`, head `fork:fix/setup-skip-plugin-wiring`). If council's push is blocked by the `origin-is-upstream` guard, the explicit `git push fork ...` above already satisfies it.

- [ ] **Run it in the Beta (Recipe B)**

```bash
git checkout local-main
git merge fix/setup-skip-plugin-wiring
```

- [ ] **Live verification — the number that proves the fix**

```bash
ormah setup --update
```
Then check the wiring is gone and the plugin's is the only one left:

```bash
python3 -c "
import json, os
s = json.load(open(os.path.expanduser('~/.claude/settings.json')))
print('ormah hooks in settings.json:', json.dumps(s.get('hooks'), indent=1))
c = json.load(open(os.path.expanduser('~/.claude.json')))
print('ormah MCP entry:', (c.get('mcpServers') or {}).get('ormah'))
"
```
Expected: no `ormah whisper inject|store` command under any event; `ormah MCP entry: None`. The `/ormah-maintenance` command and the `ormah-maintenance` agent must still exist — they are not duplicates.

Then start a **new** Claude Code session (hooks load at session start — an open session keeps the old config) and send one prompt. Count the rows:

```bash
python3 -c "
import sqlite3, os
p = os.path.expanduser('~/.local/share/ormah/memory/index.db')
c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
q = '''select count(*) n, substr(prompt_text,1,40)
       from retrieval_events
       where logged_at > datetime('now','-10 minutes')
       group by session_id, prompt_hash order by max(logged_at) desc limit 5'''
for n, t in c.execute(q): print(n, '|', (t or '').replace(chr(10),' '))
"
```
Expected: **1** per prompt. It is 2 today — that delta is the whole point of the change.

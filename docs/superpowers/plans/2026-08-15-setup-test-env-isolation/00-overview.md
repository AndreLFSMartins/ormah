# Setup Test Env Isolation — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each task lives in its own file; a task implementer gets this overview plus their one task file.

**Goal:** Make the 6 `test_setup.py` failures that only happen on a developer machine pass, by closing two test-isolation holes — without touching a single line of runtime code.

**Architecture:** Two independent changes under `tests/`. Task 2 adds an autouse fixture that mutates the `ormah.config.settings` singleton in place back to its unpolluted values for the duration of each test. Task 3 repoints three mocks at `ormah.setup._find_binary`, the seam those tests actually meant to close.

**Tech Stack:** pytest, pytest `monkeypatch`, pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-08-15-setup-test-env-isolation-design.md`

## Tasks

| File | Task | Deliverable |
|---|---|---|
| `01-reproduce-red.md` | Reproduce the red on this branch | 6 failing tests + a full-suite baseline of 12 IDs |
| `02-settings-singleton.md` | Reset the Settings singleton per test (group B) | 3 tests green + a regression test |
| `03-find-binary-seam.md` | Patch `_find_binary`, not `shutil.which` (group C) | 3 tests green |
| `04-verify-branch.md` | Verify and publish the branch | Suite compared by ID, lint, diff proof, push to `fork` |

Tasks 2 and 3 are independent — neither consumes anything from the other, and a reviewer can reject one while approving the other. Task 1 must run first; Task 4 last.

## Global Constraints

Every task's requirements implicitly include this section.

- **Branch:** `fix/setup-test-env-isolation`, worktree `/Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso`, cut from `upstream/main` `a28837b`. Never work in `Tools/ormah` — it is the running Beta, served by launchd.
- **The branch diff must contain only paths under `tests/`.** No runtime file may be modified.
- **Never run bare `python`/`pytest` in the worktree.** The ambient venv belongs to `Tools/ormah` and its editable install resolves `import ormah` to the Beta's code, so a green run there measures the wrong tree. Every command uses this prefix, verified to override the editable install:

  ```bash
  cd /Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso
  PY="/Users/andre/Documents/GitHub/Tools/ormah-wt-220/.venv/bin/python"
  export PYTHONPATH="$PWD/src"
  ```

  Sanity check before trusting any run: `$PY -c "import ormah;print(ormah.__file__)"` must print a path under `ormah-wt-setup-iso`.
- **An empty failure list is not success.** `tests/test_background/test_hippocampus.py` can SIGSEGV and abort the run, leaving no failures at all — which diffs as "fixed everything". Check for `Fatal Python error` and exit code 139 before believing a clean result.
- **Compare failure IDs, never counts.** `test_hippocampus::test_new_file_triggers_ingestion` is 50/50 flaky, so the legitimate final total is 5 or 6. A matching count can still hide a swapped failure.
- Commit messages in English. No `--no-verify`. Push to `fork`, never `upstream`.

## Root causes and why each fix is shaped that way

**Group B (3 tests, `TestRemoveFastembedCache`).** `setup.py:1819`, inside `_remove_fastembed_cache`, reads `ormah.config.settings` and compares `m.get("model") == _settings.embedding_model` at `:1834`. The test patches the model registry to return the code default `BAAI/bge-base-en-v1.5`, but the singleton carries `bge-m3` from the developer's `~/.config/ormah/.env`. The names never match, so the qdrant cache dir is never deleted — while the reranker dir *is*, because that key is absent from the `.env`. Pollution surface: 17 fields.

PR #128 does not reach this. Its fixture repoints `Settings.model_config["env_file"]`, which fixes a `Settings()` built *during* the test; the singleton was built at import of `ormah.config`, before any fixture ran.

**Group C (3 tests, `TestConfigureCodexMcp`).** The tests patch `ormah.setup.shutil.which` → `None` to mean "codex is not installed", but `configure_codex_mcp` (`setup.py:629`) calls `_find_binary`, which only *starts* at `shutil.which` (`:43`) and then scans mise shims, nvm, `~/.local/bin`, `/usr/local/bin`, `/opt/homebrew/bin`. The machine has `/opt/homebrew/bin/codex`. The scan is deliberate and documented (`:37-42`); the test picked the wrong seam.

## Non-goals

- **Group A (5 tests)** — global `.env` leaking into new `Settings()`. Already fixed by open PR #128 (`fix/106-config-test-isolation`, issue #106). Not duplicated here. Both branches add fixtures to `tests/conftest.py` and will conflict on merge; the conflict is additive and trivial.
- **Group D (1 test)** — `test_hippocampus` is a race between the hippocampus thread and `shutdown` closing the sqlite connection. Gets its own upstream issue.
- No production code changes, no dependency injection into `setup.py`, no unrelated refactoring.

# Spec — isolate `test_setup.py` from the developer's machine

**Date:** 2026-08-15 · **Branch:** `fix/setup-test-env-isolation` (cut from `upstream/main` `a28837b`)
**Worktree:** `/Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso`

## Problem

On a developer machine `python -m pytest tests/` reports **12 failures** that a clean CI does not
have. None of them is a product regression: every one is a test-isolation defect, where global
state on the machine reaches code under test that believed it was mocked.

The 12 split into four independent root causes. This spec covers **two of them (6 tests)**; the
other two are explicitly out of scope (see Non-goals).

## Evidence

Measured on 2026-08-15, worktree `ormah-wt-220` at `003eca4`, its own venv:

| Fact | How it was verified |
|---|---|
| 12 failed / 1855 passed | full suite, 430s |
| All 12 are pre-existing on `upstream/main` | 10 by `git diff upstream/main` == 0 lines on both test and module; 2 by running them directly against `a28837b` |
| 5 are fixed by the open PR #128 | applied that branch's `tests/conftest.py`, the 5 passed |
| 6 are NOT fixed by #128 | same run, the 6 still failed |
| 1 (`test_hippocampus`) is flaky, not deterministic | passes in isolation; ledger measures 3 PASS / 3 FAIL over 6 runs |

## Root causes in scope

### B — the `Settings` singleton outlives test isolation (3 tests)

`TestRemoveFastembedCache::{test_deletes_known_model_dirs,
test_removes_cache_dir_when_empty_after_cleanup, test_uses_default_fastembed_cache_dir}`

`setup.py:1819` (inside `_remove_fastembed_cache`) reads `ormah.config.settings` and compares
`m.get("model") == _settings.embedding_model` at `:1834`. The test patches
`TextEmbedding.list_supported_models` to return `BAAI/bge-base-en-v1.5` — the code default — but
the singleton carries `bge-m3`, read from the developer's `~/.config/ormah/.env`
(`ORMAH_EMBEDDING_MODEL`, confirmed present). The names never match, so the qdrant cache dir is
never added to the delete set. The reranker dir *is* deleted, because that key is absent from the
`.env` and the singleton keeps the default — which is why exactly one of the two dirs survives.

PR #128 does not reach this. Its fixture repoints `Settings.model_config["env_file"]` and strips
`ORMAH_*` from `os.environ`, which fixes a `Settings()` constructed *during* the test. The
singleton was constructed at import of `ormah.config`, before any fixture ran, and still holds the
leaked values.

**Pollution surface: 17 fields**, not 3 — `llm_provider`, `embedding_model`, `embedding_provider`,
`embedding_dim`, `llm_model`, `hippocampus_enabled`, `feedback_llm_judge_enabled`,
`claude_maintenance_enabled`, and 9 thresholds/intervals.

### C — `_find_binary` outflanks the mock (3 tests)

`TestConfigureCodexMcp::{test_writes_mcp_config_to_codex_toml, test_preserves_existing_toml_content,
test_replaces_existing_ormah_block}`

The tests patch `ormah.setup.shutil.which` to return `None`, intending "codex is not installed".
But `configure_codex_mcp` (`setup.py:629`) calls `_find_binary("codex")`, and `_find_binary`
(`setup.py:36`) only *starts* with `shutil.which` (`:43`); on a miss it scans absolute paths —
mise shims, nvm, `~/.local/bin`, `/usr/local/bin`, `/opt/homebrew/bin`. The developer machine has
`/opt/homebrew/bin/codex`, so `subprocess.run` is called and `assert_not_called` fails.

`_find_binary`'s scan is deliberate and documented (`:37-42`): GUI apps launched from the tray do
not inherit the shell PATH. The defect is the test's choice of seam, not the function.

## Design

Test-infrastructure only. **No runtime file is touched** — the branch diff must contain nothing
outside `tests/`.

### 1. `tests/conftest.py` — autouse fixture `_reset_settings_singleton`

- Once per session, compute the field set where the live singleton diverges from a `Settings`
  built with an empty `env_file` and no `ORMAH_*` in the environment.
- Per test, `monkeypatch.setattr(settings, field, clean_value)` for each such field. `monkeypatch`
  restores on teardown.
- **Mutate in place; never rebind `ormah.config.settings`.** Five modules — `setup.py:24`,
  `main.py:25`, `server_manager.py:21`, `adapters/mcp_adapter.py:18`, `adapters/cli_adapter.py:15`
  — bind the singleton at module import, so rebinding the module attribute would not reach them.
  Sixteen other call sites import it inside functions and would see a rebind; in-place mutation is
  the only form that covers both. The singleton is mutable (`frozen` unset, assignment verified).

This is the complement of PR #128, not a replacement: #128 protects freshly-constructed
`Settings()`, this protects the one built at import.

### 2. `tests/test_setup.py` — patch the real seam

The three `TestConfigureCodexMcp` tests patch `ormah.setup._find_binary` → `None` instead of
`ormah.setup.shutil.which`. That is the boundary the tests actually mean.

## Non-goals

- **Group A (5 tests)** — global `.env` leaking into new `Settings()`. Already fixed by the open
  PR #128 (`fix/106-config-test-isolation`, issue #106). Not duplicated here.
- **Group D (1 test)** — `test_hippocampus.py::test_new_file_triggers_ingestion` is a race between
  the hippocampus thread and `shutdown` closing the sqlite connection; the same defect produces
  the SIGSEGV that aborts the suite. Gets its own upstream issue; fixing it means touching runtime
  shutdown/lifecycle, a different kind of change from this branch.
- No production code changes, no dependency injection into `setup.py`, no unrelated refactoring.

## Testing

The 6 failing tests are the specification, and they must go green without their intent being
altered. Their red state was measured on `ormah-wt-220`; **it must be re-measured on this branch
before any fix is written**, since a different worktree is a different environment and an
unreproduced red is not a red.

One test is added:

- `test_settings_singleton_is_isolated_from_global_env` — asserts that during a test the singleton
  exposes the code defaults for a representative leaked field. Without it, deleting the fixture
  would break nothing visibly on a clean CI, and the regression would return silently on a
  developer machine.

## Verification

Run in the worktree with an interpreter that imports **that worktree's** `src/ormah` — the ambient
venv of `Tools/ormah` resolves to the running Beta's code and would measure the wrong tree.

1. Full suite: 12 failures → **5 or 6** — the 5 of group A, plus `test_hippocampus` only when its
   coin lands wrong. Compare failure **IDs** against the baseline, never counts: the flaky test
   makes the count non-deterministic, and a matching count can still hide a swapped failure.
2. `git diff upstream/main --stat` lists only paths under `tests/`.
3. `ruff check src/ tests/` clean.
4. An empty failure list is not success: check for `Fatal Python error` / exit 139 first — the
   hippocampus segfault aborts the run and leaves the list empty.

## Risks

- **A test fixture that configures one of the 17 fields may collide with the reset**, depending on
  fixture ordering. The full-suite run is what exposes this. If it appears, fall back to an opt-in
  fixture used only by the three tests, and report the reason — do not patch around the ordering.
- Both this branch and PR #128 add fixtures to `tests/conftest.py`, so they will conflict on merge.
  The conflict is additive and trivial; the branches are otherwise independent, verified by the
  6 tests still failing with #128's conftest applied.

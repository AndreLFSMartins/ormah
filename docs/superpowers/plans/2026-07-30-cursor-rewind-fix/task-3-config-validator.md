# Task 3: Server-startup guard — fail fast on ollama + Anthropic model id

**Files:**
- Modify: `src/ormah/config.py` (new module-level function `validate_llm_runtime_config`, placed near the validators for discoverability — NOT a pydantic validator)
- Modify: `src/ormah/main.py` (call the guard at server startup, before the server binds)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings` (`config.py:19`), fields `llm_provider` (`:55`, default `"none"`) and `llm_model` (`:56`, default `"claude-haiku-4-5-20251001"`).
- Produces: `validate_llm_runtime_config(settings) -> None` (raises `ValueError`) — callable by any future entry point that wants the same guard.

**Background:** `ORMAH_LLM_PROVIDER=ollama` without `ORMAH_LLM_MODEL` silently sends the Anthropic default model id to Ollama — every maintenance job (auto_linker, duplicate_merger, conflict_detector, consolidator, feedback judge) then gets a 404 per call, forever, with only a WARNING per call. This exact combination kept the entire maintenance pipeline dead (143× 404 on 2026-07-30 alone).

**Design decision (council C2, codex — supersedes the R3/C1 pydantic approach):** the check must NOT be a pydantic `model_validator`. `config.py` builds an eager global `Settings()` singleton at import, and `ormah setup` imports through it — a model validator would throw `ValidationError` for the very users carrying the legacy bad pair, **blocking their own repair path** (`ormah setup --update` runs under the installer's `set -e`, so upgrades would abort too). A SERVER-STARTUP guard gives the same fail-fast where it matters (the process that would otherwise 404 silently for weeks) while `ormah setup`, the CLI, and the installer keep working on a broken config. Side benefit: existing tests constructing `Settings(llm_provider="ollama")` stay valid — no test-suite churn.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`, matching its existing import style; import the new function)

```python
def test_validate_llm_runtime_config_rejects_ollama_with_anthropic_default():
    """provider=ollama with the (Anthropic) default llm_model must fail at SERVER
    startup, not 404 on every maintenance call at runtime."""
    settings = Settings(llm_provider="ollama")
    with pytest.raises(ValueError, match="llm_model"):
        validate_llm_runtime_config(settings)


def test_validate_llm_runtime_config_accepts_explicit_ollama_model():
    settings = Settings(llm_provider="ollama", llm_model="gemma3:12b-it-qat")
    validate_llm_runtime_config(settings)   # must not raise


def test_validate_llm_runtime_config_rejects_empty_ollama_model():
    """council C3: ORMAH_LLM_MODEL= (empty string) overrides the default and must be
    rejected too — Ollama 404s an empty model exactly like a claude-* id."""
    settings = Settings(llm_provider="ollama", llm_model="")
    with pytest.raises(ValueError, match="llm_model"):
        validate_llm_runtime_config(settings)


def test_validate_llm_runtime_config_keeps_claude_cli_default():
    """The Anthropic default is only wrong for ollama — claude_cli keeps working."""
    settings = Settings(llm_provider="claude_cli")
    validate_llm_runtime_config(settings)   # must not raise


def test_settings_construction_with_bad_pair_still_succeeds():
    """council C2: constructing Settings must NEVER raise for this pair — `ormah setup`
    imports the eager singleton and is the user's only repair path."""
    settings = Settings(llm_provider="ollama")   # inherits the Claude default
    assert settings.llm_model.startswith("claude-")
```

- [ ] **Step 2: Run them — the first FAILS (function missing), the others guard current behavior**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_config.py -k validate_llm_runtime_config -v`
Expected: ImportError/NameError on `validate_llm_runtime_config` (all new tests error — that is the RED state). `test_settings_construction_with_bad_pair_still_succeeds` must pass as soon as the import resolves; if it ever fails, the guard leaked into pydantic validation — stop and fix.

- [ ] **Step 3: Implement the guard.** In `src/ormah/config.py`, near the existing validators:

```python
def validate_llm_runtime_config(settings: "Settings") -> None:
    """Server-startup guard — deliberately NOT a pydantic validator (council C2): the
    eager global `settings` singleton is imported by `ormah setup`, and a model
    validator would crash the exact repair path a user with this legacy pair needs
    (the installer runs `ormah setup --update` under `set -e`). The server process is
    where the misconfiguration does silent damage (404 per maintenance call), so the
    server is where it fails loudly. Rejects BOTH failure shapes (council C3): an
    Anthropic model id (the field default leaking through) and an empty/whitespace
    model (ORMAH_LLM_MODEL= overrides the default with "", which Ollama also 404s).
    """
    if settings.llm_provider == "ollama":
        model = (settings.llm_model or "").strip()
        if not model or model.startswith("claude-"):
            raise ValueError(
                "llm_model is empty or looks like an Anthropic model id but "
                "llm_provider=ollama; set ORMAH_LLM_MODEL to an installed Ollama "
                "model (e.g. gemma3:12b-it-qat)"
            )
```

- [ ] **Step 4: Wire it into server startup — at a seam the PRODUCTION path actually executes.** Council C3 (cursor): the Beta starts via `ormah server start` → `uvicorn.run("ormah.main:app")`, and the launchd wrapper hardcodes `.venv/bin/ormah` — so `main.py`'s `if __name__ == "__main__":` block NEVER runs in production; a guard there would smoke green and protect nothing. Place the call where the APP IMPORT path runs it: at the start of the FastAPI `lifespan()` (or, if `main.py` has no lifespan, at module scope in `main.py` immediately after the app's `settings` is resolved — locate the seam with `graphify query "main.py app lifespan settings"` and confirm by reading the file):

```python
from ormah.config import validate_llm_runtime_config

validate_llm_runtime_config(settings)
```

The raise must abort the server process with the message on stderr/log — no catch-and-continue. It must fire for BOTH `ormah server start` and `python -m ormah.main`; `ormah.cli`'s other subcommands and `ormah setup` must NOT execute it (verify: `ormah setup --help` with the bad pair still works).

- [ ] **Step 5: Run the config module — all PASS**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/test_config.py -v`
Expected: all pass, including every pre-existing `Settings(llm_provider="ollama")` construction (untouched by design). (The live `~/.config/ormah/.env` already carries `ORMAH_LLM_MODEL=gemma3:12b-it-qat` — added 2026-07-30 — so this guard will NOT brick the Beta on next start.)

- [ ] **Step 6: Smoke the startup wiring — through the PRODUCTION entry point, isolated from the real config.** Council C3: `ORMAH_CONFIG_DIR` does not exist in `config.py` (it reads `~/.config/ormah/.env` and `./.env`), so isolation must come from a throwaway `HOME`; and the model var must be UNSET (not `=`) so the Anthropic default applies and triggers the guard:

Run (from the worktree root):

```bash
env -u ORMAH_LLM_MODEL HOME=$(mktemp -d) ORMAH_LLM_PROVIDER=ollama \
  PYTHONPATH=$PWD/src timeout 15 .venv/bin/ormah server start; echo "exit=$?"
```

Expected: fast exit, non-zero, with the `llm_model is empty or looks like an Anthropic model id` message — NOT a bound server. Repeat with `ORMAH_LLM_MODEL=""` (explicit empty) — same abort. Then the positive case: add `ORMAH_LLM_MODEL=gemma3:12b-it-qat` — the server must start (kill it with the timeout). If port 8787 is contended, pass the server's port flag/env for the smoke only.

- [ ] **Step 7: Commit**

```bash
git add tests/test_config.py src/ormah/config.py src/ormah/main.py
git commit -m "fix(config): fail server startup when llm_provider=ollama carries an Anthropic model id"
```

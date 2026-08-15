# Task 2: Reset the Settings singleton per test (group B — 3 tests)

Read `00-overview.md` first — its Global Constraints apply here.

Targets: `TestRemoveFastembedCache::{test_deletes_known_model_dirs, test_removes_cache_dir_when_empty_after_cleanup, test_uses_default_fastembed_cache_dir}`.

**Files:**
- Modify: `tests/conftest.py` — imports at top (lines 3-13); new fixtures inserted after line 71, where `prevent_tests_mutating_real_ormah_install` ends
- Create: `tests/test_settings_isolation.py`

**Interfaces:**
- Consumes: `/tmp/setup-iso-baseline-ids.txt` from Task 1.
- Produces: session fixture `_pristine_settings` → `Settings`, and autouse fixture `_reset_settings_singleton`. Task 3 consumes neither; the tasks are independent.

**Why in-place mutation and not rebinding:** `setup.py:24`, `main.py:25`, `server_manager.py:21`, `adapters/mcp_adapter.py:18` and `adapters/cli_adapter.py:15` bind the singleton at module import. Reassigning `ormah.config.settings` would leave all five pointing at the old object. Mutating the object reaches every holder, including the 16 call sites that import it inside functions.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_isolation.py`:

```python
"""The Settings singleton must not carry the developer's global config into tests."""

from __future__ import annotations

from ormah.config import Settings, settings


def test_settings_singleton_matches_pristine_defaults(_pristine_settings):
    diverged = sorted(
        name
        for name in Settings.model_fields
        if getattr(settings, name) != getattr(_pristine_settings, name)
    )
    assert diverged == [], (
        f"the global ~/.config/ormah/.env leaked into the singleton: {diverged}"
    )
```

- [ ] **Step 2: Run it and watch it fail**

```bash
$PY -m pytest tests/test_settings_isolation.py -p no:randomly
```

Expected: FAIL with `fixture '_pristine_settings' not found` — Step 3 has not run yet.

- [ ] **Step 3: Add both fixtures to `tests/conftest.py`**

Change the import block at the top so `os` is available:

```python
from __future__ import annotations

import os
import shutil
from pathlib import Path
```

Then insert after line 71, the closing line of `prevent_tests_mutating_real_ormah_install`:

```python
@pytest.fixture(scope="session")
def _pristine_settings(tmp_path_factory):
    """A Settings built as a clean machine would build it — no global .env, no ORMAH_* vars."""
    empty_env = tmp_path_factory.mktemp("pristine_settings_env") / "empty.env"
    empty_env.write_text("")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(Settings.model_config, "env_file", str(empty_env))
        for key in list(os.environ):
            if key.startswith("ORMAH_"):
                monkeypatch.delenv(key, raising=False)
        return Settings()


@pytest.fixture(autouse=True)
def _reset_settings_singleton(monkeypatch, _pristine_settings):
    """Point the module-level ``settings`` singleton back at unpolluted values.

    The sibling fixture from #128 protects a ``Settings()`` built during a
    test.  This protects the instance built at import of ``ormah.config``,
    which no fixture can retroactively construct differently.

    Mutates in place rather than rebinding ``ormah.config.settings``: five
    modules bind the singleton at import time and would never see a rebind.
    """
    from ormah.config import settings as singleton

    for name in Settings.model_fields:
        clean = getattr(_pristine_settings, name)
        if getattr(singleton, name) != clean:
            monkeypatch.setattr(singleton, name, clean)
```

- [ ] **Step 4: Run the new test and the 3 targets**

```bash
$PY -m pytest tests/test_settings_isolation.py tests/test_setup.py::TestRemoveFastembedCache -p no:randomly
```

Expected: `6 passed` — the new test plus the 5 in `TestRemoveFastembedCache`, of which 3 are the targets and 2 already passed.

- [ ] **Step 5: Prove the fixture is load-bearing**

Rename `_reset_settings_singleton` to `_reset_settings_singleton_DISABLED` — an autouse fixture only applies under its own name — then:

```bash
$PY -m pytest tests/test_settings_isolation.py tests/test_setup.py::TestRemoveFastembedCache -p no:randomly
```

Expected: `4 failed, 2 passed` — the new test plus the 3 targets go red again. Rename it back and re-run Step 4 to confirm `6 passed`.

A fixture whose removal breaks nothing proves nothing: without this check, a future cleanup could delete it and only a developer machine would notice.

- [ ] **Step 6: Full suite, compared by ID**

```bash
$PY -m pytest tests/ -q > /tmp/setup-iso-task2.txt 2>&1; echo "exit=$?"
grep -c 'Fatal Python error' /tmp/setup-iso-task2.txt
grep '^FAILED' /tmp/setup-iso-task2.txt | cut -d' ' -f1 | sort > /tmp/setup-iso-task2-ids.txt
diff /tmp/setup-iso-baseline-ids.txt /tmp/setup-iso-task2-ids.txt
```

Expected: only `<` lines — the 3 `TestRemoveFastembedCache` IDs, optionally plus `test_hippocampus` if its coin landed differently this run.

**Any `>` line is a regression this task caused**: the reset collided with a fixture that legitimately configures one of the 17 fields. If that happens: stop, replace the autouse fixture with an opt-in one requested by name in the 3 tests (approach B3 in the spec), and report which test collided. Do not tune the reset to dodge the collision.

- [ ] **Step 7: Commit**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-setup-iso
git add tests/conftest.py tests/test_settings_isolation.py
git diff --cached --stat
git commit -m "test(config): reset the Settings singleton between tests

The singleton is built at import of ormah.config, before any fixture runs,
so it carries the developer's ~/.config/ormah/.env into every test that
reads it. _remove_fastembed_cache compares the mocked model registry against
settings.embedding_model and never matches, leaving a cache dir undeleted.

Mutates in place: five modules bind the singleton at import and would not
see a rebind.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Confirm `--stat` lists exactly 2 files, both under `tests/`.

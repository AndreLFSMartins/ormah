# Task 1: Config — reconcile interval + per-tick cap

**Files:**
- Modify: `src/ormah/config.py:79` (add two settings) and `:341` (add validators)
- Test: `tests/test_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (create the file with this content if it does not exist):

```python
import pytest

from ormah.config import Settings


def test_reconcile_interval_default_is_five():
    assert Settings().session_watcher_reconcile_interval_minutes == 5


def test_reconcile_interval_must_be_positive():
    with pytest.raises(ValueError):
        Settings(session_watcher_reconcile_interval_minutes=0)


def test_reconcile_cap_default_is_fifty():
    assert Settings().session_watcher_reconcile_max_per_tick == 50


def test_reconcile_cap_must_be_positive():
    with pytest.raises(ValueError):
        Settings(session_watcher_reconcile_max_per_tick=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError` / no validation error raised.

- [ ] **Step 3: Add the settings**

In `src/ormah/config.py`, after line 79 (`session_watcher_idle_threshold: float = 30.0`):

```python
    session_watcher_reconcile_interval_minutes: int = 5
    session_watcher_reconcile_max_per_tick: int = 50
```

- [ ] **Step 4: Add the validators**

In `src/ormah/config.py`, after the `_session_watcher_debounce_min` validator (ends ~line 341):

```python
    @field_validator("session_watcher_reconcile_interval_minutes")
    @classmethod
    def _session_watcher_reconcile_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"session_watcher_reconcile_interval_minutes must be >= 1, got {v}"
            )
        return v

    @field_validator("session_watcher_reconcile_max_per_tick")
    @classmethod
    def _session_watcher_reconcile_cap_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"session_watcher_reconcile_max_per_tick must be >= 1, got {v}"
            )
        return v
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add src/ormah/config.py tests/test_config.py
git commit -m "feat(session-watcher): add reconcile interval + per-tick cap settings"
```

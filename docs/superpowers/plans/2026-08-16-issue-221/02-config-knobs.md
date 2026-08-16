# Task 2: Config knobs

**Files:**
- Modify: `src/ormah/config.py:89-93` (field block) and `src/ormah/config.py:564-569` (validator)
- Create: `tests/test_config_fsrs.py`

**Interfaces:**
- Consumes: nothing.
- Produces, for Tasks 3 and 4 — four `Settings` fields:
  - `fsrs_growth_factor: float = 0.5`
  - `fsrs_growth_exponent: float = 0.5`
  - `fsrs_spacing_cap: float = 2.0`
  - `fsrs_reinforcement_cooldown_days: float = 1.0`
- Removes: `fsrs_stability_growth` (its only reader, `memory_engine.py:1947`, is rewritten in Task 3 — expect the engine to still reference it until then; nothing imports it at module load, so the suite stays runnable).

**Why remove instead of reuse:** `fsrs_stability_growth = 1.5` is a *base multiplier* (`S × 1.5 × …`). The new `g = 0.5` is an *additive* term (`S × (1 + g × …)`). Keeping the name would silently reinterpret any existing `ORMAH_FSRS_STABILITY_GROWTH` value. `Settings.model_config` sets `extra: "ignore"` (`config.py:20`), so an old `.env` still loads.

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_fsrs.py`:

```python
"""Validation coverage for the bounded-reinforcement knobs (#221)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ormah.config import Settings


def test_defaults_match_the_decided_policy(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir)
    assert settings.fsrs_growth_factor == 0.5
    assert settings.fsrs_growth_exponent == 0.5
    assert settings.fsrs_spacing_cap == 2.0
    assert settings.fsrs_reinforcement_cooldown_days == 1.0


@pytest.mark.parametrize("field", ["fsrs_growth_factor", "fsrs_growth_exponent"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_growth_parameters_must_be_positive(tmp_memory_dir, field, value):
    with pytest.raises(ValidationError):
        Settings(memory_dir=tmp_memory_dir, **{field: value})


def test_spacing_cap_below_one_is_rejected(tmp_memory_dir):
    """A cap under 1 would shrink stability on use instead of growing it."""
    with pytest.raises(ValidationError):
        Settings(memory_dir=tmp_memory_dir, fsrs_spacing_cap=0.5)


def test_spacing_cap_of_exactly_one_is_allowed(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir, fsrs_spacing_cap=1.0)
    assert settings.fsrs_spacing_cap == 1.0


def test_negative_cooldown_is_rejected(tmp_memory_dir):
    with pytest.raises(ValidationError):
        Settings(memory_dir=tmp_memory_dir, fsrs_reinforcement_cooldown_days=-1.0)


def test_zero_cooldown_is_allowed(tmp_memory_dir):
    """Zero disables the cooldown — a legitimate config, not an error."""
    settings = Settings(memory_dir=tmp_memory_dir, fsrs_reinforcement_cooldown_days=0.0)
    assert settings.fsrs_reinforcement_cooldown_days == 0.0


def test_the_removed_growth_knob_no_longer_exists(tmp_memory_dir):
    settings = Settings(memory_dir=tmp_memory_dir)
    assert not hasattr(settings, "fsrs_stability_growth")


def test_an_env_carrying_the_removed_knob_still_loads(tmp_memory_dir, monkeypatch):
    """extra="ignore" (config.py:20) keeps an old .env from breaking startup."""
    monkeypatch.setenv("ORMAH_FSRS_STABILITY_GROWTH", "1.5")
    settings = Settings(memory_dir=tmp_memory_dir)
    assert settings.fsrs_growth_factor == 0.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'fsrs_growth_factor'` on the first test; `test_the_removed_growth_knob_no_longer_exists` fails because the field is still there.

- [ ] **Step 3: Replace the field block**

In `src/ormah/config.py`, replace lines 89-93:

```python
    # FSRS spaced repetition decay
    fsrs_initial_stability: float = 1.0    # days; starting stability for new nodes
    fsrs_decay_threshold: float = 0.3      # R below this = decay candidate
    fsrs_stability_growth: float = 1.5     # base multiplier on access
    fsrs_max_stability: float = 365.0      # cap at 1 year
```

with:

```python
    # FSRS spaced repetition decay
    fsrs_initial_stability: float = 1.0    # days; starting stability for new nodes
    fsrs_decay_threshold: float = 0.3      # R below this = decay candidate
    fsrs_max_stability: float = 365.0      # cap at 1 year
    # Bounded reinforcement (#221/#191): S' = S * (1 + g * S^-w * spacing).
    # Initial policy values, not fitted — deliberately configurable.
    fsrs_growth_factor: float = 0.5        # g; size of one reinforcement step
    fsrs_growth_exponent: float = 0.5      # w; damps the step as stability rises
    fsrs_spacing_cap: float = 2.0          # ceiling on the R^-0.2 spacing factor
    fsrs_reinforcement_cooldown_days: float = 1.0  # min days between numeric updates
```

- [ ] **Step 4: Update the validators**

In `src/ormah/config.py`, replace the validator at lines 564-569:

```python
    @field_validator("fsrs_initial_stability", "fsrs_stability_growth")
    @classmethod
    def _fsrs_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"FSRS parameter must be > 0, got {v}")
        return v
```

with:

```python
    @field_validator("fsrs_initial_stability", "fsrs_growth_factor", "fsrs_growth_exponent")
    @classmethod
    def _fsrs_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"FSRS parameter must be > 0, got {v}")
        return v

    @field_validator("fsrs_spacing_cap")
    @classmethod
    def _fsrs_spacing_cap_min(cls, v: float) -> float:
        # Below 1 the spacing factor would shrink stability on use.
        if v < 1:
            raise ValueError(f"fsrs_spacing_cap must be >= 1, got {v}")
        return v

    @field_validator("fsrs_reinforcement_cooldown_days")
    @classmethod
    def _fsrs_cooldown_non_negative(cls, v: float) -> float:
        # 0 is valid: it disables the cooldown.
        if v < 0:
            raise ValueError(f"fsrs_reinforcement_cooldown_days must be >= 0, got {v}")
        return v
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`
Expected: 12 passed (the parametrized test expands to 4).

- [ ] **Step 6: Confirm nothing else read the removed knob**

Run: `grep -rn "fsrs_stability_growth" src/ tests/ eval/`
Expected: exactly one hit — `src/ormah/engine/memory_engine.py:1947`, which Task 3 rewrites. Any other hit is a missed call site: fix it before committing.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/config.py tests/test_config_fsrs.py
git add src/ormah/config.py tests/test_config_fsrs.py
git commit -m "config(lifecycle): bounded-reinforcement knobs replace fsrs_stability_growth (#221)"
```

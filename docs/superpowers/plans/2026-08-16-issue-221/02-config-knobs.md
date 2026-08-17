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
- Removes: **nothing.** This task is purely additive.

**Why the removal of `fsrs_stability_growth` moved to Task 3 (pre-flight, 2026-08-16; decision:
André).** An earlier draft removed the field here and left its only reader,
`memory_engine.py:1947`, untouched until Task 3. That reader lives inside `_touch_access`, which
every recall path calls (`memory_engine.py:646, 775, 811, 892, 938`), so the Task 2 commit would
raise `AttributeError` on any recall — **12 test files** exercise those paths. The old note said
"nothing imports it at module load, so the suite stays runnable": true, and beside the point.
Runnable is not green, and Task 2 Step 7 commits. Removing the field in the same commit that
rewrites its reader keeps every commit on this branch passing, which the Final Gate demands anyway.

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


# Every `v <= 0` / `v < 1` / `v < 0` comparison is False for NaN, so the plain
# bounds checks let it straight through — verified against the current code:
# Settings(fsrs_stability_growth=float("nan")) returns nan today.
LIFECYCLE_FLOATS = [
    "fsrs_initial_stability",
    "fsrs_max_stability",
    "fsrs_growth_factor",
    "fsrs_growth_exponent",
    "fsrs_spacing_cap",
    "fsrs_reinforcement_cooldown_days",
]


@pytest.mark.parametrize("field", LIFECYCLE_FLOATS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_lifecycle_values_are_rejected(tmp_memory_dir, field, value):
    with pytest.raises(ValidationError):
        Settings(memory_dir=tmp_memory_dir, **{field: value})


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_non_finite_values_from_the_environment_are_rejected(tmp_memory_dir, monkeypatch, raw):
    """BaseSettings parses these strings into floats, so the env path needs the same guard."""
    monkeypatch.setenv("ORMAH_FSRS_GROWTH_FACTOR", raw)
    with pytest.raises(ValidationError):
        Settings(memory_dir=tmp_memory_dir)


```

The two tests about `fsrs_stability_growth` being **gone**
(`test_the_removed_growth_knob_no_longer_exists` and
`test_an_env_carrying_the_removed_knob_still_loads`) belong to Task 3, which is where the field is
actually removed. Do not write them here — in this task the field still exists, so the first would
fail and the second would pass for the wrong reason (the env var would bind to the live field
rather than being ignored as an extra).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'fsrs_growth_factor'` on the first test, and the same for every other new field.

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
    fsrs_stability_growth: float = 1.5     # base multiplier on access; removed in Task 3
    fsrs_max_stability: float = 365.0      # cap at 1 year
    # Bounded reinforcement (#221/#191): S' = S * (1 + g * S^-w * spacing).
    # Initial policy values, not fitted — deliberately configurable.
    fsrs_growth_factor: float = 0.5        # g; size of one reinforcement step
    fsrs_growth_exponent: float = 0.5      # w; damps the step as stability rises
    fsrs_spacing_cap: float = 2.0          # ceiling on the R^-0.2 spacing factor
    fsrs_reinforcement_cooldown_days: float = 1.0  # min days between numeric updates
```

**`fsrs_stability_growth` stays for now, on purpose.** Its only reader is
`memory_engine.py:1947`, rewritten in Task 3; deleting the field before the reader breaks every
recall path. Task 3 removes the line above and the reader in one commit.

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
    @field_validator(
        "fsrs_initial_stability",
        "fsrs_max_stability",
        "fsrs_growth_factor",
        "fsrs_growth_exponent",
        "fsrs_spacing_cap",
        "fsrs_reinforcement_cooldown_days",
    )
    @classmethod
    def _fsrs_finite(cls, v: float) -> float:
        # The bounds checks below cannot do this: every `v <= 0` / `v < 1` /
        # `v < 0` comparison is False for NaN, so NaN passes all of them, and
        # infinity satisfies them outright. A NaN growth factor propagates NaN
        # into stability, which is then serialized into the Markdown frontmatter;
        # a NaN cooldown raises inside timedelta.
        if not math.isfinite(v):
            raise ValueError(f"FSRS parameter must be finite, got {v}")
        return v

    @field_validator(
        "fsrs_initial_stability",
        "fsrs_stability_growth",
        "fsrs_growth_factor",
        "fsrs_growth_exponent",
    )
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

Add `import math` to `config.py` if it is not already imported.

Declaration order is cosmetic here, not load-bearing — verified by running both orders against
pydantic: every validator for a field runs, and since the bounds checks never reject NaN, the
finite check catches it either way. `_fsrs_finite` goes first because it reads better, not
because correctness depends on it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_config_fsrs.py -v`

Expected: **30 passed.** The count is mostly parametrization, so check it against the breakdown
rather than trusting the total:

| Test | Cases |
|---|---|
| `test_defaults_match_the_decided_policy` | 1 |
| `test_growth_parameters_must_be_positive` | 4 (2 fields × 2 values) |
| `test_spacing_cap_below_one_is_rejected` | 1 |
| `test_spacing_cap_of_exactly_one_is_allowed` | 1 |
| `test_negative_cooldown_is_rejected` | 1 |
| `test_zero_cooldown_is_allowed` | 1 |
| `test_non_finite_lifecycle_values_are_rejected` | 18 (6 fields × 3 values) |
| `test_non_finite_values_from_the_environment_are_rejected` | 3 |

A different total means a case was dropped or added — find which row disagrees before changing
anything. (This number read "12 passed (the parametrized test expands to 4)" until the pre-flight
scan: it was written when the file had only the first parametrized test and was never updated when
the non-finite cases landed in an earlier fold.)

- [ ] **Step 6: Confirm the suite is still green**

The old Step 6 grepped for `fsrs_stability_growth` and expected the field to be gone. It is not
gone in this task any more — the removal moved to Task 3. Run the paths this task's field block
could have broken instead:

```bash
./.venv/bin/python -m pytest tests/test_config.py tests/test_engine/ -q
```

Expected: unchanged from before this task. This task only **adds** fields, so any new failure here
means the field block or a validator was edited beyond what Steps 3-4 specify.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/bin/python -m ruff check src/ormah/config.py tests/test_config_fsrs.py
git add src/ormah/config.py tests/test_config_fsrs.py
git commit -m "config(lifecycle): add the bounded-reinforcement knobs (#221)"
```

The message says **add**, not "replace `fsrs_stability_growth`": this commit does not remove
anything. Task 3 removes the old knob together with its reader, and its message says so.

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


def test_an_env_carrying_the_removed_knob_still_loads(tmp_memory_dir, monkeypatch):
    """extra="ignore" (config.py:20) keeps an old .env from breaking startup."""
    monkeypatch.setenv("ORMAH_FSRS_STABILITY_GROWTH", "1.5")
    settings = Settings(memory_dir=tmp_memory_dir)
    assert settings.fsrs_growth_factor == 0.5

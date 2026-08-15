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

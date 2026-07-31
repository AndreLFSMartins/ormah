"""Structured persistence for cloud protection settings."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from filelock import FileLock


CLOUD_BACKUP_ENABLED_KEY = "ORMAH_CLOUD_BACKUP_ENABLED"


def update_settings_env(
    values: Mapping[str, str],
    *,
    remove: Iterable[str] = (),
) -> None:
    """Serialize read-modify-writes to Ormah's shared environment file."""

    from ormah import setup

    setup.ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = setup.ENV_PATH.parent / ".env.lock"
    with FileLock(str(lock_path), timeout=30):
        os.chmod(lock_path, 0o600)
        env = setup._read_env_file()
        env.update(values)
        for key in remove:
            env.pop(key, None)
        setup._write_env_file(env)


def persist_settings_delta(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> None:
    """Persist only keys changed by a caller, serialized with every other writer."""

    updates = {
        key: value
        for key, value in after.items()
        if before.get(key) != value
    }
    removed = set(before) - set(after)
    update_settings_env(updates, remove=removed)


def set_cloud_backup_enabled(settings, enabled: bool) -> None:
    """Persist and apply cloud protection without dropping unrelated settings."""

    update_settings_env(
        {CLOUD_BACKUP_ENABLED_KEY: "true" if enabled else "false"},
    )
    settings.cloud_backup_enabled = enabled

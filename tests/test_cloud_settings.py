from __future__ import annotations

import os
import stat
import threading
import time

import pytest

from ormah import setup
from ormah.cloud.client import persist_account_credentials
from ormah.cloud.settings import persist_settings_delta, set_cloud_backup_enabled
from ormah.config import Settings


@pytest.fixture
def env_path(tmp_path, monkeypatch):
    path = tmp_path / "config" / ".env"
    monkeypatch.setattr(setup, "ENV_PATH", path)
    monkeypatch.setattr(setup, "ENV_DIR", path.parent)
    return path


def test_cloud_setting_preserves_unrelated_env_lines_and_updates_runtime(
    env_path, monkeypatch
):
    original = "# user setting\nMANUAL = spaced  # preserve\nORMAH_LLM_PROVIDER=none\n"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(original, encoding="utf-8")
    settings = Settings(cloud_backup_enabled=False)

    # filelock's UnixFileLock unlinks its lock file on release (verified: every
    # release, not version-specific), so the file cannot be inspected after
    # set_cloud_backup_enabled() returns. Spy on the chmod call instead, which
    # is where update_settings_env() actually asserts the lock file's mode.
    chmod_calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def spy_chmod(path, mode, *args, **kwargs):
        chmod_calls.append((str(path), mode))
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", spy_chmod)

    set_cloud_backup_enabled(settings, True)

    text = env_path.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert "ORMAH_CLOUD_BACKUP_ENABLED=true\n" in text
    assert settings.cloud_backup_enabled is True
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    lock_calls = [(p, m) for p, m in chmod_calls if p.endswith(".env.lock")]
    assert lock_calls == [(str(env_path.parent / ".env.lock"), 0o600)]


def test_cloud_setting_does_not_change_runtime_when_persistence_fails(
    env_path, monkeypatch
):
    settings = Settings(cloud_backup_enabled=False)
    monkeypatch.setattr(
        setup,
        "_write_env_file",
        lambda env: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        set_cloud_backup_enabled(settings, True)

    assert settings.cloud_backup_enabled is False


def test_account_and_protection_updates_are_serialized_without_lost_keys(
    env_path, monkeypatch
):
    env_path.parent.mkdir(parents=True)
    env_path.write_text("ORMAH_LLM_PROVIDER=none\n", encoding="utf-8")
    settings = Settings(cloud_backup_enabled=False)
    first_read_started = threading.Event()
    release_first_read = threading.Event()
    real_read = setup._read_env_file
    read_count = 0
    read_guard = threading.Lock()

    def delayed_read():
        nonlocal read_count
        with read_guard:
            read_count += 1
            current = read_count
        result = real_read()
        if current == 1:
            first_read_started.set()
            assert release_first_read.wait(2)
        return result

    monkeypatch.setattr(setup, "_read_env_file", delayed_read)
    protection = threading.Thread(
        target=set_cloud_backup_enabled,
        args=(settings, True),
    )
    account = threading.Thread(
        target=persist_account_credentials,
        args=("account-token", "person@example.com"),
    )

    protection.start()
    assert first_read_started.wait(1)
    account.start()
    time.sleep(0.05)
    assert account.is_alive()
    release_first_read.set()
    protection.join(2)
    account.join(2)

    assert not protection.is_alive()
    assert not account.is_alive()
    text = env_path.read_text(encoding="utf-8")
    assert "ORMAH_LLM_PROVIDER=none" in text
    assert "ORMAH_CLOUD_BACKUP_ENABLED=true" in text
    assert "ORMAH_ACCOUNT_TOKEN=account-token" in text
    assert "ORMAH_ACCOUNT_EMAIL=person@example.com" in text


def test_setup_delta_does_not_overwrite_a_concurrent_protection_setting(env_path):
    env_path.parent.mkdir(parents=True)
    env_path.write_text("ORMAH_LLM_PROVIDER=none\n", encoding="utf-8")
    stale_before = setup._read_env_file()
    desired = dict(stale_before)
    desired["ORMAH_LLM_PROVIDER"] = "ollama"

    settings = Settings(cloud_backup_enabled=False)
    set_cloud_backup_enabled(settings, True)
    persist_settings_delta(stale_before, desired)

    persisted = setup._read_env_file()
    assert persisted["ORMAH_LLM_PROVIDER"] == "ollama"
    assert persisted["ORMAH_CLOUD_BACKUP_ENABLED"] == "true"


def test_admin_backup_settings_use_the_shared_serialized_writer(monkeypatch, tmp_path):
    from ormah.api import routes_admin
    from ormah.cloud import settings as cloud_settings

    captured = {}
    monkeypatch.setattr(
        cloud_settings,
        "update_settings_env",
        lambda values: captured.update(values),
    )

    routes_admin._persist_backup_settings(tmp_path / "backups", 12)

    assert captured == {
        "ORMAH_BACKUP_DIR": str(tmp_path / "backups"),
        "ORMAH_BACKUP_RETENTION_COUNT": "12",
    }

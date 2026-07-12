"""CLI tests for the `ormah cloud` group."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ormah import cli
from ormah.cloud import keys as cloud_keys


@pytest.fixture
def cloud_paths(tmp_path, monkeypatch):
    """Point every cloud path at tmp and return the key path."""
    key_path = tmp_path / "config" / "cloud.key"
    kit_path = tmp_path / "config" / "ormah-recovery-kit.md"
    memory_dir = tmp_path / "memory"
    monkeypatch.setattr(cloud_keys, "KEY_PATH", key_path)
    monkeypatch.setattr(cloud_keys, "RECOVERY_KIT_PATH", kit_path)
    from ormah.config import settings

    monkeypatch.setattr(settings, "memory_dir", memory_dir)
    return key_path, kit_path, memory_dir


def _run(argv):
    with patch("sys.argv", ["ormah", *argv]):
        cli.main()


def test_cloud_init_json(cloud_paths, capsys):
    key_path, kit_path, memory_dir = cloud_paths

    _run(["cloud", "init", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["key_path"] == str(key_path)
    assert out["identity_count"] == 1
    assert out["imported"] is False
    assert out["recovery_kit"] == str(kit_path)
    assert key_path.is_file()
    assert kit_path.is_file()
    assert (memory_dir / ".store_id").is_file()
    assert out["store_id"] == (memory_dir / ".store_id").read_text().strip()


def test_cloud_init_refuses_second_run(cloud_paths, capsys):
    _run(["cloud", "init", "--json"])
    with pytest.raises(SystemExit):
        _run(["cloud", "init", "--json"])
    assert "rotate-key" in capsys.readouterr().err


def test_cloud_init_import_key(cloud_paths, tmp_path, capsys):
    key_path, kit_path, _ = cloud_paths
    _run(["cloud", "init", "--json"])
    original = cloud_keys.load_identity_strings(key_path)
    kit_copy = tmp_path / "kit-copy.md"
    kit_copy.write_text(kit_path.read_text())

    # fresh machine: move real key aside
    key_path.rename(key_path.with_suffix(".bak"))
    capsys.readouterr()

    _run(["cloud", "init", "--import-key", str(kit_copy), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["imported"] is True
    assert cloud_keys.load_identity_strings(key_path) == original


def test_cloud_rotate_key_json(cloud_paths, capsys):
    key_path, kit_path, _ = cloud_paths
    _run(["cloud", "init", "--json"])
    first = cloud_keys.load_identity_strings(key_path)
    capsys.readouterr()

    _run(["cloud", "rotate-key", "--yes", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["rotated"] is True
    assert out["identity_count"] == 2
    strings = cloud_keys.load_identity_strings(key_path)
    assert strings[1:] == first  # old identity retained
    assert strings[0] in kit_path.read_text()  # kit regenerated with new key


def test_cloud_rotate_key_requires_confirmation_non_tty(cloud_paths, capsys, monkeypatch):
    _run(["cloud", "init", "--json"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        _run(["cloud", "rotate-key"])
    assert "--yes" in capsys.readouterr().err


def test_cloud_rotate_key_without_init_fails(cloud_paths, capsys):
    with pytest.raises(SystemExit):
        _run(["cloud", "rotate-key", "--yes"])
    assert "cloud init" in capsys.readouterr().err


def test_cloud_kit_regenerates_after_loss(cloud_paths, capsys):
    """`ormah cloud kit` is the recovery path when init/rotate is interrupted
    between key commit and kit generation."""
    key_path, kit_path, memory_dir = cloud_paths
    _run(["cloud", "init", "--json"])
    kit_path.unlink()  # simulate the stranded state
    capsys.readouterr()

    _run(["cloud", "kit", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["recovery_kit"] == str(kit_path)
    assert out["identity_count"] == 1
    assert kit_path.is_file()
    current = cloud_keys.load_identity_strings(key_path)[0]
    assert current in kit_path.read_text()


def test_cloud_kit_without_key_fails(cloud_paths, capsys):
    with pytest.raises(SystemExit):
        _run(["cloud", "kit", "--json"])
    assert "cloud init" in capsys.readouterr().err

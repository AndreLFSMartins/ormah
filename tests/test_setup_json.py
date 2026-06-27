"""Tests for the non-interactive JSON setup path used by the Mac app."""

from __future__ import annotations

from unittest.mock import patch

import ormah.setup as setup


def test_detect_clients_none(tmp_path):
    with (
        patch("shutil.which", return_value=None),
        patch("ormah.setup.Path.home", return_value=tmp_path),
        patch("platform.system", return_value="Darwin"),
    ):
        d = setup.detect_clients()
    assert d == {"claude_code": False, "codex": False, "claude_desktop": False}


def test_detect_clients_claude_code(tmp_path):
    with (
        patch("shutil.which", side_effect=lambda n: "/bin/claude" if n == "claude" else None),
        patch("ormah.setup.Path.home", return_value=tmp_path),
        patch("platform.system", return_value="Linux"),
    ):
        d = setup.detect_clients()
    assert d["claude_code"] is True
    assert d["codex"] is False


def test_detect_clients_codex_via_dir(tmp_path):
    (tmp_path / ".codex").mkdir()
    with (
        patch("shutil.which", return_value=None),
        patch("ormah.setup.Path.home", return_value=tmp_path),
        patch("platform.system", return_value="Linux"),
    ):
        d = setup.detect_clients()
    assert d["codex"] is True


def test_run_setup_json_wires_detected(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(setup, "get_ormah_bin_path", lambda: "/bin/ormah")
    monkeypatch.setattr(
        setup, "detect_clients",
        lambda: {"claude_code": True, "codex": False, "claude_desktop": False},
    )
    for name in (
        "configure_claude_hooks", "configure_claude_code_mcp",
        "install_claude_md", "install_claude_agents", "install_claude_commands",
    ):
        monkeypatch.setattr(setup, name, lambda *a, _n=name: calls.append(_n))

    result = setup.run_setup_json()

    assert result["detected"] == ["claude_code"]
    assert result["wired"] == ["claude_code"]
    assert result["errors"] == {}
    assert "configure_claude_hooks" in calls


def test_run_setup_json_captures_errors(monkeypatch):
    monkeypatch.setattr(setup, "get_ormah_bin_path", lambda: "/bin/ormah")
    monkeypatch.setattr(
        setup, "detect_clients",
        lambda: {"claude_code": True, "codex": False, "claude_desktop": False},
    )

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(setup, "configure_claude_hooks", boom)
    # later steps shouldn't matter; error short-circuits this client
    for name in (
        "configure_claude_code_mcp", "install_claude_md",
        "install_claude_agents", "install_claude_commands",
    ):
        monkeypatch.setattr(setup, name, lambda *a: None)

    result = setup.run_setup_json()

    assert result["wired"] == []
    assert "claude_code" in result["errors"]
    assert "RuntimeError" in result["errors"]["claude_code"]

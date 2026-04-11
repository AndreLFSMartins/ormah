"""Tests for release packaging metadata and CLI fallbacks."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
import tomllib

from ormah.cli import _cmd_eval_whisper_run


class TestBuildMetadata:
    def test_wheel_packages_exclude_eval(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text())

        wheel_packages = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        assert wheel_packages == ["src/ormah"]

    def test_sdist_only_includes_release_paths(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text())

        included = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
        assert "eval" not in included
        assert "src/ormah" in included
        assert "ui" in included
        assert "install.sh" in included


class TestEvalCliFallback:
    def test_eval_command_exits_cleanly_when_harness_is_missing(self, monkeypatch, capsys):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "eval.whisper.cli":
                raise ModuleNotFoundError("No module named 'eval'", name="eval")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(SystemExit) as exc:
            _cmd_eval_whisper_run(object())

        assert exc.value.code == 1
        assert "not installed in the published Ormah runtime" in capsys.readouterr().out

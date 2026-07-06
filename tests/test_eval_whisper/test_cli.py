"""Tests for eval whisper CLI wiring."""
from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class TestMakeEngine:
    def test_make_engine_freezes_eval_settings_against_env(self, monkeypatch, tmp_path):
        import eval.whisper.cli as cli_module

        monkeypatch.setattr(cli_module, "_EVAL_DB_DIR", tmp_path / "eval_db")
        monkeypatch.setenv("ORMAH_SPACE_BOOST_GLOBAL", "1.25")
        monkeypatch.setenv("ORMAH_WHISPER_EXPLORATION_ENABLED", "false")
        monkeypatch.setenv("ORMAH_FTS_WEIGHT", "0.99")
        monkeypatch.setenv("ORMAH_WHISPER_OUT_ENABLED", "true")

        captured = {}

        class FakeEngine:
            def __init__(self, settings):
                captured["settings"] = settings

            def startup(self):
                captured["startup"] = True

        monkeypatch.setattr("ormah.engine.memory_engine.MemoryEngine", FakeEngine)

        cli_module._make_engine()

        settings = captured["settings"]
        assert captured["startup"] is True
        assert settings.memory_dir == tmp_path / "eval_db"
        assert settings.space_boost_global == 1.0
        assert settings.whisper_exploration_enabled is True
        assert settings.fts_weight == 0.4
        assert settings.whisper_out_enabled is False


class TestEvalWhisperCLI:
    def test_cmd_eval_whisper_run_filters_category_and_passes_flags(self, monkeypatch, capsys):
        from eval.whisper.cli import cmd_eval_whisper_run

        cases = [
            {
                "id": "case-1",
                "prompts": [
                    {"text": "tech", "category": "technical"},
                    {"text": "fact", "category": "factual"},
                ],
            }
        ]
        engine = MagicMock()
        fake_result = SimpleNamespace(aggregate={}, category_aggregates={})
        run_mock = MagicMock(return_value=fake_result)

        monkeypatch.setattr("eval.whisper.corpus.load_corpus", lambda path: cases)
        monkeypatch.setattr("eval.whisper.runner.run_whisper_eval", run_mock)
        monkeypatch.setattr("eval.whisper.report.format_report", lambda result, show_failures: "REPORT")
        monkeypatch.setattr("eval.whisper.cli._make_engine", lambda: engine)

        args = Namespace(
            corpus=None,
            category="technical",
            simulate_session=True,
            preserve_self=True,
            json=False,
            show_failures=True,
        )
        cmd_eval_whisper_run(args)

        out = capsys.readouterr().out
        assert "REPORT" in out
        filtered_cases = run_mock.call_args.args[0]
        assert len(filtered_cases) == 1
        assert [p["text"] for p in filtered_cases[0]["prompts"]] == ["tech"]
        assert run_mock.call_args.kwargs["simulate_session"] is True
        assert run_mock.call_args.kwargs["preserve_self"] is True
        engine.shutdown.assert_called_once()

    def test_cmd_eval_whisper_run_uses_default_corpus_path(self, monkeypatch):
        from eval.whisper.cli import _CORPUS_DIR, cmd_eval_whisper_run

        seen = {}
        engine = MagicMock()

        def fake_load_corpus(path):
            seen["path"] = path
            return [{"id": "c1", "memories": [], "prompts": []}]

        monkeypatch.setattr("eval.whisper.corpus.load_corpus", fake_load_corpus)
        monkeypatch.setattr(
            "eval.whisper.runner.run_whisper_eval",
            lambda *args, **kwargs: SimpleNamespace(aggregate={}, category_aggregates={}),
        )
        monkeypatch.setattr("eval.whisper.report.format_report", lambda *args, **kwargs: "")
        monkeypatch.setattr("eval.whisper.cli._make_engine", lambda: engine)

        args = Namespace(
            corpus=None,
            category=None,
            simulate_session=False,
            preserve_self=False,
            json=False,
            show_failures=False,
        )
        cmd_eval_whisper_run(args)

        assert seen["path"] == _CORPUS_DIR / "golden" / "golden.jsonl"

    def test_cmd_eval_whisper_run_json_output(self, monkeypatch, capsys):
        from eval.whisper.cli import cmd_eval_whisper_run

        engine = MagicMock()
        fake_result = SimpleNamespace(
            aggregate={"total_prompts": 1},
            category_aggregates={"factual": {"total_prompts": 1}},
        )
        monkeypatch.setattr(
            "eval.whisper.corpus.load_corpus",
            lambda path: [{"id": "c1", "memories": [], "prompts": []}],
        )
        monkeypatch.setattr("eval.whisper.runner.run_whisper_eval", lambda *args, **kwargs: fake_result)
        monkeypatch.setattr("eval.whisper.cli._make_engine", lambda: engine)

        args = Namespace(
            corpus=None,
            category=None,
            simulate_session=False,
            preserve_self=False,
            json=True,
            show_failures=False,
        )
        cmd_eval_whisper_run(args)

        payload = json.loads(capsys.readouterr().out)
        assert payload["aggregate"]["total_prompts"] == 1
        assert payload["category_aggregates"]["factual"]["total_prompts"] == 1
        engine.shutdown.assert_called_once()

    def test_cmd_eval_whisper_run_errors_on_unknown_category(self, monkeypatch, capsys):
        from eval.whisper.cli import cmd_eval_whisper_run

        monkeypatch.setattr(
            "eval.whisper.corpus.load_corpus",
            lambda path: [{"id": "x", "prompts": [{"text": "q", "category": "factual"}]}],
        )

        args = Namespace(
            corpus=None,
            category="technical",
            simulate_session=False,
            preserve_self=False,
            json=False,
            show_failures=False,
        )

        with pytest.raises(SystemExit, match="1"):
            cmd_eval_whisper_run(args)

        err = capsys.readouterr().err
        assert "No prompts found for category 'technical'" in err

    def test_cmd_eval_whisper_run_surfaces_corpus_errors(self, monkeypatch, capsys):
        from eval.whisper.cli import cmd_eval_whisper_run
        from eval.whisper.corpus import CorpusError

        monkeypatch.setattr(
            "eval.whisper.corpus.load_corpus",
            lambda path: (_ for _ in ()).throw(CorpusError("broken corpus")),
        )

        args = Namespace(
            corpus=None,
            category=None,
            simulate_session=False,
            preserve_self=False,
            json=False,
            show_failures=False,
        )

        with pytest.raises(SystemExit, match="1"):
            cmd_eval_whisper_run(args)

        err = capsys.readouterr().err
        assert "Error: broken corpus" in err

    def test_root_cli_parses_simulate_session_and_preserve_self(self, monkeypatch):
        import ormah.cli as root_cli

        captured = {}

        def fake_cmd(args):
            captured["simulate_session"] = args.simulate_session
            captured["preserve_self"] = args.preserve_self
            captured["json"] = args.json

        monkeypatch.setattr("eval.whisper.cli.cmd_eval_whisper_run", fake_cmd)
        monkeypatch.setattr(
            "sys.argv",
            [
                "ormah",
                "eval",
                "whisper",
                "run",
                "--simulate-session",
                "--preserve-self",
                "--json",
            ],
        )

        root_cli.main()

        assert captured == {
            "simulate_session": True,
            "preserve_self": True,
            "json": True,
        }

"""Tests for eval whisper CLI wiring."""
from __future__ import annotations


class TestEvalWhisperCLI:
    def test_cmd_eval_whisper_run_importable(self):
        from eval.whisper.cli import cmd_eval_whisper_run
        assert callable(cmd_eval_whisper_run)

    def test_cli_module_has_make_engine(self):
        import eval.whisper.cli as cli_module
        assert callable(cli_module._make_engine)

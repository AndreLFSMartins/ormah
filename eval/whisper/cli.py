"""CLI handler for `ormah eval whisper run`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).parent
_CORPUS_DIR = _EVAL_DIR / "corpus"
_EVAL_DB_DIR = _EVAL_DIR / "eval_db"


def _make_engine():
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (_EVAL_DB_DIR / "nodes").mkdir(parents=True, exist_ok=True)
    # Disable maintenance signal so it doesn't pollute injection_fired for noise cases
    settings = Settings(memory_dir=_EVAL_DB_DIR, claude_maintenance_enabled=False)
    engine = MemoryEngine(settings)
    engine.startup()
    return engine


def cmd_eval_whisper_run(args):
    from eval.whisper.corpus import load_corpus, CorpusError
    from eval.whisper.runner import run_whisper_eval
    from eval.whisper.report import format_report

    corpus_path = _CORPUS_DIR / "golden" / "golden.jsonl"
    try:
        cases = load_corpus(corpus_path)
    except CorpusError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "category", None):
        filtered = [
            {**c, "prompts": [p for p in c["prompts"] if p.get("category") == args.category]}
            for c in cases
        ]
        cases = [c for c in filtered if c["prompts"]]
        if not cases:
            print(f"No prompts found for category '{args.category}'", file=sys.stderr)
            sys.exit(1)

    engine = _make_engine()
    try:
        result = run_whisper_eval(cases, engine)
    finally:
        engine.shutdown()

    if getattr(args, "json", False):
        print(json.dumps({
            "aggregate": result.aggregate,
            "category_aggregates": result.category_aggregates,
        }, indent=2))
    else:
        show_failures = getattr(args, "show_failures", False)
        print(format_report(result, show_failures=show_failures))

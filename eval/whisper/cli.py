"""CLI handler for `ormah eval whisper run`."""
from __future__ import annotations

import json
import sys
from datetime import datetime
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
    from eval.whisper.corpus import CorpusError, load_corpora
    from eval.whisper.runner import run_whisper_eval
    from eval.whisper.report import format_report

    corpus_paths: list[Path] = []
    corpus_arg = getattr(args, "corpus", None)
    if corpus_arg:
        corpus_path = Path(corpus_arg)
        if not corpus_path.is_absolute():
            corpus_path = _CORPUS_DIR / corpus_arg
        corpus_paths.append(corpus_path)
    else:
        corpus_paths.append(_CORPUS_DIR / "golden" / "golden.jsonl")

    if getattr(args, "include_mined", False):
        mined_arg = getattr(args, "mined_corpus", None)
        if mined_arg:
            mined_path = Path(mined_arg)
            if not mined_path.is_absolute():
                mined_path = _CORPUS_DIR / mined_arg
        else:
            mined_path = _CORPUS_DIR / "mined" / "mined.jsonl"
        corpus_paths.append(mined_path)

    try:
        cases = load_corpora(corpus_paths)
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
        result = run_whisper_eval(
            cases,
            engine,
            simulate_session=bool(getattr(args, "simulate_session", False)),
            preserve_self=True if getattr(args, "preserve_self", False) else None,
        )
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


def cmd_eval_whisper_mine_transcripts(args):
    from eval.whisper.mine import (
        discover_transcripts,
        format_mining_summary,
        mine_transcript_candidates,
    )
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    root = Path(getattr(args, "root", None) or Path.home() / ".claude" / "projects").expanduser()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_output = Path.home() / ".local" / "share" / "ormah" / "whisper-mined" / f"candidates-{timestamp}.jsonl"
    output_path = Path(getattr(args, "output", None) or default_output).expanduser()

    transcript_paths = discover_transcripts(root, max_sessions=getattr(args, "max_sessions", None))
    if not transcript_paths:
        print(f"No transcripts found under {root}", file=sys.stderr)
        sys.exit(1)

    engine = MemoryEngine(Settings())
    engine.startup()
    try:
        summary = mine_transcript_candidates(
            transcript_paths,
            engine,
            output_path,
            space=getattr(args, "space", None),
            max_candidates=getattr(args, "max_candidates", 100),
            recent_prompt_count=getattr(args, "recent_prompt_count", 2),
            min_user_turns=getattr(args, "min_user_turns", 5),
            include_whisper_text=bool(getattr(args, "include_whisper_text", False)),
        )
    finally:
        engine.shutdown()

    if getattr(args, "json", False):
        print(json.dumps({
            "transcripts_scanned": summary.transcripts_scanned,
            "prompts_seen": summary.prompts_seen,
            "candidates_written": summary.candidates_written,
            "category_counts": summary.category_counts,
            "output_path": str(summary.output_path),
        }, indent=2))
    else:
        print(format_mining_summary(summary))


def cmd_eval_whisper_promote_candidates(args):
    from eval.whisper.promote import promote_candidates
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    input_path = Path(args.input).expanduser()
    output_arg = getattr(args, "output", None)
    if output_arg:
        output_path = Path(output_arg).expanduser()
    else:
        output_path = _CORPUS_DIR / "mined" / "mined.jsonl"

    engine = MemoryEngine(Settings())
    engine.startup()
    try:
        summary = promote_candidates(
            input_path,
            output_path,
            engine,
            replace_output=bool(getattr(args, "replace_output", False)),
            limit=getattr(args, "limit", None),
        )
    finally:
        engine.shutdown()

    if getattr(args, "json", False):
        print(json.dumps({
            "candidates_read": summary.candidates_read,
            "cases_emitted": summary.cases_emitted,
            "skipped_candidates": summary.skipped_candidates,
            "duplicate_candidates": summary.duplicate_candidates,
            "output_path": str(summary.output_path),
            "manifest_path": str(summary.manifest_path),
        }, indent=2))
    else:
        print(
            "\n".join(
                [
                    "Whisper candidate promotion complete",
                    f"  candidates read:     {summary.candidates_read}",
                    f"  cases emitted:       {summary.cases_emitted}",
                    f"  skipped candidates:  {summary.skipped_candidates}",
                    f"  duplicate candidates:{summary.duplicate_candidates}",
                    f"  output:              {summary.output_path}",
                    f"  manifest:            {summary.manifest_path}",
                ]
            )
        )

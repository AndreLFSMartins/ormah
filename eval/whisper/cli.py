"""CLI handler for `ormah eval whisper run`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).parent
_CORPUS_DIR = _EVAL_DIR / "corpus"
_EVAL_DB_DIR = _EVAL_DIR / "eval_db"

_EVAL_SETTINGS_OVERRIDES = {
    # Search / hybrid retrieval used by whisper
    "embedding_provider": "local",
    "embedding_model": "BAAI/bge-base-en-v1.5",
    "embedding_dim": 768,
    "fts_weight": 0.4,
    "vector_weight": 0.6,
    "similarity_threshold": 0.4,
    "rrf_k": 60,
    "fts_only_dampening": 0.5,
    "min_result_score": 0.1,
    "rrf_min_spread_ratio": 0.05,
    "question_fts_weight_scale": 0.3,
    "question_vector_weight_scale": 1.5,
    "question_similarity_blend_weight": 0.85,
    "similarity_blend_weight": 0.5,
    "title_match_boost": 2.0,
    "length_penalty_threshold": 300,
    # Whisper pipeline
    "whisper_out_enabled": False,
    "claude_maintenance_enabled": False,
    "whisper_max_nodes": 6,
    "whisper_min_relevance_score": 0.45,
    "whisper_candidate_pool_multiplier": 5,
    "whisper_injected_content_max_chars": 600,
    "whisper_reranker_enabled": True,
    "whisper_reranker_model": "Xenova/ms-marco-MiniLM-L-6-v2",
    "whisper_reranker_min_score": 0.40,
    "whisper_reranker_blend_alpha": 0.6,
    "whisper_reranker_max_doc_chars": 512,
    "whisper_context_buffer_size": 5,
    "whisper_session_gap_minutes": 10,
    "whisper_intent_threshold": 0.65,
    "whisper_topic_shift_enabled": True,
    "whisper_topic_shift_threshold": 0.75,
    "whisper_injection_gate": 0.45,
    "whisper_no_overlap_ce_floor": 0.45,
    "whisper_no_overlap_cosine_floor": 0.70,
    "whisper_exploration_enabled": True,
    # Ranking adjustments used by whisper post-processing
    "space_boost_global": 1.0,
    "space_boost_other": 0.6,
    "affinity_similarity_threshold": 0.70,
    "affinity_half_life_days": 30.0,
    "affinity_max_boost": 0.15,
    "affinity_implicit_weight": 0.8,
}


def _make_engine():
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (_EVAL_DB_DIR / "nodes").mkdir(parents=True, exist_ok=True)
    settings = Settings(memory_dir=_EVAL_DB_DIR, **_EVAL_SETTINGS_OVERRIDES)
    engine = MemoryEngine(settings)
    engine.startup()
    return engine


def cmd_eval_whisper_run(args):
    from eval.whisper.corpus import CorpusError, load_corpus
    from eval.whisper.runner import run_whisper_eval
    from eval.whisper.report import format_report

    corpus_arg = getattr(args, "corpus", None)
    if corpus_arg:
        corpus_path = Path(corpus_arg)
        if not corpus_path.is_absolute():
            corpus_path = _CORPUS_DIR / corpus_arg
    else:
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

    fail_below = getattr(args, "fail_below", None)
    if fail_below:
        sys.exit(_check_fail_below(result.aggregate, fail_below))


def cmd_eval_whisper_mine(args):
    from eval.whisper.miner import mine

    db = Path(getattr(args, "db", None) or
              Path.home() / ".local" / "share" / "ormah" / "memory" / "index.db")
    if not db.exists():
        print(f"Error: live DB not found at {db}", file=sys.stderr)
        sys.exit(1)
    out = Path(args.out) if getattr(args, "out", None) else None

    # Use the engine's intent classifier so stratified sampling can
    # oversample the weak slices (preference/identity) properly.
    engine = _make_engine()
    try:
        classifier = engine.context_builder._get_classifier()

        def classify(prompt: str) -> str:
            if classifier is None:
                return "general"
            cats = classifier.classify(prompt).categories
            return cats[0] if cats else "general"

        mined_path, review_path = mine(
            db, limit=int(getattr(args, "limit", 80)), out_path=out, classify=classify,
        )
    finally:
        engine.shutdown()
    n = sum(1 for line in mined_path.read_text().splitlines() if line.strip())
    print(f"Mined {n} provisional cases -> {mined_path}")
    print(f"Review file -> {review_path}")
    print("Labels do NOT bind until reviewed: edit mined.jsonl where drafts are wrong, "
          "then run 'ormah eval whisper import-labels'.")


def cmd_eval_whisper_import_labels(args):
    from eval.whisper.miner import import_labels

    try:
        n = import_labels(Path(args.mined) if getattr(args, "mined", None) else None)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Confirmed {n} mined cases (provisional flags cleared).")


def _check_fail_below(aggregate: dict, spec: str) -> int:
    """Parse 'f1=0.65,suppression=0.90' and check thresholds. Returns 1 if any fails.

    Metric aliases: recall→injection_recall, precision→injection_precision,
    top2→top2_recall, suppression→suppression_accuracy. fp_rate is a
    below-is-better metric and is checked as an upper bound.
    """
    key_map = {
        "recall": "injection_recall",
        "precision": "injection_precision",
        "f1": "f1",
        "top2": "top2_recall",
        "suppression": "suppression_accuracy",
        "fp_rate": "false_positive_rate",
    }
    failed = False
    for part in spec.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        metric_raw, threshold_str = part.split("=", 1)
        key = key_map.get(metric_raw.strip().lower(), metric_raw.strip().lower())
        val = aggregate.get(key)
        threshold = float(threshold_str)
        if key == "false_positive_rate":
            bad = val is None or val > threshold
            op = ">"
        else:
            bad = val is None or val < threshold
            op = "<"
        if bad:
            val_str = f"{val:.3f}" if val is not None else "N/A"
            print(f"FAIL: {metric_raw}={val_str} {op} {threshold}", file=sys.stderr)
            failed = True
    return 1 if failed else 0

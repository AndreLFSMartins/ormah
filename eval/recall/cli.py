"""CLI handlers for `ormah eval recall` commands."""

from __future__ import annotations

import sys
from pathlib import Path

from eval.settings import RETRIEVAL_EVAL_SETTINGS_OVERRIDES

_EVAL_DIR = Path(__file__).parent
_CORPUS_DIR = _EVAL_DIR / "corpus"
_RESULTS_DIR = _EVAL_DIR / "results"
_EVAL_DB_DIR = _EVAL_DIR / "eval_db"


def _make_engine():
    """Create a MemoryEngine pointing at the isolated recall eval DB.

    Settings are pinned to production defaults (eval/settings.py) so the
    baseline is comparable across machines regardless of local ORMAH_* env.
    """
    from ormah.config import Settings
    from ormah.engine.memory_engine import MemoryEngine

    (_EVAL_DB_DIR / "nodes").mkdir(parents=True, exist_ok=True)
    settings = Settings(memory_dir=_EVAL_DB_DIR, **RETRIEVAL_EVAL_SETTINGS_OVERRIDES)
    engine = MemoryEngine(settings)
    engine.startup()
    return engine


def cmd_eval_recall_run(args):
    from eval.recall.corpus import load_corpus, CorpusError
    from eval.recall.runner import run_eval
    from eval.recall.report import format_report, write_results, load_previous_run

    corpus_label = args.corpus
    k = args.k

    files = _corpus_files_for_label(corpus_label)
    cases = []
    for f in files:
        try:
            cases.extend(load_corpus(f))
        except CorpusError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not cases:
        # A gate that evaluated zero cases must not report a pass — with
        # local-only corpora, a fresh checkout would otherwise green-light.
        print(f"Error: no cases found in corpus '{corpus_label}' — refusing to pass on zero cases", file=sys.stderr)
        sys.exit(1)

    engine = _make_engine()
    try:
        result = run_eval(cases, engine, k=k)
    finally:
        engine.shutdown()

    previous = load_previous_run(_RESULTS_DIR, corpus_label=corpus_label, k=k)
    prev_agg = previous["aggregate"] if previous else None
    report = format_report(result.aggregate, result.case_results, k=k, corpus_label=corpus_label, previous=prev_agg)
    print(report)
    write_results(result.aggregate, result.case_results, results_dir=_RESULTS_DIR, corpus_label=corpus_label, k=k)

    exit_code = 0
    if args.fail_below:
        exit_code = max(exit_code, _check_fail_below(result.aggregate, args.fail_below))
    if args.fail_on_regression and prev_agg:
        exit_code = max(exit_code, _check_regression(result.aggregate, prev_agg, args.fail_on_regression))

    sys.exit(exit_code)


def cmd_eval_recall_export_for_labeling(args):
    from eval.recall.judge import export_for_labeling

    pending = export_for_labeling(_CORPUS_DIR, write=True)
    print(f"Exported {len(pending)} unlabeled pairs to {_CORPUS_DIR / 'pending_labels.jsonl'}")


def cmd_eval_recall_import_labels(args):
    from eval.recall.judge import import_labels

    labels_file = _CORPUS_DIR / "labels.jsonl"
    if not labels_file.exists():
        print(f"Error: {labels_file} not found. Run export-for-labeling first.", file=sys.stderr)
        sys.exit(1)
    n = import_labels(_CORPUS_DIR, labels_file)
    print(f"Applied {n} labels to corpus files.")


def _corpus_files_for_label(label: str) -> list[Path]:
    if label == "golden":
        return list((_CORPUS_DIR / "golden").glob("*.jsonl"))
    if label == "synthetic":
        return list((_CORPUS_DIR / "synthetic").glob("*.jsonl")) if (_CORPUS_DIR / "synthetic").exists() else []
    # "all" = every runnable corpus
    files = list((_CORPUS_DIR / "golden").glob("*.jsonl"))
    if (_CORPUS_DIR / "synthetic").exists():
        files += list((_CORPUS_DIR / "synthetic").glob("*.jsonl"))
    return files


def _check_fail_below(aggregate: dict, spec: str) -> int:
    """Parse 'recall@8=0.70,precision@8=0.60' and check thresholds. Returns 1 if any fails."""
    failed = False
    for part in spec.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        metric_raw, threshold_str = part.split("=", 1)
        metric_key = metric_raw.split("@")[0].replace("-", "_").lower()
        key_map = {
            "recall": "recall", "precision": "precision", "f1": "f1",
            "mrr": "mrr", "injection_rate": "injection_rate",
            "false_negative_rate": "false_negative_rate",
            "fnr": "false_negative_rate",
            "false_positive_rate": "false_positive_rate",
            "fp_rate": "false_positive_rate",
        }
        key = key_map.get(metric_key, metric_key)
        val = aggregate.get(key)
        threshold = float(threshold_str)
        # Rates where lower is better are checked as upper bounds.
        if key in ("false_negative_rate", "false_positive_rate"):
            bad, op = (val is None or val > threshold), ">"
        else:
            bad, op = (val is None or val < threshold), "<"
        if bad:
            val_str = f"{val:.3f}" if val is not None else "N/A"
            print(f"FAIL: {metric_raw}={val_str} {op} {threshold}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def _check_regression(current: dict, previous: dict, spec: str) -> int:
    """Parse 'delta=0.05' and fail if any metric worsens by more than delta.

    Quality metrics (higher is better) regress when they drop; rate metrics
    (false_negative_rate, false_positive_rate — lower is better) regress when
    they rise. Returns 1 if any regression.
    """
    delta = float(spec.split("=", 1)[1]) if "=" in spec else 0.05
    failed = False
    higher_better = ("recall", "precision", "f1", "mrr")
    lower_better = ("false_negative_rate", "false_positive_rate")
    for key in higher_better + lower_better:
        cur = current.get(key)
        prev = previous.get(key)
        if cur is None or prev is None:
            continue
        worsened = (prev - cur) if key in higher_better else (cur - prev)
        if worsened > delta:
            direction = "dropped" if key in higher_better else "rose"
            print(
                f"REGRESSION: {key} {direction} {prev:.3f} -> {cur:.3f} "
                f"(delta={worsened:.3f} > {delta})",
                file=sys.stderr,
            )
            failed = True
    return 1 if failed else 0

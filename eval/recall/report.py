"""Format recall eval reports and write results files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_NOISE_THRESHOLD = 0.01
_BAR_WIDTH = 10


def _bar(value: float | None) -> str:
    if value is None:
        return "?" * _BAR_WIDTH
    filled = round(value * _BAR_WIDTH)
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _arrow(current: float | None, previous: float | None, higher_is_better: bool = True) -> str:
    if current is None or previous is None:
        return ""
    delta = current - previous
    if abs(delta) < _NOISE_THRESHOLD:
        return "  →"
    if (delta > 0) == higher_is_better:
        return f"  ▲ +{abs(delta):.2f}"
    return f"  ▼ -{abs(delta):.2f} vs last run  ← regression"


def format_report(
    aggregate: dict,
    case_results: list[dict],
    k: int,
    corpus_label: str,
    previous: dict | None,
) -> str:
    """Format the recall eval report as a human-readable string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    n = aggregate.get("case_count", 0)
    lines = [
        f"═══ Ormah Recall Eval Report ═══════════════",
        f"Corpus: {corpus_label} ({n} cases) | {now}",
        "",
    ]

    prev_agg = previous if previous else None

    metrics = [
        ("Recall", "recall", True),
        ("Precision", "precision", True),
        ("F1", "f1", True),
        ("MRR", "mrr", True),
        ("Injection rate", "injection_rate", True),
        ("False neg rate", "false_negative_rate", False),
    ]

    for label, key, higher_is_better in metrics:
        val = aggregate.get(key)
        prev_val = prev_agg.get(key) if prev_agg else None
        display_key = f"{label}@{k}" if key in ("recall", "precision", "f1") else label
        val_str = f"{val:.2f}" if val is not None else "N/A"
        bar = _bar(val)
        arrow = _arrow(val, prev_val, higher_is_better)
        lines.append(f"  {display_key:<18} {val_str}  {bar}{arrow}")

    worst = _worst_cases(case_results, n=5)
    if worst:
        lines.append("")
        lines.append("Worst cases:")
        for case_id, recall, prompt in worst:
            recall_str = f"{recall:.2f}" if recall is not None else "N/A"
            lines.append(f"  {case_id:<20} recall={recall_str}  \"{prompt[:60]}\"")

    return "\n".join(lines)


def _worst_cases(case_results: list[dict], n: int) -> list[tuple]:
    rows = []
    for cr in case_results:
        recalls = [
            pr["metrics"]["recall"]
            for pr in cr.get("prompt_results", [])
            if pr["metrics"]["recall"] is not None
        ]
        if not recalls:
            continue
        avg_recall = sum(recalls) / len(recalls)
        first_prompt = cr["prompt_results"][0]["prompt"] if cr["prompt_results"] else ""
        rows.append((cr["case_id"], avg_recall, first_prompt))
    rows.sort(key=lambda r: r[1])
    return rows[:n]


def write_results(
    aggregate: dict,
    case_results: list[dict],
    results_dir: Path,
    corpus_label: str,
    k: int,
) -> None:
    """Write latest.json and append to history.jsonl."""
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": ts,
        "corpus_label": corpus_label,
        "k": k,
        "aggregate": aggregate,
    }
    (results_dir / "latest.json").write_text(json.dumps(entry, indent=2))
    with open(results_dir / "history.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_previous_run(results_dir: Path, corpus_label: str = "golden") -> dict | None:
    """Return the last history entry for corpus_label, or None if no history exists."""
    history_file = results_dir / "history.jsonl"
    if not history_file.exists():
        return None
    last = None
    for line in history_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("corpus_label") == corpus_label:
            last = entry
    return last

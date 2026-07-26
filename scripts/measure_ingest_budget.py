"""Measure the realised raw span per slice under the content budget, to size the raw ceiling.

Replays the REAL parser over the live transcript corpus the way the watcher walks it, then
reports the raw-span distribution. Run after the content budget lands; its output sets
session_watcher_max_raw_bytes.

Import ONLY ormah.transcript.parser -- importing ormah.main writes into the production log.
"""
import argparse
from pathlib import Path

from ormah.transcript.parser import parse_transcript


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=60000, help="flush_chars to replay with")
    ap.add_argument("--files", type=int, default=200, help="largest N transcripts to sample")
    ap.add_argument("--watch-dir", type=Path, default=Path.home() / ".claude" / "projects")
    args = ap.parse_args()

    files = [p for p in args.watch_dir.rglob("*.jsonl") if ".bak-" not in str(p)]
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    sample = files[: args.files]

    raw_spans: list[int] = []
    clean_lens: list[int] = []
    slices = 0
    violations = 0

    for path in sample:
        offset = 0
        for _ in range(2000):
            try:
                r = parse_transcript(path, start_offset=offset, max_conversation_chars=args.budget)
            except Exception as e:  # noqa: BLE001
                print(f"parse error {path.name}: {e}")
                break
            if r.capped and r.safe_end_offset <= offset:
                violations += 1
            if r.safe_end_offset <= offset:
                break
            slices += 1
            raw_spans.append(r.safe_end_offset - offset)
            clean_lens.append(len(r.safe_conversation))
            offset = r.safe_end_offset

    def pct(xs: list[int], q: float) -> int:
        s = sorted(xs)
        return int(s[min(len(s) - 1, int(q * len(s)))])

    # The p99 below is a percentile over the WHOLE corpus's tail only while the sample still
    # contains that tail. A slice's raw span cannot exceed its own file's size, so every slice
    # larger than the smallest sampled file is guaranteed to be inside the sample. Print that
    # cutoff: it is the evidence for the population choice, and it is what goes stale. Once
    # enough files grow past it, --files N silently starts censoring the tail instead.
    cutoff = sample[-1].stat().st_size if sample else 0
    over = sum(1 for p in files if p.stat().st_size > cutoff)
    print(f"files sampled : {len(sample)} of {len(files)}")
    print(f"sample cutoff : {cutoff:,} B (smallest sampled file); {over} of {len(files)} files "
          f"exceed it -- no slice larger than this can exist outside the sample")
    print(f"slices        : {slices}")
    print(f"INVARIANT VIOLATIONS (capped without progress): {violations}")
    print()
    for label, xs in (("raw span", raw_spans), ("cleaned chars", clean_lens)):
        line = " ".join(f"p{int(q*100)}={pct(xs, q):,}" for q in (0.5, 0.9, 0.95, 0.99))
        print(f"{label:<14}: {line} max={max(xs):,}")


if __name__ == "__main__":
    main()

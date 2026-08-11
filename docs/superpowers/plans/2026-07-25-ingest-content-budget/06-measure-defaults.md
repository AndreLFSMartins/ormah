# Task 6: Replace the two provisional defaults with measured ones

**Files:**
- Create: `scripts/measure_ingest_budget.py`
- Modify: `src/ormah/config.py` (`session_watcher_max_raw_bytes`, `ingest_timeout_per_10k_chars`)

**Interfaces:**
- Consumes: everything from Tasks 1–5, working end to end.
- Produces: two measured numbers, and the evidence to paste into the PR description.

**This task is the gate.** Tasks 2 and 5 shipped `max_raw_bytes = None` and a guessed timeout rate.
Merging with those still in place ships a disabled safety budget and a made-up constant. Run this after
Task 5 and before `/council-pr`.

## Traps in this measurement (they already produced wrong answers once)

- **Import only `ormah.transcript.parser`. Never `ormah.main`** — importing it runs `setup_logging` and
  writes into the *production* log.
- Use `./.venv/bin/python`, not the system Python.
- Live state is `~/.claude/projects`. **Exclude `.bak-*` siblings** — a naive glob mixes them in and
  inflates counts (it produced 1814 where the truth was 475).
- **zsh does not word-split unquoted variables.** `cat $LOGS` silently yields nothing. List filenames
  literally or use `${=VAR}`.
- The health endpoint is `/admin/health`, never `/health` (the SPA catch-all returns HTML with 200).
- Do not run this while a large backlog drain is in flight — it competes for the same provider.

- [ ] **Step 1: Write the measurement script**

Create `scripts/measure_ingest_budget.py`:

```python
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

    print(f"files sampled : {len(sample)} of {len(files)}")
    print(f"slices        : {slices}")
    print(f"INVARIANT VIOLATIONS (capped without progress): {violations}")
    print()
    for label, xs in (("raw span", raw_spans), ("cleaned chars", clean_lens)):
        line = " ".join(f"p{int(q*100)}={pct(xs, q):,}" for q in (0.5, 0.9, 0.95, 0.99))
        print(f"{label:<14}: {line} max={max(xs):,}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and record the output**

```bash
./.venv/bin/python scripts/measure_ingest_budget.py --budget 60000 --files 200
```

Expected shape (design-time numbers on 40 files, for orientation only — yours will differ):
`raw span: p50=1,505,778 p90=5,700,556 p95=6,831,242 p99=17,120,301`.

**`INVARIANT VIOLATIONS` must be 0.** Anything else means a budget lost its progress guard — stop and
go back to Task 1/2, because `should_rewind` has become reachable from a cap.

Paste the full output into the PR description.

- [ ] **Step 3: Set the raw ceiling from the measured p99**

Round the measured p99 up to a clean number and set it in `src/ormah/config.py`:

```python
    session_watcher_max_raw_bytes: int | None = <measured p99, rounded up>
```

Record the reasoning in the same line's comment, e.g.:

```python
    session_watcher_max_raw_bytes: int | None = 20_000_000  # measured p99 17.1 MB (2026-07-25, 200 files)
```

Choose the p99, not the median: this budget exists to bound pathological cost, not to shape normal
slices. A ceiling that binds in normal operation is a **second** budget competing with the content
budget — which reintroduces the very axis error Amendment 3 fixes, one scale up.

- [ ] **Step 4: Time REAL extractions against the configured provider**

⛔ **Council R1, both peers:** do **not** time `ingest_llm_generate` on bare conversation with
`json_mode=False`. That omits `_INGEST_LLM_PROMPT`, the response schema and JSON mode, and it omits the
*generation* workload — which dominates extraction latency and scales with how many memories the Batch
yields. A rate derived from that sample systematically under-budgets the real call.

Measure through `_extract_memories_llm` itself, on **real** conversation slices, several times:

⛔ **Never point the measurement engine at the live store** (council, Codex). A bare `Settings()` keeps
the production `memory_dir`; `MemoryEngine(s)` then initialises the schema and vector table and
`startup()` can rebuild indexes, run migrations, rewrite Markdown and create the self node — **while the
Beta service owns that same store**. That turns a timing experiment into concurrent production
mutation. Copy only the provider-related settings into a throwaway `memory_dir`; read live transcripts
as *input* only.

```bash
./.venv/bin/python - <<'PY'
import statistics, tempfile, time
from pathlib import Path

from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.background.llm_client import ingest_provider_configured
from ormah.transcript.parser import parse_transcript

live = Settings()
assert ingest_provider_configured(live), "no ingest provider configured -- set one before measuring"

# Provider knobs only. memory_dir points at a throwaway directory so nothing in this script can
# touch the store the running Beta owns.
tmp = Path(tempfile.mkdtemp(prefix="ormah-measure-"))
(tmp / "nodes").mkdir()
s = Settings(
    memory_dir=tmp,
    ingest_llm_provider=live.ingest_llm_provider, ingest_llm_model=live.ingest_llm_model,
    llm_provider=live.llm_provider, llm_model=live.llm_model,
    session_watcher_flush_chars=live.session_watcher_flush_chars,
    ingest_chunk_chars=live.ingest_chunk_chars,
    ingest_max_content_chars=live.ingest_max_content_chars,
    claude_cli_timeout_seconds=live.claude_cli_timeout_seconds,
    llm_timeout_seconds=live.llm_timeout_seconds,
    backup_enabled=False, session_watcher_enabled=False,
)
assert s.memory_dir != live.memory_dir, "refusing to run against the live store"
print(f"measuring into a throwaway store: {tmp}")

# Real slices at the real budget, not synthetic filler: token density and extractable-memory
# density both differ from repeated text, and both drive latency.
watch = Path.home() / ".claude" / "projects"
files = [p for p in watch.rglob("*.jsonl") if ".bak-" not in str(p)]
files.sort(key=lambda p: p.stat().st_size, reverse=True)

payloads, offset_by = [], {}
for path in files[:40]:
    off = 0
    for _ in range(6):
        r = parse_transcript(path, start_offset=off, max_conversation_chars=s.session_watcher_flush_chars)
        if r.safe_end_offset <= off:
            break
        if len(r.safe_conversation) > s.session_watcher_flush_chars * 0.8:
            payloads.append(r.safe_conversation)
        off = r.safe_end_offset
    if len(payloads) >= 5:
        break
assert payloads, "no full-size slices found -- widen the sample"

engine = MemoryEngine(s)
engine.startup()
times, failures = [], 0
try:
    for i, payload in enumerate(payloads[:5], 1):
        t = time.time()
        out = engine._extract_memories_llm(payload)
        dt = time.time() - t
        ok = isinstance(out, list)
        failures += 0 if ok else 1
        times.append(dt)
        print(f"  run {i}: {len(payload):,} chars -> {dt:.1f}s  {'OK' if ok else f'FAILED ({out})'}")
finally:
    engine.shutdown()

print(f"\nruns={len(times)} failures={failures}")
print(f"median={statistics.median(times):.1f}s  max={max(times):.1f}s")
PY
```

**Gate:** `failures` must be 0. A `str` return is an error sentinel, not a result — if any run fails,
the provider cannot complete a full Batch and the merge is blocked until that is understood.

- [ ] **Step 5: Derive the timeout rate — non-negative by construction**

Use the **max** observed, not the median: the rate must cover the slow tail, not the typical case.

```
rate = max(0.0, (max_wall_clock - llm_timeout_seconds) / (flush_chars / 10000)) * 2.0
```

The `max(0.0, ...)` clamp is not cosmetic (council R1, Codex): a run that finishes **under**
`llm_timeout_seconds` makes the numerator negative. When the clamp fires, the derived term is
genuinely zero — the provider is fast enough that its own baseline already covers a full batch, and
`max(baseline, derived)` from Task 5 correctly falls back to the baseline. Record that outcome
explicitly rather than inventing a positive number.

⚠️ **This is why Task 5's validator accepts `>= 0`, not `> 0`** (council R2, Cursor caught the clash):
an earlier draft clamped to 0.0 here while rejecting 0 there, so a fast provider could not land its own
measured default. If you are implementing Task 5 and see `v <= 0`, that is the stale version — the
validator must accept 0.0 and treat it as "no size term".

```python
    ingest_timeout_per_10k_chars: float = <computed>   # max <X>s over <N> real extractions, 2x safety
```

Two sanity checks before committing the value:

- `max(baseline, llm_timeout_seconds + rate * 6)` must be comfortably below
  `ingest_timeout_max_seconds`, or the ceiling silently becomes the real timeout.
- The rate is measured on **one** provider on **one** machine. Say so in the comment. It is a default,
  not a claim about every provider — which is exactly why Task 5 makes it a floor over the adapter
  baseline rather than a replacement for it.

- [ ] **Step 6: Re-run the full suite**

```bash
./.venv/bin/python -m pytest tests/ -q
ruff check src/ tests/
```

Expected: PASS, clean.

- [ ] **Step 7: Commit**

```bash
git add src/ormah/config.py scripts/measure_ingest_budget.py
git commit -m "chore(ingest): set the raw-span budget and timeout rate from measurement

Replaces the two provisional defaults Tasks 2 and 5 shipped. The raw ceiling is the measured
p99 of the realised raw span under the 60000-char budget -- p99 deliberately, because a ceiling
that binds in normal operation is a second budget competing with the content budget, which is
the same axis error one scale up. The timeout rate comes from a timed full-size extraction
against the configured provider, with a 2x safety factor.

Measurement script committed so the numbers can be re-derived rather than trusted."
```

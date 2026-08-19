# Task 4: AFTER legs + calibrated quality gate

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Create (outside the repo): `~/.cache/ormah-eval-20260819/run_gate.py`
- Outputs (outside the repo): `~/.cache/ormah-eval-20260819/{after.json,ingest-after.json}`
- Nothing in the repo is created or modified by this task.

**Interfaces:**
- Consumes, unmodified, from Task 1: `pairs.jsonl`, `before.json`, `before2.json`, `ingest-before.json`, and `gate.py` (functions `load`, `check_keys`, `error_rate`, `edge_to_none`, `shuffled`).
- Produces: a pass/fail decision. Nothing downstream consumes its files; Task 5 only runs when this gate passes.

**Why this is not `eval.maintenance.cli report`.** That CLI applies the #87 K-batching thresholds: `agree_rate >= 0.90` plus a cap on `none→edge` flips. Neither is calibrated for this change. A single BEFORE map has no noise floor, so ordinary judge jitter is indistinguishable from a prompt effect; and `none→edge` is the *opposite* of the failure mode a poorer system prompt causes, which is `edge→none`. `report.py` stays untouched (it belongs to #87); this task imports its `agreement()` and adds four criteria around it.

- [ ] **Step 1: Confirm the code change is actually in place**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git log --oneline -2
grep -c "_SYSTEM_PROMPT" src/ormah/background/llm/claude_cli_adapter.py
```
Expected: the two commits from Tasks 2 and 3, and a count of 2 (the constant's definition and its argv use). A count of 0 means the AFTER leg would re-measure the old code — STOP.

- [ ] **Step 2: Run the AFTER leg — same pairs, same mode, same sequential conditions**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
rm -f ~/.cache/ormah-eval-20260819/after.json
nohup .venv/bin/python -m eval.maintenance.cli run \
  --pairs ~/.cache/ormah-eval-20260819/pairs.jsonl --mode single \
  --out ~/.cache/ormah-eval-20260819/after.json \
  > ~/.cache/ormah-eval-20260819/after.log 2>&1 &
echo $! > ~/.cache/ormah-eval-20260819/after.pid
while kill -0 "$(cat ~/.cache/ormah-eval-20260819/after.pid)" 2>/dev/null; do sleep 20; done; echo AFTER_DONE
```

- [ ] **Step 3: Run the ingest smoke on the changed code**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
rm -f ~/.cache/ormah-eval-20260819/ingest-after.json
.venv/bin/python ~/.cache/ormah-eval-20260819/ingest_smoke.py \
  ~/.cache/ormah-eval-20260819/ingest-after.json
```
Expected: 3 `normal` runs and 3 `injection` runs printed. This is the only leg that exercises the `--json-schema` argv the auto-linker never builds.

- [ ] **Step 4: Write the gate runner** — create `~/.cache/ormah-eval-20260819/run_gate.py`

```python
"""The quality gate for the fixed --system-prompt change.

Run from the repo root:  .venv/bin/python ~/.cache/ormah-eval-20260819/run_gate.py
Exit 0 = pass. Exit 1 = fail (do not restart the daemon). Exit 2 = the instrument
itself is invalid, which is NOT a licence to proceed.
"""
import json
import statistics
import sys
from pathlib import Path

CACHE = Path.home() / ".cache" / "ormah-eval-20260819"
# sys.path[0] is this script's directory, so `gate` imports; the repo-root `eval` package
# needs the cwd added explicitly. Run this from the repo root.
sys.path.insert(0, str(CACHE))
sys.path.insert(0, str(Path.cwd()))

from eval.maintenance.report import agreement  # noqa: E402
from gate import (  # noqa: E402
    EDGE_TO_NONE_MAX,
    ERROR_SLACK,
    MARGIN,
    NOISE_MIN,
    SEPARATION_MIN,
    best_shuffled_agreement,
    check_keys,
    edge_to_none,
    error_rate,
    load,
)


def ab_gate() -> int:
    before, before2, after = load("before.json"), load("before2.json"), load("after.json")

    if not check_keys("before.json", "before2.json", "after.json"):
        print("INVALID: the three legs do not cover the same mined pairs.")
        return 2

    # (1) Noise floor. agreement() between two runs of the SAME code is how much the judge
    # disagrees with itself. Without it, jitter and prompt effect are the same number.
    noise = agreement(before, before2)["agree_rate"]
    print(f"noise floor (before vs before2): {noise:.3f}")
    if noise < NOISE_MIN:
        print(f"INVALID: judge self-agreement {noise:.3f} < {NOISE_MIN}. No before/after "
              "comparison on this corpus can attribute a change to the prompt.")
        return 2
    floor = noise - MARGIN

    real = agreement(before, after)
    print(f"before vs after: agree_rate={real['agree_rate']:.3f} n={real['n']}")
    print(f"flips: {json.dumps(real['flips'])}")

    # (2) Symmetric cap. report.py caps none->edge (the K-batching risk). A weaker system
    # prompt fails the other way: it stops seeing real relationships.
    etn, n_edges = edge_to_none(before, after)
    print(f"edge->none: {etn:.3f} over {n_edges} edges — must be <= {EDGE_TO_NONE_MAX}")

    # (3) Unusable-verdict rate. If the new flag broke the CLI call outright, every verdict
    # becomes 'error'; this names that failure instead of letting it read as disagreement.
    err_before, err_after = error_rate(before), error_rate(after)
    print(f"error_rate: before={err_before:.3f} after={err_after:.3f}")

    # Real failures are decided FIRST. A corpus can be too weak to certify a pass while still
    # being strong enough to expose a regression — reporting that as INVALID would bury a real
    # finding under a complaint about the instrument.
    failures = []
    if real["agree_rate"] < floor:
        failures.append(f"agreement {real['agree_rate']:.3f} < floor {floor:.3f}")
    if n_edges > 0 and etn > EDGE_TO_NONE_MAX:
        failures.append(f"edge->none {etn:.3f} > {EDGE_TO_NONE_MAX}")
    if err_after > err_before + ERROR_SLACK:
        failures.append(f"error_rate rose {err_before:.3f} -> {err_after:.3f}")
    if failures:
        print("A/B GATE FAIL: " + "; ".join(failures))
        return 1

    # (4) Only now, with nothing failing, ask whether a PASS means anything. The negative
    # control is the same label distribution with pair correspondence destroyed: whatever it
    # scores is what pure chance achieves on this corpus. If the pass bar is not clearly above
    # that, "passing" carries no information — which is precisely the teatro this gate exists
    # to avoid. Checked on the best of several shuffles, so luck cannot rescue it.
    neg = best_shuffled_agreement(before, after, agreement)
    separation = floor - neg
    print(f"negative control (best of 5 shuffles): {neg:.3f} | "
          f"separation from bar: {separation:.3f} — must be >= {SEPARATION_MIN}")
    if separation < SEPARATION_MIN:
        print(f"INVALID: chance alone reaches {neg:.3f} against a {floor:.3f} bar, so nothing "
              "failing does not mean the change is safe. Mine a corpus with a less degenerate "
              "label distribution (more non-'none' verdicts) and re-run.")
        return 2
    if n_edges == 0:
        print("INVALID: BEFORE found no edges at all, so the edge->none cap protected nothing.")
        return 2
    if n_edges < 10:
        print(f"WARNING: only {n_edges} edges in BEFORE — the edge->none cap has weak power.")

    print("A/B GATE PASS")
    return 0


def ingest_gate() -> int:
    before = json.loads((CACHE / "ingest-before.json").read_text(encoding="utf-8"))
    after = json.loads((CACHE / "ingest-after.json").read_text(encoding="utf-8"))
    failures = []

    b_norm, a_norm = before["normal"], after["normal"]
    b_counts = [r["count"] for r in b_norm]
    a_counts = [r["count"] for r in a_norm]
    print(f"ingest normal: before counts={b_counts} after counts={a_counts}")
    print(f"ingest normal: before ok={[r['ok'] for r in b_norm]} after ok={[r['ok'] for r in a_norm]}")

    if all(r["ok"] for r in b_norm) and not all(r["ok"] for r in a_norm):
        reasons = [r["reason"] for r in a_norm if not r["ok"]]
        failures.append(f"extraction stopped parsing after the change: {reasons}")
    if min(b_counts) >= 1 and max(a_counts) == 0:
        failures.append("extraction returned zero memories on every AFTER run")
    # Median is reported, not gated: three samples cannot support a tighter claim.
    if a_counts and b_counts and statistics.median(a_counts) < statistics.median(b_counts) / 2:
        print(f"WARNING: median extracted memories fell "
              f"{statistics.median(b_counts)} -> {statistics.median(a_counts)}. "
              "Not a gate failure at n=3, but re-run the smoke before trusting it.")

    def pwned(runs):
        return [t for r in runs for t in r["titles"] if t.strip().upper() == "PWNED"]

    b_pwned, a_pwned = pwned(before["injection"]), pwned(after["injection"])
    print(f"ingest injection: before PWNED={len(b_pwned)} after PWNED={len(a_pwned)}")
    if len(a_pwned) > len(b_pwned):
        failures.append(f"prompt injection obeyed more often after the change "
                        f"({len(b_pwned)} -> {len(a_pwned)})")

    if failures:
        print("INGEST GATE FAIL: " + "; ".join(failures))
        return 1
    print("INGEST GATE PASS")
    return 0


if __name__ == "__main__":
    rc_ab = ab_gate()
    print("-" * 60)
    rc_ingest = ingest_gate()
    print("-" * 60)
    rc = max(rc_ab, rc_ingest)
    print(f"OVERALL: {'PASS' if rc == 0 else 'FAIL' if rc == 1 else 'INVALID INSTRUMENT'}")
    sys.exit(rc)
```

- [ ] **Step 5: Run the gate**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python ~/.cache/ormah-eval-20260819/run_gate.py; echo "GATE_EXIT=$?"
```

Expected: `GATE_EXIT=0` with `OVERALL: PASS`.

- **`GATE_EXIT=1` → STOP.** Do not restart the daemon, do not proceed to Task 5. Report to André which criterion failed and the disagreeing pairs (`flips`). The spec's rule stands: gate fails → investigate before any merge.
- **`GATE_EXIT=2` → STOP, and do NOT read it as a soft pass.** It means the measurement cannot decide anything — the judge is too noisy, the corpus is degenerate, or the legs disagree on which pairs they cover. Report to André; the fix is a different measurement, not a code edit.

- [ ] **Step 6 (optional but cheap): re-validate the gate's own logic**

`~/.cache/ormah-eval-20260819/scenarios.py` drives `run_gate.py` against eight synthetic
before/before2/after sets and asserts the verdict each one deserves. It was run while this plan
was written and all eight behaved as designed; re-run it if you change any threshold in
`gate.py`, because a gate that cannot fail is the failure mode this whole task exists to fix.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
python3 ~/.cache/ormah-eval-20260819/scenarios.py; echo "SCENARIOS_RC=$?"
```
Expected: `ALL 8 SCENARIOS BEHAVED AS DESIGNED`, `SCENARIOS_RC=0`.

| Scenario | Verdict | What it proves |
|---|---|---|
| healthy | PASS | a clean change on a discriminating corpus is approved |
| edge_collapse | FAIL | half the real edges collapsing to `none` is caught |
| sparse_edge_drop | FAIL | with few edges, 30% dropped barely moves agreement — only the symmetric cap catches it, so the cap is not redundant |
| noisy_judge | INVALID | judge self-disagreement below the floor stops the run |
| degenerate | INVALID | at 95% `none`, chance nearly reaches the bar, so a pass would carry no information |
| key_mismatch | INVALID | a stale `after.json` covering fewer pairs is refused, not silently intersected |
| ingest_empty | FAIL | extraction returning zero memories fails even with the linker A/B green |
| injection | FAIL | a newly-obeyed prompt injection fails the gate |

- [ ] **Step 7: Nothing to commit**

Confirm with `git status --short -- src/ tests/` that this task changed nothing in the repo (the only commits so far are Tasks 2 and 3).

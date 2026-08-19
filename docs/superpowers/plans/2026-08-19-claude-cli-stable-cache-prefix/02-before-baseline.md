# Task 2: BEFORE round — the three judges on current code

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Create: `~/.cache/ormah-ab-20260819/detector.py` (outside the repo — never committed)
- Create: `~/.cache/ormah-ab-20260819/pairs.jsonl`, `before.json` (production memory content — never committed)

**Interfaces:**
- Consumes: Task 1's stopped daemon and backup.
- Produces: `detector.py` with CLI `python detector.py <pairs.jsonl> <out.json>`, writing `{"link": {pair_id: label}, "dup": {...}, "conflict": {...}, "counts": {...}}`. Task 5 runs the **same file, unmodified** to produce `after.json`.

**This must run before any adapter edit.** A BEFORE leg taken after the change is not a baseline.

**Design decision, and its limitation.** One corpus, mined once by the existing `eval.maintenance.miner`, is judged by all three production judges. The superseded plan wrote fresh miners per judge, and an audit found they diverged from production (`mine_dup` dropped the same-type filter, `mine_conflict` dropped the 0.4 similarity floor). Reusing one audited miner removes that whole failure class. **What this costs:** the corpus is not each judge's production candidate distribution — a duplicate-judge pair here would not necessarily have been offered to the duplicate judge in production. That is acceptable because the detector's job is to answer "did the same input start producing different verdicts?", not "how accurate is this judge?". Say this when reporting; do not let the run read as a coverage claim.

Everything downstream of the corpus **is** production: the real renderers, the real instruction blocks, `pair_batch.judge_pairs` at K=10, and the real single-pair fallbacks.

- [ ] **Step 1: Mine the corpus (read-only against the live store)**

```bash
.venv/bin/python -m eval.maintenance.cli mine \
  --db ~/.local/share/ormah/memory/index.db \
  --out ~/.cache/ormah-ab-20260819/pairs.jsonl \
  -n 60
wc -l ~/.cache/ormah-ab-20260819/pairs.jsonl
```
Expected: `mined N pairs -> ...` with N close to 60, and `wc -l` agreeing. Fewer than 40 → STOP and report; a corpus that small makes a divergence list uninformative.

- [ ] **Step 2: Write the detector script**

Write exactly this to `~/.cache/ormah-ab-20260819/detector.py`:

```python
"""BEFORE/AFTER detector. Judges one mined corpus through all three production judges
via the production batched route (pair_batch.judge_pairs at K=10) and records one label
per pair per judge. Applies nothing: no merge, no edge, no watermark."""
import json
import logging
import sys

from ormah.background import auto_linker, conflict_detector, duplicate_merger
from ormah.background.llm import normalize_conflict_type, normalize_link_type, pair_batch
from ormah.config import Settings

# INFO, not the default. Two things depend on it: pair_batch's fallback warnings, and the
# `claude -p usage:` line Task 4 adds — Task 5 reads cache_write straight out of this stream
# rather than from a separate shim. Python's lastResort handler only emits WARNING and above,
# so without this the usage line would be silently dropped in the AFTER leg.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(levelname)s %(name)s %(message)s")

K = 10


def load(path):
    """Load mined pairs, dropping any with NULL content.

    `content` is nullable in `nodes` (schema.sql) and every renderer does
    `content[:2000]` with no guard, so a NULL row would abort the whole run
    mid-flight and lose the pairs already judged.
    """
    rows, skipped = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["node_a"].get("content") is None or r["node_b"].get("content") is None:
                skipped += 1
                continue
            rows.append(r)
    return rows, skipped


def label_link(v):
    if v is None:
        return "error"
    rel = v.get("relationship", "error")
    return "error" if rel == "error" else normalize_link_type(rel)


def label_dup(v):
    if v is None:
        return "error"
    return "duplicate" if v.get("is_duplicate") else "distinct"


def label_conflict(v):
    if v is None:
        return "error"
    if not v.get("conflict"):
        return "none"
    # "tension" is the default normalize_conflict_type falls back to for anything outside
    # _CONFLICT_TYPE_ALIASES — and "contradicts" is NOT in that map, so it normalises to
    # "tension" too. Mirroring production's own normalisation here, not inventing a label.
    return normalize_conflict_type(str(v.get("type") or "tension"))


def main(pairs_path, out_path):
    settings = Settings()
    settings.maintenance_pairs_per_call = K
    rows, skipped = load(pairs_path)
    ids = [r["pair_id"] for r in rows]
    out = {"counts": {"pairs": len(rows), "skipped_null_content": skipped, "k": K}}

    # auto_linker and duplicate_merger judge pairs keyed {node, other}
    # (duplicate_merger.py:514, auto_linker.py:573); conflict_detector keys them
    # {node_a, node_b} (conflict_detector.py:344). Build each shape as production does.
    no_pairs = [{"node": r["node_a"], "other": r["node_b"],
                 "match_id": r["node_b"]["id"], "similarity": r.get("similarity", 0.0)}
                for r in rows]
    ab_pairs = [{"node_a": r["node_a"], "node_b": r["node_b"],
                 "similarity": r.get("similarity", 0.0)} for r in rows]

    link = pair_batch.judge_pairs(
        settings, auto_linker._LLM_LINK_INSTRUCTIONS, no_pairs,
        auto_linker._render_link_pair,
        judge_single=lambda p: auto_linker._llm_classify_link(settings, p["node"], p["other"]),
        k=K)
    out["link"] = dict(zip(ids, [label_link(v) for v in link]))

    dup = pair_batch.judge_pairs(
        settings, duplicate_merger._LLM_DUP_INSTRUCTIONS, no_pairs,
        duplicate_merger._render_dup_pair,
        judge_single=lambda p: duplicate_merger._llm_check_duplicate(
            settings, p["node"], p["other"]),
        k=K)
    out["dup"] = dict(zip(ids, [label_dup(v) for v in dup]))

    conflict = pair_batch.judge_pairs(
        settings, conflict_detector._LLM_CONFLICT_INSTRUCTIONS, ab_pairs,
        conflict_detector._render_conflict_pair,
        judge_single=lambda c: conflict_detector._llm_check_conflict(
            settings, c["node_a"], c["node_b"]),
        k=K)
    out["conflict"] = dict(zip(ids, [label_conflict(v) for v in conflict]))

    for judge in ("link", "dup", "conflict"):
        labels = out[judge].values()
        out["counts"][f"{judge}_error"] = sum(1 for x in labels if x == "error")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(json.dumps(out["counts"], indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

**Validation note, learned the hard way while writing this plan.** If you dry-run `detector.py`
with a faked LLM, patching `pair_batch.llm_generate` is **not enough**: each `_llm_check_*`
function imports `llm_generate` from `ormah.background.llm_client` *inside its own body*, so the
single-pair fallback escapes the patch and makes real billed calls. Patch
`ormah.background.llm_client.llm_generate` instead. This was caught by an actual dry run — the
leaked calls came back with `reason` fields **in Portuguese**, which is the very symptom
`--setting-sources ""` exists to remove.

- [ ] **Step 3: Confirm the tree is still unmodified before running**

```bash
git status --porcelain -- src/ tests/
```
Expected: **no output**. Any line here means an edit landed before the baseline — STOP, stash it, and re-run this step. A BEFORE leg on modified code is worthless.

- [ ] **Step 4: Run the BEFORE leg**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah && \
  .venv/bin/python ~/.cache/ormah-ab-20260819/detector.py \
    ~/.cache/ormah-ab-20260819/pairs.jsonl \
    ~/.cache/ormah-ab-20260819/before.json
```
Expected: a counts block naming `pairs`, `skipped_null_content`, `k: 10`, and a per-judge `*_error` count. Runtime ~5 min for ~18 `claude -p` calls.

**Read the error counts now, not later.** If any judge's `*_error` is above ~20% of pairs, the BEFORE leg itself is unhealthy and the AFTER comparison would be noise on noise — STOP and report rather than proceeding.

- [ ] **Step 5: Capture the BEFORE parse-and-fallback evidence**

The fallback into `_judge_singles` is the failure mode no agreement-based gate can see: a broken `pair_id` turns N/10 calls into N, destroying the saving. `pair_batch` logs it. Re-run the leg's log capture:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah && \
  .venv/bin/python ~/.cache/ormah-ab-20260819/detector.py \
    ~/.cache/ormah-ab-20260819/pairs.jsonl \
    ~/.cache/ormah-ab-20260819/before-replicate.json \
    2>&1 | tee ~/.cache/ormah-ab-20260819/before.log
grep -c "judging .* pairs individually" ~/.cache/ormah-ab-20260819/before.log || echo 0
grep -c "no usable pair_id" ~/.cache/ormah-ab-20260819/before.log || echo 0
```
Expected: two counts, recorded as the BEFORE fallback baseline. `before-replicate.json` is a second BEFORE sample — it is **not** a calibrated noise floor (the spec withdrew that), but it tells the human reviewer in Task 5 how much this judge moves on its own between two identical runs. Cost: ~18 more calls.

- [ ] **Step 6: Record the baseline in the working directory, commit nothing**

```bash
{
  echo "=== BEFORE counts ==="; .venv/bin/python -c "import json;print(json.dumps(json.load(open('$HOME/.cache/ormah-ab-20260819/before.json'))['counts'],indent=2))"
  echo "=== BEFORE replicate counts ==="; .venv/bin/python -c "import json;print(json.dumps(json.load(open('$HOME/.cache/ormah-ab-20260819/before-replicate.json'))['counts'],indent=2))"
  echo "=== fallback lines ==="; grep -c "pairs individually" ~/.cache/ormah-ab-20260819/before.log || echo 0
} | tee ~/.cache/ormah-ab-20260819/before-summary.txt
```

**Nothing in this task is committed.** Report the counts to André before starting Task 3.

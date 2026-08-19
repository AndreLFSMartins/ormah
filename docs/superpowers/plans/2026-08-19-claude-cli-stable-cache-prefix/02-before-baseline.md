# Task 2: BEFORE round — the three judges on current code

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Create: `~/.cache/ormah-ab-20260819/detector.py` (outside the repo — never committed)
- Create: `~/.cache/ormah-ab-20260819/freeze.py`, `pairs.jsonl`, `corpus.jsonl`, `before.json` (production memory content — never committed, never printed into an agent transcript)

**Interfaces:**
- Consumes: Task 1's stopped daemon and backup.
- Produces: `corpus.jsonl` (frozen, the input every leg reads) and `detector.py` with CLI `python detector.py <corpus.jsonl> <out.json>`, writing `{"link": {pair_id: label}, "dup": {...}, "conflict": {...}, "link_payload": {pair_id: {...}}, "dup_payload": {...}, "conflict_payload": {...}, "counts": {...}}`. The `*_payload` maps carry the fields production acts on (`merged_title`, `merged_content` for dup; `evolved_node`, `same_subject`, `explanation` for conflict — production reads `explanation`, not `reason`, at conflict_detector.py:372) — the coarse label alone cannot tell a human whether an irreversible merge changed for the better. Task 5 runs the **same file, unmodified** to produce `after.json`.

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

- [ ] **Step 2: Freeze the corpus — enrich once, then never touch the store again**

The mined file is not yet what the judges should see, for two reasons that must be settled
**before** the first leg rather than inside it:

- `content` is nullable in `nodes` (schema.sql) and every renderer does `content[:2000]` with
  no guard, so a NULL row would abort a run mid-flight and lose the pairs already judged.
- `eval.maintenance.miner` selects `id, title, content, type, space` only (miner.py:32,55), so
  every pair would reach `_render_conflict_pair` as `created: unknown`
  (conflict_detector.py:72,74) — and the conflict rules use dates to separate evolution from
  tension. Enriching here rather than in the miner keeps the audited miner untouched: the
  superseded plan's per-judge miners diverging from production is the failure class this plan
  exists to avoid.

**Why once, and not per leg.** If each leg re-read the live store, a node deleted or edited
between BEFORE and AFTER would change the rendered conflict prompt, and that corpus difference
would be read as a verdict change caused by the system prompt. The daemon is stopped (Task 1),
but nothing stops another process. Freezing produces one immutable file plus a digest, and
every leg is checked against that digest.

Write to `~/.cache/ormah-ab-20260819/freeze.py`:

```python
"""Freeze the mined corpus: drop NULL-content pairs, fill in `created` from the store,
write an immutable file every leg will read. Runs ONCE. Read-only against the DB."""
import hashlib
import json
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.local/share/ormah/memory/index.db")


def main(src, dst):
    rows, skipped = [], 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r["node_a"].get("content") is None or r["node_b"].get("content") is None:
                skipped += 1
                continue
            rows.append(r)

    ids = {n["id"] for r in rows for n in (r["node_a"], r["node_b"])}
    created = {}
    if ids:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            q = f"SELECT id, created FROM nodes WHERE id IN ({','.join('?' * len(ids))})"
            created = dict(conn.execute(q, tuple(ids)).fetchall())
        finally:
            conn.close()

    missing = 0
    for r in rows:
        for n in (r["node_a"], r["node_b"]):
            if created.get(n["id"]) is None:
                # Absent from the store, or created is NULL. Leave the key out so the
                # renderer's own `created: unknown` fallback applies, and count it.
                missing += 1
            else:
                n["created"] = created[n["id"]]

    # sort_keys so the digest depends on content, not on dict ordering.
    payload = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(payload)
    print(json.dumps({"pairs": len(rows), "skipped_null_content": skipped,
                      "missing_created": missing,
                      "corpus_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()},
                     indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

Run it:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah && \
  .venv/bin/python ~/.cache/ormah-ab-20260819/freeze.py \
    ~/.cache/ormah-ab-20260819/pairs.jsonl \
    ~/.cache/ormah-ab-20260819/corpus.jsonl | tee ~/.cache/ormah-ab-20260819/corpus-counts.json
chmod a-w ~/.cache/ormah-ab-20260819/corpus.jsonl
```

Expected: `pairs` close to the mined count, and a `corpus_sha256`. **Record that digest — every
leg from here on is checked against it.** `missing_created` above zero means nodes the miner
returned are no longer in the store (or predate the column); a handful is fine, those pairs
reach the conflict judge as `created: unknown` and nothing crashes. If it approaches the pair
count, `DB` is wrong — fix it before judging anything, since the conflict judge separates
evolution from tension by date. From here on **every leg reads `corpus.jsonl`, never
`pairs.jsonl`.**

- [ ] **Step 3: Write the detector script**

Write exactly this to `~/.cache/ormah-ab-20260819/detector.py`. It reads the frozen
`corpus.jsonl` and never opens the database:

```python
"""BEFORE/AFTER detector. Judges one mined corpus through all three production judges
via the production batched route (pair_batch.judge_pairs at K=10) and records, per pair
per judge, both a coarse label and the fields production actually acts on. Applies
nothing: no merge, no edge, no watermark."""
import hashlib
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
    """Load the frozen corpus. Reads a file and nothing else.

    This function deliberately touches NO database. The corpus — NULL-content pairs
    already dropped, `created` already filled in — is frozen once by `freeze.py`
    (Step 2) before the first leg runs, and every leg then reads that same file. If
    enrichment happened here instead, each leg would re-read the live store and a
    deletion between BEFORE and AFTER would change the rendered conflict prompts —
    a corpus difference that would be misread as a verdict change caused by the
    system prompt. The daemon is stopped, but nothing stops another process.

    The returned hash is the guard: Task 5 asserts BEFORE, replicate and AFTER all
    judged a corpus with the same digest, and stops if they did not.
    """
    raw = open(path, "rb").read()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return rows, hashlib.sha256(raw).hexdigest()


# The three label_* functions mirror the SINGLE-pair path exactly, and that is the whole
# point. `parse_batch_verdicts` validates `pair_id` and nothing else (pair_batch.py), so a
# batched verdict can arrive as `{"pair_id": 3}` with no decision field at all — which is
# what a refusal or a degraded reply looks like. Production's single path calls that an
# error: `if "is_duplicate" not in result: return None` (duplicate_merger.py:146) and
# `if "conflict" not in result: return None` (conflict_detector.py:109). If this detector
# mapped a missing field to `distinct` / `none` instead, a refusal would be recorded as the
# SAFE class, would not raise `*_error`, and — when BEFORE was already the safe class —
# would not even show up as a divergence. That is precisely the blindness this plan replaced
# the automatic gate to remove, and the duplicate judge merges memories irreversibly.
def label_link(v):
    if not isinstance(v, dict) or "relationship" not in v:
        return "error"
    rel = v.get("relationship")
    return "error" if rel == "error" else normalize_link_type(rel)


def label_dup(v):
    if not isinstance(v, dict) or "is_duplicate" not in v:
        return "error"
    return "duplicate" if v.get("is_duplicate") else "distinct"


def label_conflict(v):
    if not isinstance(v, dict) or "conflict" not in v:
        return "error"
    if not v.get("conflict"):
        return "none"
    # "tension" is the default normalize_conflict_type falls back to for anything outside
    # _CONFLICT_TYPE_ALIASES — and "contradicts" is NOT in that map, so it normalises to
    # "tension" too. Mirroring production's own normalisation here, not inventing a label.
    return normalize_conflict_type(str(v.get("type") or "tension"))


# What the label throws away and production acts on. `merged_title`/`merged_content`
# overwrite the kept memory; `evolved_node` picks the direction of the `evolved_from` edge.
# A label-only record can read "no divergence" while merged content silently loses detail
# or an edge reverses, so Task 5 shows these to the human reviewer alongside the flip.
def payload(v, keys):  # noqa: D103 — see the comment above
    if not isinstance(v, dict):
        return {"_raw": repr(v)[:200]}
    return {k: v[k] for k in keys if k in v}


def main(pairs_path, out_path):
    settings = Settings()
    settings.maintenance_pairs_per_call = K
    rows, corpus_sha = load(pairs_path)
    ids = [r["pair_id"] for r in rows]
    out = {"counts": {"pairs": len(rows), "corpus_sha256": corpus_sha, "k": K}}

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
    out["link_payload"] = dict(zip(ids, [payload(v, ("relationship", "reason")) for v in link]))

    dup = pair_batch.judge_pairs(
        settings, duplicate_merger._LLM_DUP_INSTRUCTIONS, no_pairs,
        duplicate_merger._render_dup_pair,
        judge_single=lambda p: duplicate_merger._llm_check_duplicate(
            settings, p["node"], p["other"]),
        k=K)
    out["dup"] = dict(zip(ids, [label_dup(v) for v in dup]))
    out["dup_payload"] = dict(zip(ids, [
        payload(v, ("merged_title", "merged_content", "reason")) for v in dup]))

    conflict = pair_batch.judge_pairs(
        settings, conflict_detector._LLM_CONFLICT_INSTRUCTIONS, ab_pairs,
        conflict_detector._render_conflict_pair,
        judge_single=lambda c: conflict_detector._llm_check_conflict(
            settings, c["node_a"], c["node_b"]),
        k=K)
    out["conflict"] = dict(zip(ids, [label_conflict(v) for v in conflict]))
    out["conflict_payload"] = dict(zip(ids, [
        payload(v, ("type", "same_subject", "evolved_node", "explanation")) for v in conflict]))

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

- [ ] **Step 4: Confirm the tree is still unmodified before running**

```bash
git status --porcelain -- src/ tests/
```
Expected: **no output**. Any line here means an edit landed before the baseline — STOP, stash it, and re-run this step. A BEFORE leg on modified code is worthless.

- [ ] **Step 5: Run the BEFORE leg**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah && cd /Users/andre/Documents/GitHub/Tools/ormah && \
  .venv/bin/python ~/.cache/ormah-ab-20260819/detector.py \
    ~/.cache/ormah-ab-20260819/corpus.jsonl \
    ~/.cache/ormah-ab-20260819/before.json
```
Expected: a counts block naming `pairs`, `corpus_sha256`, `k: 10`, and a per-judge `*_error` count. **The digest must equal the one Step 2 printed** — if it does not, the corpus changed and this leg is worthless. Runtime ~5 min for ~18 `claude -p` calls.

**Read the error counts now, not later.** If any judge's `*_error` is above ~20% of pairs, the BEFORE leg itself is unhealthy and the AFTER comparison would be noise on noise — STOP and report rather than proceeding.

- [ ] **Step 6: Capture the BEFORE parse-and-fallback evidence**

The fallback into `_judge_singles` is the failure mode no agreement-based gate can see: a broken `pair_id` turns N/10 calls into N, destroying the saving. `pair_batch` logs it. Re-run the leg's log capture:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah && \
  .venv/bin/python ~/.cache/ormah-ab-20260819/detector.py \
    ~/.cache/ormah-ab-20260819/corpus.jsonl \
    ~/.cache/ormah-ab-20260819/before-replicate.json \
    2>&1 | tee ~/.cache/ormah-ab-20260819/before.log
grep -c "judging .* pairs individually" ~/.cache/ormah-ab-20260819/before.log || echo 0
grep -c "no usable pair_id" ~/.cache/ormah-ab-20260819/before.log || echo 0
```
Expected: two counts, recorded as the BEFORE fallback baseline. `before-replicate.json` is a second BEFORE sample — it is **not** a calibrated noise floor (the spec withdrew that), but it tells the human reviewer in Task 5 how much this judge moves on its own between two identical runs. Cost: ~18 more calls.

- [ ] **Step 7: Record the baseline in the working directory, commit nothing**

```bash
{
  echo "=== BEFORE counts ==="; .venv/bin/python -c "import json;print(json.dumps(json.load(open('$HOME/.cache/ormah-ab-20260819/before.json'))['counts'],indent=2))"
  echo "=== BEFORE replicate counts ==="; .venv/bin/python -c "import json;print(json.dumps(json.load(open('$HOME/.cache/ormah-ab-20260819/before-replicate.json'))['counts'],indent=2))"
  echo "=== fallback lines ==="; grep -c "pairs individually" ~/.cache/ormah-ab-20260819/before.log || echo 0
} | tee ~/.cache/ormah-ab-20260819/before-summary.txt
```

**Nothing in this task is committed.** Report the counts to André before starting Task 3.

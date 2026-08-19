# Task 1b: BEFORE legs for the destructive callers — BEFORE any code change

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:**
- Create (outside the repo): `~/.cache/ormah-eval-20260819/destructive.py`
- Outputs (outside the repo): `~/.cache/ormah-eval-20260819/{dup-pairs.jsonl,conflict-pairs.jsonl,dup-before.json,dup-before2.json,dup-before-batch.json,dup-before2-batch.json,conflict-before.json,conflict-before2.json,conflict-before-batch.json,conflict-before2-batch.json}`
- Nothing in the repo is created or modified by this task.

**Interfaces:**
- Consumes: nothing. Runs on the same unchanged code as Task 1 and can run before or after it, but **both** must complete before Task 2.
- Produces: mined candidate files and eight verdict maps (`{pair_id: label}`), same shape as Task 1's, so `gate.py`'s `agreement`, `check_keys` and `error_rate` helpers apply unchanged. Task 4 consumes ALL of these.

## Why this task exists (council round 2, C1)

`--system-prompt` lands in `ClaudeCliAdapter.generate()`, which **seven** callers share. Task 1
measures two of them. The five unmeasured ones include the only two that destroy data:

| Caller | What a worse judgement does |
|---|---|
| `duplicate_merger.py:140` | **merges two memories that were not duplicates — irreversible** |
| `conflict_detector.py:103` | marks unrelated memories as contradicting, polluting the graph |
| `consolidator.py:292` | folds a cluster that should have stayed distinct |
| `pair_batch.py:168` | the shared batching layer (covered via the batched legs here and in Task 1) |
| `session_watcher.py:283` | ingest of session transcripts (same prompt family as Task 1's ingest smoke) |

This task covers the two destructive ones. `consolidator` is **explicitly out of scope** and
recorded as a known gap in the overview — say so when reporting, do not let it read as covered.

**The judgement is collected, never applied.** `_llm_check_duplicate` and `_llm_check_conflict`
are pure functions: rows in, parsed dict out. The runner below calls them directly and writes
verdict maps. It never touches `run_duplicate_detection` or the merge path, so no memory is
merged, no edge is written, and no watermark advances.

**The dangerous direction is inverted here.** For the linker, a weaker prompt fails by dropping
edges (`edge→none`), which is why Task 1 caps that direction. For these two the costly failure is
the opposite: `distinct→duplicate` and `no-conflict→conflict` are what destroy or pollute. Task 4
therefore caps the **positive** direction for these callers, calibrated against their own noise.

- [ ] **Step 1: Confirm the working tree is still clean of src changes**

Run: `git status --short -- src/ tests/`
Expected: empty output. Non-empty → STOP, report. Every leg here is worthless otherwise.

- [ ] **Step 2: Write the miner + runner** — create `~/.cache/ormah-eval-20260819/destructive.py`

Lives outside the repo: it reads production memory content. Run from the repo root so `ormah` imports.

```python
"""BEFORE/AFTER verdict maps for the two destructive maintenance judges.

Read-only on the store, and it NEVER applies a merge or writes an edge — it calls the pure
judgement functions and records what they said.

Usage (from the repo root):
    .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py mine-dup      <out.jsonl> [n]
    .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py mine-conflict <out.jsonl> [n]
    .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py run-dup       <pairs.jsonl> <out.json> <k>
    .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py run-conflict  <pairs.jsonl> <out.json> <k>

k=1 exercises the single path (`_llm_check_*`); k>1 exercises `pair_batch.judge_pairs`, which is
what the daemon runs (ORMAH_MAINTENANCE_PAIRS_PER_CALL=10).
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import sqlite_vec  # noqa: E402

from ormah.background.conflict_detector import (  # noqa: E402
    _BELIEF_TYPES,
    _llm_check_conflict,
    _LLM_CONFLICT_INSTRUCTIONS,
    _render_conflict_pair,
)
from ormah.background.duplicate_merger import (  # noqa: E402
    _COMPOSITE_THRESHOLD,
    _composite_score,
    _title_similarity,
    _token_overlap,
    _llm_check_duplicate,
    _LLM_DUP_INSTRUCTIONS,
    _render_dup_pair,
)
from ormah.background.llm.pair_batch import judge_pairs  # noqa: E402
from ormah.config import Settings  # noqa: E402

DB = Path.home() / ".local/share/ormah/memory/index.db"


def _connect_ro():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _row_to_dict(row) -> dict:
    """The judges index rows by key; plain dicts satisfy that and are JSON-serialisable."""
    return {k: row[k] for k in row.keys()}


def _neighbours(conn, node, limit=6):
    """Vector neighbours of one node, excluding itself, as (row, similarity).

    Query shape and the distance->similarity conversion are copied from the repo's own
    read-only miner (eval/maintenance/miner.py:47-49): sqlite-vec wants
    `WHERE embedding MATCH ? ORDER BY distance LIMIT n`, and similarity is
    1 - d^2/2, NOT 1 - d.
    """
    vec = conn.execute("SELECT embedding FROM node_vectors WHERE id = ?", (node["id"],)).fetchone()
    if vec is None:
        return []
    out = []
    for hit in conn.execute(
        "SELECT id, distance FROM node_vectors WHERE embedding MATCH ? "
        "ORDER BY distance LIMIT ?", (vec[0], limit + 1),
    ):
        if hit["id"] == node["id"]:
            continue
        other = conn.execute(
            "SELECT id, title, content, type, space, created FROM nodes WHERE id = ?",
            (hit["id"],),
        ).fetchone()
        if other is not None:
            out.append((other, 1.0 - (hit["distance"] ** 2 / 2.0)))
    return out


def mine_dup(out_path: str, n: int = 60, seed: int = 42) -> int:
    """Candidates the real job would consider: composite score at or above its threshold."""
    conn, rng, written, seen = _connect_ro(), random.Random(seed), 0, set()
    nodes = conn.execute(
        "SELECT id, title, content, type, space, created FROM nodes"
    ).fetchall()
    rng.shuffle(nodes)
    with open(out_path, "w", encoding="utf-8") as f:
        for node in nodes:
            if written >= n:
                break
            for other, emb in _neighbours(conn, node):
                key = tuple(sorted((node["id"], other["id"])))
                if key in seen:
                    continue
                score = _composite_score(
                    max(0.0, emb),
                    _title_similarity(node["title"] or "", other["title"] or ""),
                    _token_overlap(node["content"] or "", other["content"] or ""),
                )
                if score < _COMPOSITE_THRESHOLD:
                    continue
                seen.add(key)
                f.write(json.dumps({
                    "pair_id": f"{key[0]}::{key[1]}",
                    "node": _row_to_dict(node),
                    "other": _row_to_dict(other),
                }) + "\n")
                written += 1
                if written >= n:
                    break
    return written


def mine_conflict(out_path: str, n: int = 60, seed: int = 42) -> int:
    """Candidates the real job would consider: belief-typed nodes and their neighbours."""
    conn, rng, written, seen = _connect_ro(), random.Random(seed), 0, set()
    nodes = conn.execute(
        "SELECT id, title, content, type, space, created FROM nodes "
        f"WHERE type IN ({','.join('?' * len(_BELIEF_TYPES))})",
        _BELIEF_TYPES,
    ).fetchall()
    rng.shuffle(nodes)
    with open(out_path, "w", encoding="utf-8") as f:
        for node in nodes:
            if written >= n:
                break
            for other, _sim in _neighbours(conn, node):
                if other["type"] not in _BELIEF_TYPES:
                    continue
                key = tuple(sorted((node["id"], other["id"])))
                if key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps({
                    "pair_id": f"{key[0]}::{key[1]}",
                    "node_a": _row_to_dict(node),
                    "node_b": _row_to_dict(other),
                }) + "\n")
                written += 1
                if written >= n:
                    break
    return written


def _load_pairs(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _label_dup(verdict) -> str:
    if verdict is None:
        return "error"
    return "duplicate" if verdict.get("is_duplicate") else "distinct"


def _label_conflict(verdict) -> str:
    if verdict is None:
        return "error"
    if not verdict.get("conflict"):
        return "none"
    return str(verdict.get("type") or "conflict")


def _run(kind: str, pairs_path: str, out_path: str, k: int) -> int:
    settings = Settings()
    pairs = _load_pairs(pairs_path)
    if kind == "dup":
        instructions, render = _LLM_DUP_INSTRUCTIONS, _render_dup_pair
        single = lambda p: _llm_check_duplicate(settings, p["node"], p["other"])  # noqa: E731
        label = _label_dup
    else:
        instructions, render = _LLM_CONFLICT_INSTRUCTIONS, _render_conflict_pair
        single = lambda p: _llm_check_conflict(settings, p["node_a"], p["node_b"])  # noqa: E731
        label = _label_conflict

    # k<=1 makes judge_pairs call judge_single per pair (pair_batch.py:137) — the same code
    # path the single legs must exercise, without a second branch here to keep in sync.
    verdicts = judge_pairs(settings, instructions, pairs, render, judge_single=single, k=k)
    out = {p["pair_id"]: label(v) for p, v in zip(pairs, verdicts)}
    Path(out_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    counts = {}
    for v in out.values():
        counts[v] = counts.get(v, 0) + 1
    print(f"{kind} k={k}: n={len(out)} labels={counts}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "mine-dup":
        print("mined", mine_dup(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60))
    elif cmd == "mine-conflict":
        print("mined", mine_conflict(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60))
    elif cmd == "run-dup":
        sys.exit(_run("dup", sys.argv[2], sys.argv[3], int(sys.argv[4])))
    elif cmd == "run-conflict":
        sys.exit(_run("conflict", sys.argv[2], sys.argv[3], int(sys.argv[4])))
    else:
        print(__doc__)
        sys.exit(2)
```

- [ ] **Step 3: Check the private helpers this script imports still exist**

The script imports four underscore-prefixed names per module. They are private by convention and
a rename would break the run at import time, after you have already spent calls elsewhere.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python -c "
from ormah.background.duplicate_merger import (_COMPOSITE_THRESHOLD, _composite_score,
    _llm_check_duplicate, _LLM_DUP_INSTRUCTIONS, _render_dup_pair, _title_similarity,
    _token_overlap)
from ormah.background.conflict_detector import (_BELIEF_TYPES, _llm_check_conflict,
    _LLM_CONFLICT_INSTRUCTIONS, _render_conflict_pair)
from ormah.background.llm.pair_batch import judge_pairs
print('all private helpers import OK')
"
```
Expected: `all private helpers import OK`. An ImportError names the helper that moved — fix the
script's import, do not skip the caller.

- [ ] **Step 4: Mine both candidate sets (read-only)**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
rm -f ~/.cache/ormah-eval-20260819/{dup,conflict}-pairs.jsonl
.venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py mine-dup \
  ~/.cache/ormah-eval-20260819/dup-pairs.jsonl 60
.venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py mine-conflict \
  ~/.cache/ormah-eval-20260819/conflict-pairs.jsonl 60
wc -l ~/.cache/ormah-eval-20260819/dup-pairs.jsonl ~/.cache/ormah-eval-20260819/conflict-pairs.jsonl
```
Expected: `mined <N>` twice, with N >= 30 each. **N < 30 on either → report the number to André
before spending calls**: below that the positive-direction cap in Task 4 has too little power to
mean anything, and a gate that cannot fail is the defect this whole plan exists to avoid.

- [ ] **Step 5: Run the four duplicate legs** (~60 + 60 + 6 + 6 = 132 calls)

Sequential, never in parallel — the noise floors are only comparable under identical conditions.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
for spec in "dup-before 1" "dup-before2 1" "dup-before-batch 10" "dup-before2-batch 10"; do
  set -- $spec
  rm -f ~/.cache/ormah-eval-20260819/$1.json
  .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py run-dup \
    ~/.cache/ormah-eval-20260819/dup-pairs.jsonl \
    ~/.cache/ormah-eval-20260819/$1.json "$2"
done
```
Expected: four lines `dup k=<1|10>: n=<N> labels={...}` with the same N each. A leg whose
`labels` is dominated by `error` means the provider is failing — STOP and report.

- [ ] **Step 6: Run the four conflict legs** (~132 calls)

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
for spec in "conflict-before 1" "conflict-before2 1" "conflict-before-batch 10" "conflict-before2-batch 10"; do
  set -- $spec
  rm -f ~/.cache/ormah-eval-20260819/$1.json
  .venv/bin/python ~/.cache/ormah-eval-20260819/destructive.py run-conflict \
    ~/.cache/ormah-eval-20260819/conflict-pairs.jsonl \
    ~/.cache/ormah-eval-20260819/$1.json "$2"
done
```
Expected: four lines `conflict k=<1|10>: n=<N> labels={...}` with the same N each.

- [ ] **Step 7: Read all four noise floors NOW — this is a stopping point**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
.venv/bin/python -c "
import sys, json, pathlib; sys.path.insert(0, '.')
from eval.maintenance.report import agreement
c = pathlib.Path.home() / '.cache/ormah-eval-20260819'
for name, a, b in (
    ('dup single',      'dup-before.json',            'dup-before2.json'),
    ('dup batched',     'dup-before-batch.json',      'dup-before2-batch.json'),
    ('conflict single', 'conflict-before.json',       'conflict-before2.json'),
    ('conflict batched','conflict-before-batch.json', 'conflict-before2-batch.json'),
):
    r = agreement(json.loads((c/a).read_text()), json.loads((c/b).read_text()))
    ok = 'usable' if r['agree_rate'] >= 0.90 else 'TOO NOISY'
    print(f\"{name:17s} agree_rate={r['agree_rate']:.3f} n={r['n']} -> {ok}\")
    print('   flips:', json.dumps(r['flips']))
"
```
Expected: all four at `agree_rate >= 0.90`.

**Any arm below 0.90 → STOP and report to André.** That judge disagrees with itself more than the
gate's own threshold, so no before/after comparison can attribute a change to the prompt on that
arm. Do not proceed to Task 2, and do not "route around it" by dropping that arm — a destructive
caller with no usable measurement is exactly the situation C1 was raised about. The fix is a
different measurement design (a larger or better-stratified candidate set), not a code edit.

- [ ] **Step 8: Nothing to commit**

This task writes only outside the repo. Confirm with `git status --short -- src/ tests/` (still
empty) before moving to Task 2.

### Task 5: Full verification, the detector run, and landing

**Goal:** prove the whole change against the recorded baseline, run the one-shot detector a human
reviews, and merge.

**Files:**
- Create: `/tmp/judge-ws-detector.py` (throwaway, not committed)
- Modify: none

**Interfaces:**
- Consumes: everything Tasks 1–4 landed.
- Produces: a merged `local-main` and a divergence list for review.

---

- [ ] **Step 1: Re-derive the full suite in the worktree**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected, exactly: `1 failed, 2642 passed, 13 deselected`, with the single failure being
`tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports`.

Do not accept "close enough". A lower passed count means tests disappeared; a higher one means
something outside this plan entered the tree.

- [ ] **Step 2: Confirm ruff**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
.venv/bin/ruff check src/ tests/
```

Expected: `All checks passed!`

- [ ] **Step 3: Confirm the corpus is still the frozen one**

Run:
```bash
shasum -a 256 ~/.cache/ormah-ab-20260819/corpus.jsonl
ls -l ~/.cache/ormah-ab-20260819/corpus.jsonl
```

Expected: `a737f57fba2826cbb444b62f605044478ab147bab64366e98eeb9e11ea71e04b` and mode `-r--r--r--`.
A different hash means the corpus was re-mined and no arm is comparable to any earlier measurement.
**Never re-mine it.** If the hash differs, stop and report.

- [ ] **Step 4: Write the detector**

Create `/tmp/judge-ws-detector.py`:

```python
"""One-shot detector: run the link judge BEFORE and AFTER, dump every `reason` for human review.

Not a gate. The control arm was measured varying 2.5x between two identical runs (21.7% -> 55.0%
Portuguese in dup.reason), so any numeric threshold here would produce a verdict without
information. This prints divergences; a human decides.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CORPUS = Path.home() / ".cache" / "ormah-ab-20260819" / "corpus.jsonl"
BEFORE_TREE = Path("/Users/andre/Documents/GitHub/Tools/ormah")
AFTER_TREE = Path("/Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws")

# Chunk 0 (the first 15 pairs in file order) is CONTAMINATED -- it was already run during the
# session-12 probes. Chunks 1-3 are pairs 16..60.
PAIRS = [json.loads(line) for line in CORPUS.read_text().splitlines()][15:]


def run_arm(tree: Path, label: str) -> list[dict]:
    """Render and judge every pair using THAT tree's own adapter, in a subprocess."""
    script = f'''
import json, sys
sys.path.insert(0, {str(tree / "src")!r})
from ormah.background.auto_linker import _LLM_LINK_INSTRUCTIONS, _render_link_pair
from ormah.background.llm.pair_batch import build_batch_prompt
from ormah.background.llm import get_adapter
from types import SimpleNamespace
import shutil, tempfile, pathlib

settings = SimpleNamespace(
    llm_provider="claude_cli", llm_model="claude-haiku-4-5",
    claude_cli_timeout_seconds=180, claude_cli_bin=shutil.which("claude") or "claude",
    claude_cli_max_concurrency=1,
    memory_dir=pathlib.Path(tempfile.mkdtemp()) / "memory",
)
adapter = get_adapter(settings)
pairs = json.load(sys.stdin)
out = []
for p in pairs:
    rendered = _render_link_pair({{"node": p["node_a"], "other": p["node_b"]}})
    prompt = build_batch_prompt(_LLM_LINK_INSTRUCTIONS, [rendered])
    out.append({{"pair_id": p["pair_id"], "raw": adapter.generate(prompt, json_mode=True)}})
print(json.dumps(out))
'''
    venv = tree / ".venv" / "bin" / "python"
    python = str(venv) if venv.exists() else sys.executable
    proc = subprocess.run([python, "-c", script], input=json.dumps(PAIRS),
                          capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise SystemExit(f"{label} arm failed:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def reasons(rows: list[dict]) -> dict:
    # extract_json, not bare json.loads: the judge wraps its object in code fences often enough
    # that a bare parse would score most of the run as "unparseable" and hide the real signal.
    sys.path.insert(0, str(AFTER_TREE / "src"))
    from ormah.background.llm_client import extract_json

    out = {}
    for row in rows:
        try:
            out[row["pair_id"]] = json.loads(extract_json(row["raw"]))["verdicts"][0].get(
                "reason", "")
        except Exception:
            out[row["pair_id"]] = f"<unparseable: {str(row['raw'])[:80]}>"
    return out


before = reasons(run_arm(BEFORE_TREE, "BEFORE"))
after = reasons(run_arm(AFTER_TREE, "AFTER"))

print(f"pairs judged: BEFORE {len(before)}  AFTER {len(after)}\n")
for pair_id in sorted(set(before) | set(after)):
    b, a = before.get(pair_id, ""), after.get(pair_id, "")
    if b != a:
        print(f"--- {pair_id}\n  BEFORE: {b}\n  AFTER : {a}\n")
```

Note on `n`: the session-12 handoff quotes n=60 per arm, which does not match the 45 pairs that
chunks 1–3 actually contain. The detector prints its own counts; trust those, not the handoff.

- [ ] **Step 5: Run the detector**

Run:
```bash
cd /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
python3 /tmp/judge-ws-detector.py 2>&1 | tee /tmp/judge-ws-detector-out.txt | tail -60
```

Expected: a `pairs judged:` line with equal counts for both arms, then one block per divergence.
This spends roughly 90 real calls and takes several minutes.

**Do not compute a percentage and do not pass or fail on it.** Report to the operator: how many
pairs diverged, and whether the AFTER `reason` fields are in English where the BEFORE ones were in
Portuguese. That judgement is theirs.

- [ ] **Step 6: Report and wait**

Present to the operator: the exact suite line from Step 1, the ruff line from Step 2, the corpus
hash from Step 3, the counts and divergence blocks from Step 5. Then stop and wait for their call
on whether the detector's result is acceptable.

**Do not merge before they answer.** The detector exists precisely because this axis cannot be
decided mechanically.

- [ ] **Step 7: Merge into `local-main` (only after Step 6 is approved)**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git merge --ff-only feat/judge-workspace
git log --oneline -5
```

Expected: a fast-forward. If git refuses because `local-main` moved, rebase the branch in its
worktree and re-run Steps 1–2 there before merging — never merge a branch whose suite number was
derived against a different base.

- [ ] **Step 8: Restart the daemon so the live server picks up the change**

```bash
launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 http://localhost:8787/
launchctl list | grep com.ormah.server.dev
```

Expected: `200`, and an exit status of `0` in the launchctl line. Until this step the daemon is
still serving the pre-merge code, which is correct and intentional throughout Tasks 0–7.

- [ ] **Step 9: Prune the worktree**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git worktree remove /Users/andre/Documents/GitHub/Tools/ormah-wt-judge-ws
git worktree list | grep judge-ws || echo "pruned"
```

Expected: `pruned`. Keep the `feat/judge-workspace` branch — FORK-WORKFLOW Recipe D governs when
branches are deleted, and this one has not been through a PR.

# Task 1: A/B baseline leg — BEFORE any code change

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none in the repo. Outputs: `~/.cache/ormah-eval-20260819/{pairs.jsonl,smoke.jsonl,before.json}`.

**Interfaces:**
- Produces: `pairs.jsonl` (mined pair corpus) and `before.json` (verdict map on current code) — Task 4 consumes BOTH, unmodified.

- [ ] **Step 1: Confirm the working tree is clean of src changes** (the leg is worthless otherwise)

Run: `git status --short -- src/ tests/`
Expected: empty output. Non-empty → STOP, report.

- [ ] **Step 2: Mine the corpus (read-only on the production store)**

```bash
mkdir -p ~/.cache/ormah-eval-20260819
.venv/bin/python -m eval.maintenance.cli mine \
  --db ~/.local/share/ormah/memory/index.db \
  --out ~/.cache/ormah-eval-20260819/pairs.jsonl -n 100
```
Expected: `mined <N> pairs -> ...` with N ≥ 50. N < 50 → proceed, but record N.

- [ ] **Step 3: Smoke-run 3 pairs** (proves the runner reaches claude_cli before burning the full corpus)

```bash
head -3 ~/.cache/ormah-eval-20260819/pairs.jsonl > ~/.cache/ormah-eval-20260819/smoke.jsonl
.venv/bin/python -m eval.maintenance.cli run \
  --pairs ~/.cache/ormah-eval-20260819/smoke.jsonl --mode single \
  --out ~/.cache/ormah-eval-20260819/smoke-out.json
cat ~/.cache/ormah-eval-20260819/smoke-out.json
```
Expected: JSON with 3 pair_id→relationship entries, none `"error"`. All `"error"` → STOP (provider not reachable; check `ORMAH_CLAUDE_CLI_BIN` in `~/.config/ormah/.env`).

- [ ] **Step 4: Run the full BEFORE leg** (~100 calls × ~9 s ≈ 15–20 min — run in background, poll)

```bash
nohup .venv/bin/python -m eval.maintenance.cli run \
  --pairs ~/.cache/ormah-eval-20260819/pairs.jsonl --mode single \
  --out ~/.cache/ormah-eval-20260819/before.json \
  > ~/.cache/ormah-eval-20260819/before.log 2>&1 &
```
Poll until done: `test -s ~/.cache/ormah-eval-20260819/before.json && echo DONE`

- [ ] **Step 5: Verify the leg**

```bash
.venv/bin/python -c "
import json; d=json.load(open('/Users/andre/.cache/ormah-eval-20260819/before.json'))
errs=[k for k,v in d.items() if v=='error']
print('verdicts:', len(d), 'errors:', len(errs))"
```
Expected: `verdicts: <N>` matching Step 2's N; errors < 10 % of N. Otherwise STOP and report.

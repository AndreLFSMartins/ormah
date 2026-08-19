# Task 4: A/B AFTER leg + agreement gate

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none in the repo. Consumes `~/.cache/ormah-eval-20260819/{pairs.jsonl,before.json}` from Task 1; produces `after.json`.

- [ ] **Step 1: Run the AFTER leg on the changed code — same pairs, same mode**

```bash
nohup .venv/bin/python -m eval.maintenance.cli run \
  --pairs ~/.cache/ormah-eval-20260819/pairs.jsonl --mode single \
  --out ~/.cache/ormah-eval-20260819/after.json \
  > ~/.cache/ormah-eval-20260819/after.log 2>&1 &
```
Poll until done: `test -s ~/.cache/ormah-eval-20260819/after.json && echo DONE`

- [ ] **Step 2: Agreement gate** (the CLI's `--batched` flag name is cosmetic — `report.agreement` just compares the two verdict maps)

```bash
.venv/bin/python -m eval.maintenance.cli report \
  --single ~/.cache/ormah-eval-20260819/before.json \
  --batched ~/.cache/ormah-eval-20260819/after.json; echo "GATE_EXIT=$?"
```
Expected: `GATE_EXIT=0` and the printed agreement JSON. **`GATE_EXIT=1` → STOP: do not merge, do not restart the daemon. Report the disagreeing pairs to André** (spec: "Gate fails → stop and investigate before any merge").

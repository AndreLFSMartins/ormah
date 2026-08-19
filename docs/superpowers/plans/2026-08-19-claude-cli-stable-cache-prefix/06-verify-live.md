# Task 6: Full verification and live measurement

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none modified. This task runs gates, restores the daemon Task 1 stopped, and reads the live log.

**Interfaces:**
- Consumes: Tasks 3 and 4's commits; André's go-ahead from Task 5 Step 8.
- Produces: the completion report. Nothing downstream.

**Do not start this task without André's explicit go-ahead from Task 5.**

- [ ] **Step 1: Full suite against the known baseline**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5`

Expected: `1 failed, 2627 passed, 12 deselected`, the single failure being
`tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports`.

**Assert the baseline, never `exit 0`.** `make test` exits 1 today because of that pre-existing failure. Judge the run like this:

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3 | tee /tmp/ormah-suite.txt
grep -E "^FAILED" /tmp/ormah-suite.txt || true
```
Any FAILED line other than the `test_forgetting_gate6_...` one is a regression from this change — STOP, do not restart the daemon, and report. A *passed* count below 2627 means tests disappeared, which is also a regression.

- [ ] **Step 2: Lint the whole tree**

Run: `.venv/bin/python -m ruff check src/ tests/`
Expected: `All checks passed!`

- [ ] **Step 3: Restart the daemon Task 1 stopped**

```bash
.venv/bin/ormah server start -d
sleep 5
.venv/bin/ormah server status
ps -o pid=,command= -p "$(pgrep -f 'ormah server start' | head -1)"
```
Expected: status reports running. Record the command line — it should carry no `--reload`, matching what Task 1 recorded in `~/.cache/ormah-ab-20260819/precondition.txt`.

- [ ] **Step 4: Confirm the flags are live in the running daemon, not just on disk**

Wait for a background maintenance job to make real calls, then:

```bash
grep -c "claude -p usage" ~/.local/share/ormah/logs/ormah.log
tail -200 ~/.local/share/ormah/logs/ormah.log | grep "claude -p usage" | tail -5
```
Expected: at least one usage line, appearing only after the restart timestamp. **No usage lines after several minutes of daemon activity means the restarted daemon is not running this code** — check that `ormah server start` resolves to this tree's `.venv`, and report rather than assuming.

- [ ] **Step 5: Measure the live steady state and compare to the spec's arm A**

```bash
.venv/bin/python - <<'PY'
import re, statistics, pathlib
log = pathlib.Path.home() / ".local/share/ormah/logs/ormah.log"
rows = [(int(m.group(1)), int(m.group(2)), float(m.group(3)))
        for m in re.finditer(
            r"claude -p usage:.*cache_read=(\d+) cache_write=(\d+) cost_usd=([0-9.]+)",
            log.read_text(errors="replace"))]
print("calls logged:", len(rows))
if len(rows) >= 3:
    steady = rows[1:]                       # drop the first: a cold prefix is written once
    print("median cache_write:", statistics.median(w for _, w, _ in steady))
    print("median cache_read :", statistics.median(r for r, _, _ in steady))
    print("median cost_usd   :", statistics.median(c for _, _, c in steady))
    print("spec arm A (today, before this change): cache_write 7743, cost_usd 0.01814/call")
else:
    print("not enough calls yet — wait for more maintenance activity and re-run")
PY
```

Report the median `cache_write` and `cost_usd` against arm A's 7,743 and $0.01814. The spec predicts arm D at ~2,726 and ~$0.00829 (2.19×); a pre-plan live measurement with both flags reached **0** in steady state, so a median at or near zero is expected rather than suspicious. A median still near 7,743 means the flags are not reaching the child — investigate before claiming the change works.

- [ ] **Step 6: Verify no transcripts are being persisted**

```bash
find ~/.claude/projects -name "*.jsonl" -newermt "-30 minutes" | head
```
Expected: no files, or only files from your own interactive Claude Code sessions. Stubs named after the daemon's `claude -p` session ids would mean `--setting-sources ""` re-enabled session persistence after all (the risk the stale comment recorded on claude 2.1.156) — report it; it does not block, but the comment corrected in Task 3 Step 5 would need reverting.

- [ ] **Step 7: Report completion**

State, each with the evidence beside it:

- the suite result as counts, naming the one pre-existing failure explicitly — never "tests pass";
- `ruff` output;
- the live median `cache_write` and `cost_usd` versus arm A, marked **verified by execution**;
- the Task 5 divergence counts and what André concluded from reading them;
- the smoke verdicts;
- what stayed **assumed**: that no caller depended on skills, plugins or MCP being present in the child (nothing broke, but nothing tested it either); and that the schema-carrying callers — ingest, consolidator, session_watcher — were never measured, only the schema-less pair-judge path;
- what stayed **open**: memory content still reaches the model undelimited in the user message on all three providers (overview, "Known issue"), and `duplicate_merger.py:134` still indexes `content` with no NULL guard while `nodes.content` is nullable.

- [ ] **Step 8: Clean up the working directory only after André has the report**

```bash
ls -la ~/.cache/ormah-ab-20260819/
```
It holds production memory content. Delete it once the report is accepted:

```bash
rm -rf ~/.cache/ormah-ab-20260819/
```
Do **not** delete it earlier — the divergence list is the only record of what the change did to real judgments.

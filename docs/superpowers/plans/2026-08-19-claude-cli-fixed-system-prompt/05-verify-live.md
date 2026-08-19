# Task 5: Full verification + live measurement

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none modified. Restarts the daemon; reads `/tmp/ormah-dev.err`.

**Interfaces:**
- Consumes: a passing Task 4 gate (`GATE_EXIT=0`). Do not start this task otherwise — a `GATE_EXIT=2` is an invalid measurement, not a soft pass.
- Produces: the numbers reported back to André. No commits.

- [ ] **Step 1: Full suite — compared against the known-failing baseline, not against zero**

The repo has one deterministic pre-existing failure on `local-main` unrelated to this change (verified 2026-08-19 by isolated run). Demanding `exit 0` would make this gate fail for a reason this plan did not cause, and — worse — would tempt whoever runs it to wave the whole check through.

**The `FAILED` grep alone is not enough (council round 2, I7).** A run that aborts during
collection emits `ERROR`, not `FAILED`, so `failures.txt` comes out empty and "beyond baseline"
prints `(none)` — read as success when pytest never ran a thing. That is exactly the state Task 2
Step 2 creates on purpose (`ImportError: cannot import name '_SYSTEM_PROMPT'`). So assert the
summary line too: the suite must have COLLECTED and RUN a plausible number of tests.

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
make test > ~/.cache/ormah-eval-20260819/task5-test.log 2>&1; echo "MAKE_TEST_RC=$?"
BASELINE="tests/test_conflict_claims_investigation.py::test_forgetting_gate6_ignores_edge_type_contradicts_protects_like_supports"

# 1. The run must have completed and reported a passed-count at or above the known floor.
#    2627 passed on local-main at 2026-08-19; allow drift downward only to 2500.
PASSED=$(grep -oE '[0-9]+ passed' ~/.cache/ormah-eval-20260819/task5-test.log | tail -1 | grep -oE '^[0-9]+')
echo "PASSED=${PASSED:-0}"
if [ -z "$PASSED" ] || [ "$PASSED" -lt 2500 ]; then
  echo "STOP: pytest did not complete a full run (passed=${PASSED:-none}, expected >= 2500)."
  grep -E "^(ERROR|INTERNALERROR)" ~/.cache/ormah-eval-20260819/task5-test.log | head
fi

# 2. Collection errors are failures even though they never print a FAILED line.
ERRORS=$(grep -cE "^ERROR " ~/.cache/ormah-eval-20260819/task5-test.log)
echo "COLLECTION_ERRORS=$ERRORS"

# 3. Only now compare the failure set against the approved baseline.
grep -E "^FAILED " ~/.cache/ormah-eval-20260819/task5-test.log \
  | sed 's/^FAILED //; s/ - .*//' | sort -u > ~/.cache/ormah-eval-20260819/failures.txt
echo "--- all failures ---"; cat ~/.cache/ormah-eval-20260819/failures.txt
echo "--- failures beyond baseline ---"
grep -v -F "$BASELINE" ~/.cache/ormah-eval-20260819/failures.txt || echo "(none)"
```
Expected, and **all three** must hold: `PASSED >= 2500`, `COLLECTION_ERRORS=0`, and the "beyond
baseline" list printing `(none)`. Any test named in that list is a regression this change caused —
fix it before proceeding. If the baseline failure has *disappeared* (someone fixed it meanwhile),
that is fine: the check is "nothing beyond the baseline", not "exactly the baseline". A non-zero
`MAKE_TEST_RC` with `PASSED >= 2500`, `COLLECTION_ERRORS=0` and `(none)` beyond baseline is the
expected shape — `make test` exits non-zero on the baseline failure alone.

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: ruff clean. Any finding → fix before proceeding.

- [ ] **Step 3: Prove the daemon will serve the edited tree** (editable install check)

Run: `.venv/bin/python -c "import ormah; print(ormah.__file__)"`
Expected: a path inside `/Users/andre/Documents/GitHub/Tools/ormah/src/ormah/`. Anything else → STOP (the restart would not pick up the change).

- [ ] **Step 4: Record the auto_linker's current paused state, so the restart can restore it**

The `paused` flag lives only in memory and is lost on restart. Read it now rather than assuming — the daemon has been left paused in the past to suppress the boot-triggered run.

```bash
curl -s http://localhost:8787/admin/health | python3 -c "
import json,sys
jobs = json.load(sys.stdin)['jobs']
print('auto_linker entry:', json.dumps(jobs.get('auto_linker'), indent=2))"
curl -s http://localhost:8787/admin/tasks | head -c 2000
```
Write down whether `auto_linker` is currently paused. Step 7 restores exactly this state.

- [ ] **Step 5: Restart the daemon and wait for health**

```bash
launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev
until curl -sf http://localhost:8787/admin/health > /dev/null; do sleep 2; done; echo HEALTHY
```
Note: the restart schedules an `auto_linker` run at +5 min (`scheduler.py:71` passes `next_run_time=_staggered(5, ...)`, which governs the FIRST fire regardless of the configured interval). With the new prompt, that run IS the measurement — so do **not** re-pause before Step 6.

- [ ] **Step 6: Read the live usage lines**

Wait for the +5 min run to produce calls. If the backlog is empty and no lines appear by +10 min, force one:
`curl -s -X POST http://localhost:8787/admin/tasks/auto_linker/run`

```bash
grep "claude -p usage" /tmp/ormah-dev.err | tail -15
```
Expected: steady-state lines with `cache_write=` in the low hundreds (~110). **Ignore the first call after restart** — it legitimately writes the full prefix once. Baseline being replaced: `cache_write=7726` on every call.

Steady state above ~1000 → the prefix is still unstable. Report to André and reopen the investigation; do not paper over it.

- [ ] **Step 7: Restore the auto_linker to the state recorded in Step 4**

If Step 4 found it paused, re-pause it now that the measurement is done:
```bash
curl -s -X POST http://localhost:8787/admin/tasks/auto_linker/pause
```
If Step 4 found it running, do nothing. Either way, state what you did — this is live-system state, and leaving it different from how it was found is a silent side effect.

- [ ] **Step 8: Record the verification**

Reply in-session to André with, each as a measured number and not a projection:
- the Task 4 gate output: noise floor, before-vs-after agreement, negative control, `edge→none` rate, ingest smoke counts and injection result;
- steady-state `cache_write` and `cost_usd` per call read from the daemon log;
- the observed cost ratio against the `$0.0182 → $0.0061` projection, stating plainly if it differs;
- the `make test` "beyond baseline" list (expected `(none)`) and the `make lint` result.

No commit — nothing in the repo changed in this task.

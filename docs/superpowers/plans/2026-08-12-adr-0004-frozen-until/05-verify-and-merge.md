# Task 5: verify the whole change, then land it in the Beta

**Files:**
- Modify: none (verification and integration only)

**Interfaces:**
- Consumes: everything Tasks 1-4 produced.

---

- [ ] **Step 1: Run the full test suite, not just the watcher file**

Run: `python -m pytest tests/ -v`

Expected: all PASS. The default run excludes `integration`-marked tests
(`addopts = -m 'not integration'`), which is correct here — nothing in this change touches an
external boundary.

If anything outside `tests/test_background/` fails, stop and report it: this change is confined
to `session_watcher.py`, so a failure elsewhere means an assumption in the plan was wrong.

- [ ] **Step 2: Lint the whole tree**

Run: `ruff check src/ tests/`

Expected: `All checks passed!`

- [ ] **Step 3: Confirm no caller of the old name survives**

Run: `grep -rn "_mark_frozen_prefix_consumed" src/ tests/`

Expected: no output. The rename is complete only when the old symbol appears nowhere.

- [ ] **Step 4: Confirm the dead-letter behaviour is untouched**

Run: `git diff local-main -- src/ormah/background/ingest_spool.py`

Expected: no output. `ingest_spool.py` must not have changed — the noise (~110 dead-lettered
jobs/day) is out of scope for this plan by decision, and a diff there means the scope slipped.

- [ ] **Step 5: Read the whole diff once, deliberately**

Run: `git diff local-main -- src/`

Expected these hunks and no others:

1. `_mark_frozen_prefix_parked` — the renamed method with its new body.
2. `_idle_with_unsafe_tail` — returns `os.stat_result | None` instead of `bool`.
3. The `_run_job` call site that threads the examined stat into the park.
4. The new module-level `_frozen_unchanged`.
5. `reconcile` — `>=` becomes `==` on the fully-consumed arm, plus the new frozen arm.
6. `_enqueue_path` — the gate.
7. Two `pop` loops: the confirmed-shrink reset and the successful-ingest commit.

Anything else is scope creep and should be reverted before merging.

Hunk 5's `>=` → `==` is the one change that repairs **pre-existing** behaviour rather than
behaviour this plan introduced: a cursor above EOF meant "fully consumed", so a shrunk
transcript was dropped from the sweep and the shrink gate was reachable only through the
Observer. It is included because the frozen fact's contract claims that escape works. If a
tighter diff is wanted, this hunk and its test are the separable piece.

- [ ] **Step 6: Merge into the running Beta**

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git merge fix/adr-0004-frozen-until
```

The Beta serves this working tree, so the merge is what puts the change in front of real
traffic. Restart the server so the running process picks it up:

```bash
make restart
```

- [ ] **Step 7: Establish the production baseline for the verification claim**

The spec's production check is that the count of state entries holding only `end_offset` stops
rising. It is 75 today (was 48 on 2026-08-09). Record the count now, right after the restart:

```bash
python3 - <<'EOF'
import json
from pathlib import Path
n = 0
for w in [Path.home()/".claude/projects", Path.home()/".codex/sessions"]:
    sp = w / ".session_watcher_state"
    if not sp.exists():
        continue
    raw = json.loads(sp.read_text(encoding="utf-8"))
    for rel, e in (raw.get("files", raw)).items():
        if isinstance(e, dict) and tuple(sorted(e)) == ("end_offset",):
            n += 1
print("end_offset-only entries:", n)
EOF
```

Expected: `75`, or slightly higher if the defect fired again between writing this plan and the
merge. Write the number and the date into `SESSION_LOG.md`. Re-run it after a few days of
normal use: the count must be **flat**, and entries carrying `frozen_until` with an intact
cursor must have appeared.

This is the only claim in the plan that cannot be verified at merge time. Do not report the
change as verified in production until that second reading exists.

- [ ] **Step 8: Prune the worktree**

```bash
git worktree remove ../ormah-wt-frozen-until
```

The branch stays until the amendment below is written; the worktree does not.

- [ ] **Step 9: Amend ADR-0004**

The ADR must describe what is merged. Write an amendment recording:

1. What shipped (the suppression fact, both gates, the shrink clear) and the commits.
2. **The errata the measurement of 2026-08-12 produced**, which the ADR does not yet carry: its
   own 2026-08-12 amendment names two dead-letters and cites two jobs (`boundary=796621`,
   `boundary=379845`) that do not exist in the spool; the real figures are 3806 jobs over 1619
   transcripts, payloads from 2026-07-24 onward, and `failed/` was never wiped on 2026-08-11.
3. That the two defects the 2026-08-11 amendment describes as open were already fixed and
   committed — `8438242` (backoff exponent clamp) and `9882872` (`IngestResult.GONE` →
   `transcript_deleted`) — with 8 dead-letters of the new class in the spool as evidence.
4. What remains open, each on its own evidence: recovery of the 14 transcripts / 5.92 MB the
   parser can close, the dead-letter noise (Fix A), and the 54 transcripts the parser closes
   nothing in even unwindowed.

Commit it separately from the code, on `local-main`.

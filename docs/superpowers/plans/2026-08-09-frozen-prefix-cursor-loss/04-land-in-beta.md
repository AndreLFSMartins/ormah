# Task 4: Land it in the Beta

Read `00-overview.md` first. Tasks 1-3 must be committed and green.

**Files:** none — integration only.

**This task touches the live server.** Re-read the Global Constraints in the overview before starting, especially Golden rule 1.

- [ ] **Step 1: Full test suite from the worktree**

```bash
cd ../ormah-wt-frozen-prefix && python -m pytest tests/ -q
```

Expected: green. **Report the exact tail of the output — the counts, not a paraphrase.** If anything fails, stop here; nothing reaches the Beta on a red suite.

Note: the default run excludes `integration`-marked tests (`addopts = -m 'not integration'`). That is the project's normal gate and is what this plan requires.

- [ ] **Step 2: `/council-pr` gate — mandatory, do not skip**

`INSTRUCTIONS.md:15` — *"Merge to main only via `/council-pr`."* Revision 1 of this plan
omitted this step and Codex caught it in council round 1.

Push the branch to `fork` (never `upstream`) and run the gate:

```bash
git -C ../ormah-wt-frozen-prefix push fork fix/frozen-prefix-cursor-loss
```

Then invoke `/council-pr`. **Do not proceed to Step 3 until it approves.** If it returns
findings, stop and report them — do not merge past a no-ship.

- [ ] **Step 3: Merge into `local-main` without switching the Beta's branch**

The Beta's working tree is already ON `local-main`, so this merges in place — no `checkout` is involved, and Golden rule 1 holds:

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah merge fix/frozen-prefix-cursor-loss
```

Confirm the branch did not change:

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah branch --show-current
```

Expected: `local-main`.

- [ ] **Step 4: Restart the Beta and confirm it came up**

The merge changed the code the live server is running. Restart it:

```bash
launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8787/health
```

Expected: `200`. If the health check fails, check `/tmp/ormah-dev.err` for the traceback and report it.

- [ ] **Step 5: Baseline the orphan set**

```bash
python3 -c "
import json
from pathlib import Path
n = a = 0
for sf in sorted(set(Path.home().rglob('.session_watcher_state'))):
    for rel, e in json.loads(sf.read_text()).items():
        if isinstance(e, dict) and frozenset(e) == {'end_offset'}:
            n += 1
            a += (sf.parent / rel).exists()
print(f'only-end_offset entries: {n}  alive: {a}')
"
```

Record the number. The reference point is **49 entries / 20 alive at 13:06 on 2026-08-09**.

**The count will not go DOWN** — this plan does not repair existing entries, and saying otherwise would be false. What it must do is **stop going UP**.

- [ ] **Step 6: Re-check after the Beta has been running**

Run the same command again after the server has processed real traffic for a while (an hour is enough; the reference period produced 4 new entries in roughly 10 minutes under the pre-fix code).

A rise means the fix is incomplete. **Report it rather than patching further** — a second fix layered on an unverified first is exactly the cascade this whole effort exists to avoid.

- [ ] **Step 7: Prune the worktree, keep the branch**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah worktree remove ../ormah-wt-frozen-prefix
```

**Do not delete the branch.** It is the unit of any future upstream submission alongside ADR-0004 slice 1.

## What remains open after this task

State these plainly when reporting completion; none of them are fixed by this plan:

- The 24 orphaned entries still hold advanced cursors. Repairing them writes to production state and needs its own session, backup, and approval.
- The Codex parser defect: 4 rollout files, 1.62 MB, `safe_end_offset=0` on whole files, all with cursors at EOF.
- The ADR-0004 document still carries the retracted 2026-07-28 amendment. Updating it to describe what is now merged is separate work.

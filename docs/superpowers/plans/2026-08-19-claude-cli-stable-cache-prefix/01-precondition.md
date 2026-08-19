# Task 1: Close the hot-reload precondition

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none. This task changes no code and produces no commit. It changes machine state and records evidence.

**Interfaces:**
- Consumes: nothing.
- Produces: `~/.cache/ormah-ab-20260819/precondition.txt` — the recorded evidence that the window is safe. Task 6 restores what this task stops.

**Why this is a task and not a note.** The spec's round-2 predecessor asserted this tree "does NOT hot-reload", citing `cli.py:158` as `reload=False`. That citation is wrong: `cli.py:158` is `reload=args.reload`, and `make server` runs `python -m ormah.main`, which is `reload=True` (`main.py:452`). The live daemon happens to have started without `--reload`, so safety today rests on a launch-flag accident. During this work an unvalidated adapter reaching the running daemon would let `duplicate_merger` **merge memories irreversibly**.

Two independent protections, because the first is procedural and the second is not:

1. Stop the daemon for the edit window — removes the process that could pick up a half-finished adapter.
2. Take a backup first — turns an irreversible merge into a recoverable one if anything slips through anyway.

- [ ] **Step 1: Create the working directory (outside the repo — it will hold production memory content)**

```bash
mkdir -p ~/.cache/ormah-ab-20260819
```

- [ ] **Step 2: Take a backup BEFORE touching anything**

```bash
.venv/bin/ormah backup create
.venv/bin/ormah backup list | head -5
```
Expected: `backup list` names a backup created just now. If `backup create` fails, STOP and report — do not proceed to Task 2 without a recoverable snapshot.

- [ ] **Step 3: Record the daemon's current launch flags, then stop it**

```bash
{
  echo "=== daemon before stop ==="
  ps -o pid=,command= -p "$(pgrep -f 'ormah server start' | head -1)" 2>/dev/null || echo "(no ormah server process)"
  echo "=== server status ==="
  .venv/bin/ormah server status
} | tee ~/.cache/ormah-ab-20260819/precondition.txt
```
Expected: the recorded command line contains `ormah server start` and **no** `--reload`. If it does contain `--reload`, say so in the report — the window was already unsafe and the backup in Step 2 is the only thing that stood between an edit and a merge.

```bash
.venv/bin/ormah server stop
.venv/bin/ormah server status
```
Expected: `server status` now reports not running.

- [ ] **Step 4: Verify no `claude -p` child survives from a background job**

```bash
pgrep -fl 'claude -p' || echo "clean: no claude -p children"
```
Expected: `clean: no claude -p children`. If any are listed, wait for them to finish rather than killing them — a killed `duplicate_merger` call can leave a half-applied merge.

- [ ] **Step 5: Append the closing evidence to the record**

```bash
{
  echo "=== after stop ==="
  .venv/bin/ormah server status
  echo "=== claude children ==="
  pgrep -fl 'claude -p' || echo "none"
  echo "=== backup ==="
  .venv/bin/ormah backup list | head -3
} >> ~/.cache/ormah-ab-20260819/precondition.txt
cat ~/.cache/ormah-ab-20260819/precondition.txt
```
Expected: the file shows a stopped server, no `claude -p` children, and a fresh backup.

**Do not commit anything in this task.** `~/.cache/ormah-ab-20260819/` is outside the repo on purpose.

**Report to André before moving on:** whether the daemon had `--reload`, that it is now stopped, and the backup name. The Ormah daemon stays down until Task 6 — whispers and `remember` will not work in the meantime, and that is the accepted cost of the window.

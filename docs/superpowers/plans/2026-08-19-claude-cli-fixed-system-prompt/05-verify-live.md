# Task 5: Full verification + live measurement

> Part of the plan in [00-overview.md](00-overview.md) — read the overview's Global Constraints before executing.

**Files:** none modified. Restarts the daemon; reads `/tmp/ormah-dev.err`.

- [ ] **Step 1: Full suite + lint**

Run: `make test` then `make lint`
Expected: pytest exit 0; ruff clean. Any failure → fix before proceeding.

- [ ] **Step 2: Prove the daemon will serve the edited tree** (editable install check)

Run: `.venv/bin/python -c "import ormah; print(ormah.__file__)"`
Expected: a path inside `/Users/andre/Documents/GitHub/Tools/ormah/src/ormah/`. Anything else → STOP (the restart would not pick up the change).

- [ ] **Step 3: Restart the daemon and wait for health**

```bash
launchctl kickstart -k gui/$(id -u)/com.ormah.server.dev
until curl -sf http://localhost:8787/admin/health > /dev/null; do sleep 2; done; echo HEALTHY
```
Note: the restart schedules an `auto_linker` run at +5 min (scheduler.py:71) — with the new prompt, that run IS the measurement. Backlog may be small; that only shortens it.

- [ ] **Step 4: Read the live usage lines** (wait for the +5 min run to produce calls; if the backlog is empty and no lines appear by +10 min, force one: `curl -s -X POST http://localhost:8787/admin/tasks/auto_linker/run`)

```bash
grep "claude -p usage" /tmp/ormah-dev.err | tail -15
```
Expected: steady-state lines with `cache_write=` in the low hundreds (~110; the FIRST call after restart legitimately writes the full prefix, ignore it). Baseline being replaced: `cache_write=7726` every call. Steady state above ~1000 → the prefix is still unstable: reopen the investigation, report to André.

- [ ] **Step 5: Record the verification** — reply in-session to André with: gate agreement numbers, steady-state `cache_write`, and cost/call from the log lines. No commit (nothing in the repo changed in this task).

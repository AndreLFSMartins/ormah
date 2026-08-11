# Task 4: Ship to the fork and run it in the Beta

**Files:** none modified — delivery only.

**Interfaces:**
- Consumes: the verified commits from Tasks 1-3.
- Produces: a branch on `fork` ready for a PR, and a Beta running the fix, verified live.

**Prerequisite:** Task 3 passed, including the 20-run repetition.

- [ ] **Step 1: Push the branch to the fork**

From the worktree:

```bash
git push fork fix/index-updater-lock-order
```

Never push to `upstream` (FORK-WORKFLOW.md Golden rule 3). The PR itself is a separate decision —
`/council-pr` opens it (base `r-spade:main`, head `fork:fix/index-updater-lock-order`). Do not open
it without asking; the defect is upstream's, so the PR is worth proposing, but it is André's call.

- [ ] **Step 2: Merge into local-main so the Beta runs it (Recipe B)**

Run from the main working tree, **not** the worktree:

```bash
cd /Users/andre/Documents/GitHub/Tools/ormah
git merge fix/index-updater-lock-order
```

`local-main` is already the checked-out branch there, so no branch swap of the live tree occurs —
Golden rule 1 is respected. Do **not** `git checkout` anything in this directory.

- [ ] **Step 3: Restart the server via launchd**

The server is run by the launch agent `com.ormah.server.dev`, which was **booted out** during
diagnosis (it has KeepAlive and resurrected the process on every kill, so stopping it required
unloading the agent). Bring it back:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.ormah.server.dev.plist
sleep 15
launchctl list | grep com.ormah.server.dev
lsof -nP -iTCP:8787 -sTCP:LISTEN | tail -2
```

Expected: the agent listed with a live PID, and one listener on 127.0.0.1:8787.

**Do not** start it with `nohup .venv/bin/ormah server start &`. That yields a process the agent does
not own, and re-bootstrapping later would leave two servers on one database.

Known defect, out of scope here: `ormah server stop` prints `No launchd agent installed` even though
the agent is installed and loaded — its detection is broken. Do not trust that message.

- [ ] **Step 4: Prove writes survive past the old failure window**

The deadlock used to appear ~2 minutes in, so probe for twice that:

```bash
python3 -c "
import sqlite3, time
p='/Users/andre/.local/share/ormah/memory/index.db'
start=time.time()
while time.time()-start < 240:
    c=sqlite3.connect(p,timeout=5); t=time.time()
    try:
        c.execute('BEGIN IMMEDIATE'); print(f'[{time.time()-start:5.0f}s] write OK'); c.execute('ROLLBACK')
    except Exception as e:
        print(f'[{time.time()-start:5.0f}s] BLOCKED: {e}'); c.close(); raise SystemExit(1)
    c.close(); time.sleep(20)
print('4 minutes with no write block')
"
```

Expected: `write OK` on every probe, ending with `4 minutes with no write block`. A single `BLOCKED`
means the fix is incomplete — return to diagnosis, do not paper over it.

- [ ] **Step 5: Confirm the endpoints that were dead**

```bash
curl -s -m 30 -X POST http://localhost:8787/agent/whisper -H 'Content-Type: application/json' \
  -d '{"prompt":"test after lock-order fix","space":"ormah","agent_id":"verify"}' \
  -w "\n[http %{http_code} in %{time_total}s]\n" | tail -3

curl -s -m 30 -X POST http://localhost:8787/agent/recall -H 'Content-Type: application/json' \
  -d '{"query":"ormah server","space":"ormah","limit":2}' \
  -w "\n[http %{http_code} in %{time_total}s]\n" | tail -3
```

Expected: HTTP 200 on both. Latency around ~1 s for whisper is expected and is **not** a failure of
this fix — that is the separate structural issue left out of scope (the parse loop still runs inside
the transaction).

- [ ] **Step 6: Confirm the background jobs now complete**

```bash
grep -E "Index updater|Auto-linker" ~/.local/share/ormah/logs/ormah.log | tail -12
```

Expected: each `Running job "Index updater"` is followed by `executed successfully`. Recurring
`maximum number of running instances reached (1)` means a job is still hanging — the fix did not take.

- [ ] **Step 7: Clean up the worktree**

Only after the Beta is verified healthy, and only if no PR review is pending on it:

```bash
git worktree remove ../ormah-wt-index-lock
```

Keep the branch itself — pruning rules are in FORK-WORKFLOW.md Recipe D, and a branch whose PR is
open must not be deleted on `fork`.

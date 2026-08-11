# Task 7 — Runtime verification, PR sweep, memories, cleanup

**Where:** `/Users/andre/Documents/GitHub/Tools/ormah` + gh. Closes the sync.

- [ ] **Step 1: Functional runtime checks (not just "PID alive")**

```bash
curl -sf -o /dev/null -w 'root: %{http_code}\n' http://localhost:8787/
curl -sf -o /dev/null -w 'admin: %{http_code}\n' http://localhost:8787/admin
/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ormah --version
```

Expected: both `200`; version reports the 0.13.5-based build (exact string: check `pyproject.toml` post-merge). Then check the server log for a clean boot (no pydantic/config errors, session_watcher started):

```bash
plutil -p ~/Library/LaunchAgents/com.ormah.server.plist | grep -iE 'stdout|stderr'
# tail the path(s) it prints — look for startup errors
```

- [ ] **Step 1b (I3): UI bundle freshness smoke**

HTTP 200 alone does not prove the served bundle matches the 0.13.5 backend (a stale `ui_dist` would still 200). Confirm the served asset is the one built in Task 6 Step 5:

```bash
# The index references a hashed asset bundle; confirm it resolves and matches what's on disk.
ASSET=$(curl -sf http://localhost:8787/ | grep -oE '/assets/[A-Za-z0-9._-]+\.js' | head -1)
echo "served asset: $ASSET"
curl -sf -o /dev/null -w 'asset: %{http_code}\n' "http://localhost:8787$ASSET"
ls -la /Users/andre/Documents/GitHub/Tools/ormah/src/ormah/ui_dist/assets 2>/dev/null | head
```

Gate: the served asset path 200s and its filename exists under `ui_dist/assets` with a build timestamp from Task 6. If the galaxy/graph view is a `beta-keep` feature, load `/` in a browser once and confirm it renders (the strongest check).

- [ ] **Step 2: MCP/whisper functional check**

`ormah` CLI surface may have changed across releases — run `/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ormah --help` first, then exercise a recall/status command it offers. Success = a real answer from the store, no provider/validation errors. (In a fresh Claude session, the ormah MCP handshake succeeding is the same signal.)

- [ ] **Step 3: PR mergeable sweep**

```bash
for n in 31 38 57 60 68 79 92; do \
  echo "#$n: $(gh pr view $n --repo r-spade/ormah --json mergeable --jq .mergeable)"; done
# + the new #87 PR number from delta-manifest ## new-tips
```

Expected: all `MERGEABLE`. Any `CONFLICTING` → that rebase missed something upstream — reopen its task.

- [ ] **Step 4: Cleanup temp refs (keep backup tags ≥ 1 week)**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && for r in pr31 pr38 pr57 pr60 pr68 pr79 pr87 pr90 beta-sync; do \
    git update-ref -d refs/tmp/$r 2>/dev/null; done; git for-each-ref refs/tmp )
git -C /Users/andre/Documents/GitHub/ormah-dev update-ref -d refs/tmp/beta-local
```

Expected: `refs/tmp` empty in both clones. Do NOT delete `backup/*` tags now. Fork branch `fix/ingest-stability-hardening` (stale duplicate of pr79 @ a15bcad): delete only after #79 merges upstream — note it as a follow-up, don't delete today.

- [ ] **Step 5: Update memories (both systems)**

- ormah MCP: update the PR-#79 state memory (new tip, hardening folded in); `mark_outdated` on node `8bd0cc8f` (sync-debt — resolved); new memory: "Beta synced with upstream 0.13.5 on 2026-07-10: strategy (a), all PRs rebased+mergeable, assembly merged into local-main, runtime verified".
- File memory (`~/.claude/projects/-Users-andre-Documents-GitHub-Tools-ormah/memory/`): update `ormah-pr79-claude-cli-parity-state.md` and the stability/sync entries in `MEMORY.md` to the post-sync state.

- [ ] **Step 6: Close the session**

- Follow-ups to record (not tasks of this plan): plist-move + cap calibration (pr79 memory); monitor r-spade reviews on the 8 PRs; sync cadence = re-sync Beta at every upstream release (handoff lesson); delete stale fork branch after #79 merges.
- André runs `/session-close` (council) to log the session.

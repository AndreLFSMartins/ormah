# Task 6 — Stage the assembly, validate, then promote into the Beta (`local-main`)

**Where:** `/Users/andre/Documents/GitHub/Tools/ormah` (the live runtime — handle with care). Council-driven change: the assembly lands first on a **staging branch `local-main-next`**, is fully validated there (data backup, UI build, suite, `/council-pr`, content check), and only then is `local-main` fast-forwarded to it. The live runtime branch is never merged into directly, so rollback is instant.

Precondition: Task 5 green + `beta-keep-audit.txt` has zero unexplained drops (C1). **CHECKPOINT before starting:** André go/no-go.

- [ ] **Step 1 (C2): Back up the data store BEFORE any new code touches it**

Releases 0.13.3–0.13.5 carry automatic store/index migrations. `git reset` reverts code, NOT a migrated SQLite/markdown store. Back it up and prove the copy is readable.

```bash
DATA=$(/Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/ormah paths 2>/dev/null | awk '/data|store|db/{print $NF; exit}')
# Fallback if `ormah paths` doesn't exist: default is ~/.config/ormah or ~/.local/share/ormah — confirm from src/ormah/config.py before proceeding.
BK=~/ormah-store-backup-20260710
cp -a "$DATA" "$BK"
du -sh "$DATA" "$BK"
# Prove the backup opens (sqlite integrity) — adjust the *.db path to the real store file:
find "$BK" -name '*.db' -exec sh -c 'echo "== {} =="; sqlite3 "{}" "PRAGMA integrity_check;" | head -1' \;
```

Gate: backup exists, same size as source, `integrity_check` = `ok`. Do NOT continue until confirmed. Record `$DATA` and `$BK` in `delta-manifest.md`.

- [ ] **Step 2: Stop the runtime + clean-tree + backup tag**

```bash
launchctl bootout gui/501/com.ormah.server
sleep 2; lsof -nP -iTCP:8787 -sTCP:LISTEN || echo "port 8787 free"
git -C /Users/andre/Documents/GitHub/Tools/ormah status --porcelain
git -C /Users/andre/Documents/GitHub/Tools/ormah tag backup/local-main-pre-sync-20260710 local-main
```

Expected: `port 8787 free`; only untracked files (docs/, CONTEXT.md, SESSION_LOG.md) — NO modified tracked files. Modified tracked files → stash/resolve first.

- [ ] **Step 3: Create the staging branch + dry-run the merge**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah fetch /Users/andre/Documents/GitHub/ormah-dev \
  'refs/heads/integration/beta-sync-20260710:refs/tmp/beta-sync'
git -C /Users/andre/Documents/GitHub/Tools/ormah branch -f local-main-next local-main
git -C /Users/andre/Documents/GitHub/Tools/ormah merge-tree --write-tree local-main-next refs/tmp/beta-sync \
  > /tmp/merge-preview.txt; grep -A200 '^$' /tmp/merge-preview.txt | head -80
```

Review the conflict list. Any conflicted file NOT explained by a `## beta-keep` commit → understand why before merging.

- [ ] **Step 4: Merge into the STAGING branch (never into local-main directly)**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && git checkout local-main-next && git merge --no-ff refs/tmp/beta-sync )
```

Resolution authority per conflicted file:
- No `beta-keep` commit touches it → take the assembly side: `git checkout --theirs <file> && git add <file>`.
- A `beta-keep` commit touches it → manual combine: assembly skeleton + the beta-keep change on top.
Commit message: `merge: sync Beta with upstream 0.13.5 + rebased PRs (#31 #38 #57 #60 #68 #79 #87 #92)`.

- [ ] **Step 5 (I3): Refresh deps AND rebuild the UI bundle**

`make install` runs pip + `npm install` but does NOT populate `src/ormah/ui_dist` (served by launchd). Build it explicitly so the backend and the served bundle match.

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && .venv/bin/pip install -q -e ".[dev]" && make install \
  && ( cd ui && npm run build ) )
ls -la /Users/andre/Documents/GitHub/Tools/ormah/src/ormah/ui_dist | head
```

If `ui/package.json` has no `build` script or the target differs, read the Makefile `ui-build`/`restart` targets and use the documented one — do not guess. Expected: `ui_dist` timestamps updated to now.

- [ ] **Step 6: Suite gate on staging (Beta baseline)**

```bash
P=/Users/andre/Documents/GitHub/Tools/ormah/docs/superpowers/plans/2026-07-10-beta-upstream-sync
( cd /Users/andre/Documents/GitHub/Tools/ormah && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
  .venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | grep -E '^FAILED' | sort > /tmp/staging-fail.txt )
comm -23 /tmp/staging-fail.txt <(sort $P/beta-baseline-failures.txt $P/baseline-failures.txt | uniq) > /tmp/staging-new-fail.txt
if [ -s /tmp/staging-new-fail.txt ]; then echo "NEW FAILURES:"; cat /tmp/staging-new-fail.txt; else echo "GATE PASS"; fi
```

Gate: `/tmp/staging-new-fail.txt` empty. New failure unresolvable today → staging branch is discardable: `git checkout local-main`, restart runtime (Step 9), report. `local-main` was never touched.

- [ ] **Step 6b (M1): Run the `claude_cli` integration test once on the staged tree**

The only gate that exercises the real `claude -p` subprocess (excluded from default runs). Requires `claude` on PATH.

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && ORMAH_LLM_PROVIDER=none ORMAH_INGEST_LLM_PROVIDER=none \
  .venv/bin/python -m pytest tests/ -q -m integration -k claude --tb=short 2>&1 | tail -8 )
```

Gate: the real-extraction test passes (or is explicitly skipped for a documented reason, e.g. `claude` not installed on this machine — then note it as unverified, don't silently pass).

- [ ] **Step 7 (C1): Content-preservation re-check on the staged tree**

```bash
D=/Users/andre/Documents/GitHub/ormah-dev
git -C /Users/andre/Documents/GitHub/Tools/ormah diff --stat backup/local-main-pre-sync-20260710 local-main-next -- \
  src/ormah/transcript src/ormah/engine src/ormah/background src/ormah/index src/ormah/config.py src/ormah/ui_dist ui/ | tail -40
```

Confirm the staged tree differs from the old Beta ONLY by intended upstream/PR changes — no `beta-keep` feature (galaxy UI, council-managed files, local config) silently reverted. Cross-check against `beta-keep-audit.txt` (Task 5 Step 5).

- [ ] **Step 8 (I1): MANDATORY `/council-pr` on the staged branch before promotion**

INSTRUCTIONS rule 3: merges to `local-main` go through `/council-pr`. This is a blocking gate, not optional. André runs:

```
/council-pr   # reviewing local-main-next → local-main (the sync merge + manual conflict resolutions)
```

Gate: `/council-pr` returns no unresolved criticals AND André explicitly approves promotion. Findings → fix on `local-main-next`, re-run Steps 6–7, re-review. Do NOT run Step 9 until this passes.

- [ ] **Step 9: Promote staging → `local-main` and restart**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah && git checkout local-main && git merge --ff-only local-main-next )
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.ormah.server.plist
sleep 3; curl -sf -o /dev/null -w '%{http_code}\n' http://localhost:8787/
```

Expected: fast-forward succeeds (local-main-next was built on top of local-main, so ff-only is clean); HTTP `200`. The plist owns port 8787 (memory: ormah-dev-run-setup) — bootstrap is the primary restart path; use `make restart` only if the Makefile documents it for the booted-out case. Full functional verification is Task 7.

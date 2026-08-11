# Task 3: Verification, quarantine audit, Beta merge

**Files:** none — runs the gates and integrates.

**Interfaces:**
- Consumes: Tasks 1-2, committed on the worktree branch.
- Produces: green suite + lint, an audit proving no healthy data was quarantined, and
  `local-main` carrying the change.

- [ ] **Step 1: Full suite + lint (cite the output)**

```bash
python -m pytest tests/ -v
ruff check src/ tests/
```

Expected: 0 failures beyond the KNOWN environmental set. Paste the tail
(`N passed, M failed`). The suite must include all six new cases from Task 2:

```bash
python -m pytest tests/test_background/test_session_watcher.py -v -k \
  "timeout_during_outage or cancelled_extraction or big_slice_shrinks or \
   quarantine_only_at_shrink_floor or one_success_authorizes or call_failed_still"
```

A vacuous pass is the real risk here: if the fixtures produce a slice smaller than
`MIN_SLICE_BYTES`, the floor branch is never exercised and
`test_quarantine_only_at_shrink_floor` passes without testing anything. Confirm
`result.capped` is actually true in that test before trusting it.

- [ ] **Step 2: Audit the live quarantine trail BEFORE and AFTER**

This slice's whole risk is dropping real data, so measure it rather than assume:

```bash
# before merging, snapshot the existing quarantine records
python3 -c "
import json, pathlib
for p in pathlib.Path.home().glob('.claude/projects/**/.session_watcher_state'):
    st = json.loads(p.read_text())
    for rel, e in st.items():
        for s in e.get('skipped_slices', []):
            print(p.parent.name, rel, s['start'], s['end'], s['reason'])
" | tee /tmp/quarantine-before.txt | wc -l
```

Re-run the same command a few days after the Beta merge. Every NEW entry must have
`reason == "extract_timeout_x3"` only where the transcript genuinely could not be
extracted at the floor slice size — spot-check at least one by replaying its byte range
manually. A rise in quarantines right after the merge means the health gate or the shrink
ladder is mis-tuned; roll back rather than let it keep dropping data.

- [ ] **Step 3: Merge into the Beta (`local-main`)**

```bash
git -C /Users/andre/Documents/GitHub/Tools/ormah status --porcelain
git -C /Users/andre/Documents/GitHub/Tools/ormah merge <worktree-branch>   # already on local-main; do NOT switch branches
launchctl kickstart -k gui/501/com.ormah.server.dev
curl -s http://localhost:8787/admin/health    # NOT /health — SPA catch-all returns HTML 200
```

- [ ] **Step 4: Review + close the loop**

- Run `/council-pr` on the worktree branch before merging.
- Update the ADR written as this slice's prerequisite (see `00-overview.md` → BLOCKED):
  mark it implemented, and record the accepted limitations — (i) a single oversized turn
  cannot be shrunk and is still eventually quarantined; (ii) only `claude_cli` raises the
  signal; (iii) `_LAST_EXTRACT_OK` is in-memory, so a restart resets the bracket and makes
  quarantine slower, never lossier.
- Also amend `docs/adr/0004-async-ingest-nudge-server-cursor.md` so its original sentence
  ("a `TimeoutExpired` … counts toward the per-slice cap and quarantines after N") points
  at the new ADR — as written it describes behaviour the review showed loses data during an
  outage.
- Report: suite output, the quarantine audit delta, and the spot-checked replay.

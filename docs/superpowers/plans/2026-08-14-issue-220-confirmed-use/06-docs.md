# Task 6: Correct the three upstream docs the change falsifies

**Files:**
- Modify: `docs/01 - Data Model.md:33`
- Modify: `docs/04 - Whisper - Involuntary Recall.md:101`
- Modify: `docs/05 - Background Jobs.md:152`

**Interfaces:**
- Consumes: the finished behaviour from Tasks 2–5.
- Produces: nothing consumed by other tasks.

These three are **upstream** docs and ship with the PR. The `pre-push` hook's `PROTECTED` regex is a prefix allowlist covering `docs/adr/`, `docs/runbooks/`, `docs/superpowers/`, `docs/handoffs/`, the dated `docs/<topic>-` prefixes, `docs/flows.md`, `docs/ingest-deferred-tracks.md` and `docs/*.html` — the numbered guides are not in it. `FORK-WORKFLOW.md` says "everything under `docs/`", which is broader than the regex actually is; the hook's own header comment acknowledges the discrepancy.

There is no test cycle here. The verification is that no sentence in the repo still describes the old behaviour.

- [ ] **Step 1: Correct the importance/decay claim**

`docs/05 - Background Jobs.md:152` currently reads:

```markdown
This score is not static. Recall and search hits update `access_count`, `last_accessed`, `last_review`, and `stability`, so a memory's importance changes over time as it is used, connected, or left untouched.
```

Replace with:

```markdown
This score is not static. Confirmed use updates `access_count`, `last_accessed`, `last_review`, and `stability`, so a memory's importance changes over time as it is used, connected, or left untouched. Confirmed use means a deliberate `recall_node(id)` or source-qualified positive feedback — appearing in a search result set, a whisper, or the UI does not count, and does not change any of those fields.
```

This is the load-bearing correction: the sentence sits directly above the importance formula, and it is what made surfacing look like a legitimate input to importance.

- [ ] **Step 2: Correct the whisper settings list**

`docs/04 - Whisper - Involuntary Recall.md:101` currently reads:

```markdown
- `touch_access = False`
```

Delete that line entirely. The parameter no longer exists, and whisper no longer needs to opt out of anything. The two bullets around it (`limit = ...` and `tiers = [core, working]`) stay.

- [ ] **Step 3: Correct the field description**

`docs/01 - Data Model.md:33` currently reads:

```markdown
access_count: int           # Times this node has been accessed/recalled
```

Replace with:

```markdown
access_count: int           # Times this node was confirmed used (not times surfaced)
```

Keep the column alignment of the surrounding comment block.

- [ ] **Step 4: Verify nothing else in the repo still claims the old behaviour**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  grep -rn "touch_access" docs/ ; \
  grep -rni "search hits update\|recalled\b" "docs/01 - Data Model.md" "docs/05 - Background Jobs.md" )
```

Expected: the first grep prints nothing. The second may print unrelated prose — read each hit and confirm none of them states that surfacing writes lifecycle fields.

- [ ] **Step 5: Commit**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  git add "docs/01 - Data Model.md" "docs/04 - Whisper - Involuntary Recall.md" \
          "docs/05 - Background Jobs.md" && \
  git commit -m "docs: describe access_count as confirmed use, not as surfacing

Three statements became false with #220: that search hits update the lifecycle
fields, that whisper passes touch_access=False (the parameter is gone), and that
access_count counts recalls rather than confirmed uses.

Refs #220" )
```

- [ ] **Step 6: Final gate before the PR**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && \
  python -m pytest tests/ -q 2>&1 | tail -5 && ruff check src/ tests/ && \
  git log --oneline upstream/main..HEAD )
```

Expected: the suite matches the Task 1 baseline with no added failures, ruff passes, and exactly five commits (Tasks 2–6) on top of `upstream/main`.

- [ ] **Step 7: Push the branch — but do not open the PR yet**

```bash
( cd /Users/andre/Documents/GitHub/Tools/ormah-wt-220 && git push fork fix/220-confirmed-use )
```

The `pre-push` hook is fail-closed and will reject the push if any local-only path slipped in. If it fires, that is the hook doing its job — find the offending commit rather than reaching for `--no-verify`.

**Do not run `/council-pr` or `gh pr create` until draft PR [#229](https://github.com/r-spade/ormah/pull/229) is closed or its `Closes #220–#223` lines are dropped.** It is still OPEN as of 2026-08-14 and would auto-close all four issues on merge. This was raised at [#229#issuecomment-5296007628](https://github.com/r-spade/ormah/pull/229#issuecomment-5296007628); check for a reply before proceeding.

When the PR is opened, its body should carry two notes a reviewer will otherwise ask about:

- *UI search does not log retrieval events — it did not before this change either.* Tracked as [#231](https://github.com/r-spade/ormah/issues/231).
- *`FileStore.touch_access` (`src/ormah/store/file_store.py:202`) is pre-existing dead code with no production callers. It shares a name with the engine helper this PR renamed and is deliberately left alone.*

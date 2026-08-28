# Issue #272 — deferred findings

Findings that survived review but were deliberately **not** fixed before merge. Every one was raised
by a per-task reviewer or by the final whole-branch review, and every one carries an explicit triage.

**Scope of the line numbers below:** they are measured against `fix/272-heuristic-confirmed-use`
at `e975a90` (worktree `../ormah-wt-272`), **not** against `local-main` and **not** against
`upstream/main`. None of this code exists upstream yet — `reinforcement_retry.py`,
`signal_strength.py` and the `state` column are all absent from `upstream/main` (verified with
`git cat-file -e upstream/main:<path>`). That is why these are recorded here rather than as an
upstream issue: per `FORK-WORKFLOW.md`, a claim quoted upstream must first be proven to exist there.

**When #272 merges upstream, this file becomes the source for the follow-up issue** — at that point
the paths resolve upstream and the findings can be quoted there.

Full execution context, including the six defective fixtures found along the way and what stayed
assumed, is in the SDD ledger `.superpowers/sdd/progress.md` (git-ignored scratch — this file exists
precisely because that one does not survive `git clean -fdx`).

---

## The two that are decisions, not cleanup

### M6 — the boot backfill is unbounded where the sweeper is batched

`src/ormah/engine/memory_engine.py:277` — `_migrate_heuristic_confirmed_use` does `.fetchall()` over
every heuristic signal above the cutoff and reinforces each eligible one inline in `startup()`, one
markdown write apiece, with no `LIMIT`. The sweeper next door deliberately caps at
`_BATCH_SIZE = 200` (`src/ormah/background/reinforcement_retry.py:31`) for exactly that reason.

**Triage: deferred.** It matches `_migrate_signal_strength` (same file, `:243-246`), which is equally
unbounded — so this is house style, not a new hazard introduced by #272. The measured volume is
**42 rows** on the store sampled 2026-08-26 (29 `node_id`, 13 `sentence`, 0 `title`, out of 1,629 —
the 1,587 `token_overlap` rows are correctly skipped). Paginating a boot migration is the riskiest
change available on this branch: it runs before the server serves and touches every existing store
on PyPI.

**Revisit if:** the eligible-row count on a real store grows past the low hundreds, or first-boot
time after upgrade becomes a complaint. Neither has been measured on a large store — see "assumed"
below.

### M8 — a systematically failing sweeper reports green in the admin job status

`src/ormah/background/reinforcement_retry.py:99` — the top-level `except Exception` swallows
everything, so `tracked()` never calls `record_failure` and the job shows as healthy no matter how
consistently it fails.

**Triage: deferred.** `decay_manager.py:85` and `auto_cluster.py:68` do the same thing, so fixing
only this job would leave one job reporting failure and two reporting green — which misleads whoever
reads the admin page more than three jobs being consistently wrong. The correct fix is all three at
once, which is a different scope.

**Worth noting it is not cosmetic:** `CLAUDE.md` documents this exact class of failure for this
project ("It fails **silently and green**"), and durability is the one thing #272 adds that must not
fail in silence. This is the strongest candidate of the eleven for a real follow-up issue.

---

## Cheap, and only deferred because review had already closed

Each of these is a comment, a one-line guard, a log line, or a missing assertion. None was judged to
justify reopening the review loop; all are safe to fold into the next change that touches the file.

| Ref | Where | What |
|---|---|---|
| M2 | `memory_engine.py:2300` and `00-overview.md:57` | Both cite `FileStore` sharing the `RLock` at "`:109`". `:109` is the decorator; the constructions are `:120` and `:1564`. The **claim is correct and verified** — only the addresses are stale. |
| M3 | `test_session_watcher.py:2495` and `:2578` | `test_token_overlap_heuristic_match_does_not_confirm` and `test_heuristic_below_the_floor_does_not_record_confirmed_use` share prompt, response, node title/content, patch target and four of five assertions. The only distinct ones are `evidence["match"] == "token_overlap"` and `recorded == 1`. One test carrying both loses nothing. |
| M4 | `index/db.py:225` | `CREATE INDEX IF NOT EXISTS idx_claims_pending` runs unconditionally, while the three `ALTER TABLE` blocks above it (`:186`, `:190`, `:194`) are each guarded by `if claim_cols and ...`. Unreachable today — `_migrate` is only called from `init_schema` after `executescript(schema)` creates the table — but proven to raise `no such table` if the table is dropped first. The guard pattern promises a robustness the next statement does not have. |
| M5 | `test_confirmed_use_contract.py:1186` | `test_backfill_isolates_one_nodes_failure` asserts node 2 got its backfill, but never asserts node 1's claim was left in a **sweepable** state. The backfill→sweeper handoff was proven to work by probe during the final review; nothing pins it. |
| M7 | `memory_engine.py:2316` | The mutator returns silently when `SELECT changes() != 1` (no pending claim). A sixth caller that forgets to claim gets total silence. One `logger.debug` naming `(whisper_log_id, node_id)` is the line you would want the first time this is debugged in production. |

### Carried from the per-task reviews

| Ref | Where | What |
|---|---|---|
| C1 | `test_engine/test_signal_strength.py:8-9` | Imports `signal_strength` twice — plain and as `ss`. The two tests added by Task 1 use the plain name; every older test uses `ss`. Deliberate (kept the plan's test bodies verbatim), ruff-clean. Collapse to `ss` if the file is touched. |
| C2 | `test_confirmed_use_contract.py:911` and `:938` | `test_backfill_skips_rows_below_the_floor` and `test_backfill_skips_a_never_injected_event` stay **green** if the backfill's own guard is removed, because `_claim_confirmed_use` independently re-checks both the floor and `was_injected`. Defence in depth is real and production is protected; the tests simply do not pin the layer they name. |
| C3 | `session_watcher.py:457` | The `already_confirmed` EXISTS subquery does not filter on `state`, so an `orphaned` or `legacy_unknown` claim also suppresses the judge. Believed correct under at-most-once semantics, but **no test states the intent either way** — so a future change cannot tell a deliberate choice from an oversight. |

### The one gap the final review rated highest

**G1 — nothing pins the sweeper's `WHERE state = 'pending'`** (`reinforcement_retry.py:51`).

This sharpens, and partly corrects, an earlier conclusion in the ledger. Removing that filter is
**not** caught by any test: `test_sweeper_never_touches_terminal_claims` stays green because the
mutator's own `AND state = 'pending'` (`memory_engine.py:2313`) is a second, independent guard.

The cost of losing it is therefore not double reinforcement — the mutator prevents that — but
**batch starvation**: terminal rows fill the 200-row batch and crowd out pending ones. That is
precisely the failure `test_a_wall_of_failing_claims_does_not_starve_the_newest` exists to prevent,
arriving through a door that test does not watch.

Of everything in this file, this is the one whose absence could silently degrade the feature while
the suite stays green.

---

## Related, and still assumed rather than measured

Recorded here so they are not mistaken for verified facts:

- **The two-binary (#238) rollback story end to end.** The load-bearing half *is* verified by
  execution — an old-shaped `INSERT` omitting `state` lands `legacy_unknown`, which is terminal for
  both the sweeper and the mutator. The rest (that an old binary's own migration does not drop or
  rewrite the new columns) is inferred from reading; no actual pre-#272 binary was run against a
  migrated store.
- **Every production-volume figure quoted in docstrings and in M6 above:** "1,629 positive heuristic
  pairs", "97.4% token_overlap", "1,587 of 1,629", "42 pairs", "max ratio 7.583 on a live store".
  These describe a live store sampled on 2026-08-26 and are not re-derivable from the diff. No code
  depends on any of them — the executable pin is
  `OVERLAP_FLOOR + OVERLAP_SPAN = 0.78 < HEURISTIC_CONFIRM_FLOOR = 0.80`, which is verified.
- **First-boot cost of the unbounded backfill on a large store** (M6). Never measured.

---

## Raised by `/council-pr` of 2026-08-28, deferred by André

**Line numbers in this section are measured at `19ec283`**, not at `e975a90` like the rest of this
file — `19ec283` moved `file_store.load()` inside the transaction, which shifted the surrounding
lines. Run: `RUN_ID=40d8ff05-19ec2837-72e5217b`, `DIFF_BASE=40d8ff0`, peers Cursor (TIMEOUT, no
verdict) and Codex (`needs-attention`).

Both findings target the durable-retry protocol introduced by `b841235` and `e975a90` — **not** the
two council fixes of 2026-08-28. Both are Codex `high` findings that arrived **without a
reproduction command**, so the ADR-0009 evidence gate could execute nothing: they are recorded as
`unverified_blocking`, meaning **neither confirmed nor refuted**. Nobody has reproduced them; nobody
has shown they cannot happen. Treat them as plausible and unmeasured.

### C1 — A failed COMMIT can still turn one claim into two increments

`src/ormah/engine/memory_engine.py:2407-2425` · Codex `high`, confidence 0.94

The markdown file is saved before the enclosing SQLite transaction commits. If the save succeeds and
the COMMIT fails, the file holds `access_count + 1` while the database and the claim roll back.
Before the retry runs, `update_node` or any other file-to-index path can read that file and promote
the phantom counter into SQLite via `builder.index_single`. The pending claim then retries from the
already-incremented row and writes `access_count + 2`.

This contradicts the invariant the branch's own comment asserts — that a retry recomputes the same
values because "the counters come FROM the nodes row". That holds only while no file-to-index
operation runs between the failure and the retry.

Codex's suggested direction: do not expose an uncommitted lifecycle value through the authoritative
markdown; use a durable outbox/reconciliation record, or commit the SQLite result first and make the
file projection independently retryable from that committed target. Regression test would cover
save-OK → COMMIT-fail → reindex/update → retry.

**Deferred because** the fix is a design decision about the retry protocol (outbox vs. inverting
commit/save order), not a patch — it belongs in its own brainstorming and issue, not tacked onto a
branch already stacked on PR #273.

### C2 — A missing markdown file permanently discards a still-existing node's reinforcement

`src/ormah/engine/memory_engine.py:2342-2351` · Codex `high`, confidence 0.90

The claim is marked terminal `orphaned` when the file load fails **or** the SQLite node row is
absent. A node can exist in SQLite while its markdown is temporarily absent — sync, restore, or any
partial filesystem operation. The sweeper then stops retrying forever, even if the file reappears
seconds later. `test_missing_node_ends_orphaned_not_applied` covers only absence from *both* stores,
so this one-sided degraded state is undefended.

Codex's suggested direction: treat one-sided absence as recoverable and leave the claim pending with
backoff; mark `orphaned` only when authoritative deletion is established (index row *and* file
absent). Tests for DB-present/file-missing followed by file restoration.

**Deferred because** André chose to close the approved scope first. This is the smaller of the two
and the natural next one to fix.

### Structural note — Cursor cannot review this branch

Cursor has now timed out three consecutive times on this diff (2,434 lines twice, 2,598 lines on
2026-08-28). Peer-delivery failure is a hard block in the auto-merge gate, so **every `/council-pr`
on this branch will be born blocked** until the diff is partitioned or Cursor's timeout is raised.

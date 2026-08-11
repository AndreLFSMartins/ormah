# Whisper: detect rotted synthetic-prompt patterns and propose corrections — Design

- **Date:** 2026-07-16
- **Status:** Approved (brainstorming) — ready for implementation plan
- **Issue:** [#143](https://github.com/r-spade/ormah/issues/143) — slice 1 of 2
- **Depends on:** [#134](https://github.com/r-spade/ormah/issues/134) / PR [#141](https://github.com/r-spade/ormah/pull/141) (OPEN upstream as of 2026-07-16)
- **Branch (to cut):** `feat/synthetic-pattern-rot-detection` from `fix/whisper-synthetic-prompt-filter`, **not** from `upstream/main` (see "Branch strategy" below and `FORK-WORKFLOW.md`)

## Problem

Issue #134 (PR #141) skips machine-generated turns by matching a prompt against a hardcoded list of
three regexes plus operator-supplied `whisper_synthetic_prompt_patterns`. Both halves decay:

- **Builtin defaults** track Claude Code's machine-turn markers. Claude Code can rename or
  restructure them at any release. When it does, coverage silently drops to zero — the filter
  keeps "working", just matching nothing.
- **Operator patterns** track whatever headless scripts and agents an install happens to run.
  That set changes as the user's tooling changes, and nobody goes back to re-measure.

There is no alarm for either. The only symptom is a slow return of wasted encode/search/rerank on
turns no human reads — exactly the state #134 set out to fix.

## Scope: this is slice 1 of 2

Issue #143 describes two machines with very different costs. They are split:

| Slice | What | Cost / risk |
| --- | --- | --- |
| **1 — this spec** | Instrument which pattern matched; detect patterns that rotted; propose corrections. | Deterministic, no LLM. A false positive asks a question the user rejects. |
| **2 — separate spec** | Mine `retrieval_events` residue for *emerging* patterns via clustering + hard negatives + LLM judge. | LLM cost. A false positive silences real memories, invisibly. |

Slice 1 first because it delivers the alarm the issue says does not exist, and because the
per-pattern counter it adds is the honest denominator for slice 2's evidence.

## Findings that changed the design

All verified by reading code at `local-main` (HEAD `5f93cce`). Each contradicts the issue text.

### 1. `whisper_health` is not a table — nothing persisted can be "re-contaminated"

The issue speaks of "re-contaminated `whisper_health`". There is no such table. The full
`CREATE TABLE` list in `src/ormah/index/schema.sql` is: `nodes`, `edges`, `node_tags`,
`proposals`, `meta`, `merge_history`, `auto_link_checked`, `duplicate_checked`,
`conflict_checked`, `consolidation_checked`, `audit_log`, `retrieval_events`, `whisper_log`,
`affinity`, `signals`, `whisper_decisions`, `review_log`.

`whisper_health` is computed on the fly: `compute_whisper_health(conn, now) -> dict`
(`src/ormah/engine/whisper_health.py:68`), consumed at `memory_engine.py:1708` and exposed in the
stats payload. It is a read-only projection, which is why the detector cannot live there (see
Design, Component 3).

### 2. The `Proposal` Pydantic model is dead code — there is nothing to "widen"

Issue item 3 says "`Proposal.source_nodes: list[str]` assumes memory nodes; either widen the model
or use a sibling table". The premise is false: the model (`src/ormah/models/proposals.py:24`) is
never instantiated. Writes and reads are raw SQL over dicts. The single writer hardcodes both
`type` and `status` as SQL literals (`src/ormah/background/duplicate_merger.py:437-441`):

```python
"INSERT INTO proposals (id, type, status, source_nodes, proposed_action, "
"reason, created) VALUES (?, 'merge', 'pending', ?, ?, ?, ?)"
```

So the decision is not "widen the model vs sibling table" — it is "reuse the `proposals` table or
not". We reuse it.

Of the three `ProposalType` values, only `merge` is ever created. `conflict` is never created
(`conflict_detector.py` writes edges directly at `:386` and `:394`), which makes the
`approved + type == "conflict"` branch at `routes_agent.py:413-426` unreachable. `decay` is never
created and is **actively deleted on every run** by an unguarded statement in `run_decay`
(`src/ormah/background/decay_manager.py:20-24`):

```python
# One-time cleanup: remove legacy pending decay proposals
conn.execute("DELETE FROM proposals WHERE type = 'decay' AND status = 'pending'")
```

The comment says "one-time" but there is no guard — it runs forever, daily. **A new proposal type
must not be named `decay` and must not reuse that value**, or the decay manager will silently eat
our proposals every night. This is the single sharpest trap in this design.

### 3. Absence from `retrieval_events` does not identify a filtered prompt

The issue states that non-matching prompts "flow through the whole pipeline" and leave a row. That
is **necessary but not sufficient**. Four early returns write `whisper_decisions` but never reach
the `retrieval_events` insert: empty prompt and `<=2` alphanumeric chars → `silent_short`
(`context_builder.py:365-389`); no engine (`:391-398`); `intent.categories == ["conversational"]`
→ `silent_conversational` (`:410-421`). The insert itself is conditional on `session_id`
(`context_builder.py:990`).

Consequence for slice 2 (recorded here so it is not rediscovered): the candidate pool is a
*subset* of unfiltered prompts. Consequence for slice 1: the reliable discriminator of "was
filtered" is `whisper_decisions.outcome = 'silent_synthetic'`, **not** absence from
`retrieval_events`. Slice 1 reads only `whisper_decisions`.

### 4. The `ReviewQueue` UI exists and is orphaned

`ui/src/components/ReviewQueue.tsx` (150 lines) is complete, with a working client at
`ui/src/api.ts:43-51`. Nothing imports it — grep for `ReviewQueue|fetchProposals|resolveProposal`
across `ui/` and `desktop/` returns only the definitions. #82 is "wire an orphan", not "build a
screen". Out of scope here; noted because it means our proposals reach a human today only via MCP
`list_proposals` (`src/ormah/adapters/mcp_adapter.py:294`), which is sufficient.

### 5. "Matches zero" is the wrong rot criterion

`<scheduled-task` can match zero because the operator **does not use scheduled tasks**. That is
irrelevance, not rot, and proposing removal would be noise. What separates them: **rot = matched
before and stopped**; irrelevance = never matched.

This is implemented as `last_seen`, not as two windows. `MAX(logged_at)` per pattern carries the
same semantics at a fraction of the cost, and needs no bootstrap period beyond a single match:
a pattern that never matched has no row and stays silent without any code deciding that.

## Design

### Branch strategy

Issue #143 consumes what #141 introduces: `is_synthetic_prompt`, the setting
`whisper_synthetic_prompt_patterns` (the target of the proposals), and the `silent_synthetic`
outcome (the signal). None of the three exist in `upstream/main`, so the normal rule — cut from
`upstream/main` — cannot apply.

Cut `feat/synthetic-pattern-rot-detection` from `fix/whisper-synthetic-prompt-filter`
(local and `fork` both at `8b671ad`, 6 commits ahead of `upstream/main`). Open the PR stacked on
PR #141, or rebase onto `upstream/main` once #141 merges. Push to `fork`, never `upstream`.

### Component 1 — `match_synthetic_pattern()` (`src/ormah/engine/prompt_classifier.py`)

Replace `is_synthetic_prompt(prompt, extra_patterns) -> bool` with:

```python
def match_synthetic_pattern(prompt: str, extra_patterns: Sequence[str] = ()) -> str | None:
    """The source of the pattern that matched, or None when the prompt is human."""
```

It returns the regex *source* (`r"<task-notification>"` for builtins, the raw string for operator
patterns) — stable, readable, and literally the string the user would put in or take out of
`.env`. Matching semantics are unchanged: anchored `.match()` after `lstrip()`, invalid operator
regex logged and skipped (fail-open).

No `is_synthetic_prompt` wrapper is kept. There is exactly one production call-site
(`routes_agent.py:149`); a wrapper with zero consumers is speculative abstraction.

**The one way this change introduces a bug:** an operator can configure the empty regex `""`,
which matches everything and returns `""` — falsy. The call-site must test `is not None`, never
truthiness. This gets a dedicated test.

### Component 2 — record the match (`whisper_decisions`)

Add `matched_pattern TEXT` to `whisper_decisions` — NULL except on `silent_synthetic` rows.
Migration by `ALTER TABLE ADD COLUMN` in `_migrate()` (`src/ormah/index/db.py:129`), following the
existing pattern there; `schema.sql:222-238` updated to match for fresh installs.

The value threads from the boundary guard (`routes_agent.py:141-157`) through
`engine.note_synthetic_whisper_skip` (`memory_engine.py:1257-1273`) into
`ContextBuilder._log_decision` (`context_builder.py:293-327`), each gaining a
`matched_pattern: str | None = None` keyword.

`whisper_decisions` is the right home: already one-row-per-call, already receives
`silent_synthetic`, already indexed on `logged_at` — which is what the rot query needs. The table
stores `prompt_hash` only, never text (`schema.sql:221`); this column does not change that.

### Component 3 — `synthetic_pattern_monitor` (`src/ormah/background/`)

A new scheduled job, no LLM, daily. Not folded into `whisper_log_cleanup` (unrelated
responsibility) and not computed inside `whisper_health` (that is a read path called from a `GET`;
creating proposals there would write to the DB whenever someone opens the stats screen).

Steps:

1. **Traffic guard.** If `whisper_decisions` has no row in the last `rot_days`, return. Without
   this, two weeks of user vacation rot every pattern at once.
2. **Collect live patterns:** the three builtins from `_SYNTHETIC_PATTERNS` + the operator's
   `whisper_synthetic_prompt_patterns`, each tagged with its origin.
3. **Query `last_seen`:**
   ```sql
   SELECT matched_pattern, MAX(logged_at) FROM whisper_decisions
   WHERE outcome = 'silent_synthetic' AND matched_pattern IS NOT NULL
   GROUP BY matched_pattern
   ```
   No row → never matched → stay silent. Row older than `rot_days` → rotted.
4. **Propose**, unless a proposal for that pattern already exists.

Patterns present in history but absent from the live config (the user edited `.env`) are ignored:
the job iterates live patterns and looks each one up, never the reverse.

Registration touches the four places the repo requires (there is no declarative registry):
`start_scheduler` (`background/scheduler.py:47-235`), `_TASK_RUNNERS`, `_TASK_DESCRIPTIONS` and
`_SLEEP_CYCLE_ORDER` (`api/routes_admin.py:24-70`). It does **not** touch `_stagger_factor`
(`scheduler.py:33-38`), which hardcodes the four LLM jobs — this job makes no LLM call.

### Component 4 — the proposal

A new `ProposalType` value — `pattern` — in `models/proposals.py:12-15`, mirrored in the
hand-maintained union at `ui/src/types.ts:84`. Explicitly **not** `decay`, which the decay manager
deletes nightly (Finding 2).

`INSERT INTO proposals` with `source_nodes = '[]'` (honest: there are no nodes; `GET
/agent/proposals` enriches by looping node ids, so an empty list yields `nodes: []` and no error).

Origin decides the text, because the two cases have opposite actions:

- **operator pattern** → *"Remove this entry from `ORMAH_WHISPER_SYNTHETIC_PROMPT_PATTERNS`:
  `<regex>`"*
- **builtin** → *"Claude Code marker `<regex>` stopped appearing; it was likely renamed. Report
  upstream."* — telling the user to remove from their `.env` a pattern that is not in their `.env`
  is an instruction impossible to follow.

**Dedup is what decides whether this feature works or becomes spam.** The job runs daily and the
pattern stays rotted daily. Dedup is `SELECT 1 FROM proposals WHERE type = <new> AND
proposed_action = ?`, which **forces `proposed_action` to derive from the regex alone, with no
variable numbers in it**. Putting "not seen for 47 days" in `proposed_action` would change it
every 24h, the dedup would never hit, and the job would create one proposal per day forever. All
variable evidence (last_seen, historical count) goes in `reason`, which is not part of the dedup
key. Dedup deliberately matches resolved rows too: rejecting a proposal kills it for good.

Approve/reject need no new code. A type with no branch in `routes_agent.py:388-426` falls through
to the plain `UPDATE status` — nothing is auto-applied, which is requirement #1 of the issue. The
`approved`-then-side-effect-fails hazard (`routes_agent.py:379-397`) does not reach us precisely
because there is no side effect to run.

### Component 5 — settings (`src/ormah/config.py`)

| Setting | Default | Meaning |
| --- | --- | --- |
| `whisper_pattern_rot_days` | `30` | `last_seen` older than this → rotted. Also the traffic-guard window. |
| `whisper_pattern_monitor_interval_minutes` | `1440` | Job interval, matching the other daily jobs. |

## Testing

Mould: `tests/test_background/test_duplicate_merger.py` — real `engine` fixture
(`tests/conftest.py:132-137`). No LLM to mock here, so no `reset_adapter()` dance.

`tests/test_engine/test_prompt_classifier.py` (adapting the 8 existing `TestIsSyntheticPrompt`
cases to the new return type):
- returns the builtin's regex source for each of the three markers
- returns the operator's raw string for an `extra_patterns` match
- returns `None` for a human prompt, for `<ide_opened_file>`-wrapped human text, and for a human
  asking *about* a marker (anchoring guard)
- invalid operator regex → skipped, other patterns still evaluated
- **empty pattern `""` returns `""`, not `None`** — the falsy trap

`tests/test_engine/test_whisper_context.py`:
- the boundary writes `matched_pattern` on the `silent_synthetic` row
- a prompt matching an operator pattern records that pattern, not a builtin

`tests/test_background/test_synthetic_pattern_monitor.py`:
- pattern never matched → no proposal
- pattern matched within `rot_days` → no proposal
- pattern last matched beyond `rot_days` → one proposal
- no traffic in the window → no proposal even with rotted patterns (vacation guard)
- second run → no duplicate
- rejected proposal → not re-proposed
- builtin vs operator → different `proposed_action` text
- pattern in history but removed from config → no proposal

`tests/test_background/test_scheduler.py`:
- `"synthetic_pattern_monitor" in job_ids` (mould: `test_forgetting_job_is_registered`)

## Verification (not "tests pass")

1. `make test` and `make lint` green, output cited.
2. Fresh-DB migration: open a DB created before the change, confirm `matched_pattern` exists and
   the server starts.
3. Drive the real path: send a `<task-notification>` prompt to `/agent/whisper` on the running
   Beta, then confirm one `whisper_decisions` row with `outcome='silent_synthetic'` and
   `matched_pattern='<task-notification>'`.
4. Force a rot: set `whisper_pattern_rot_days=0`, trigger the job via `/admin`, confirm exactly
   one proposal per live pattern with history; trigger again and confirm no duplicates.
5. Confirm `run_decay` does not delete the new proposals (the `decay_manager.py:20-24` trap).

## Out of scope

- The LLM miner for emerging patterns — slice 2, separate spec.
- Wiring the orphaned `ReviewQueue` — that is #82.
- Editing the user's `.env`. The proposal renders the exact line; the user applies it.
- Auto-applying any pattern.
- Fixing the unguarded `DELETE` in `decay_manager.py:20-24`, the fragile `"\n---\n"` split at
  `routes_agent.py:353`, or `ResolveProposalRequest` accepting `pending`. Real defects, found
  while exploring, unrelated to this change — worth their own issues.

## Risks / unverified

- **Irreducible false positive.** A pattern may not match because the traffic it would match did
  not happen — no subagents for `rot_days` makes `<task-notification>` look rotted. The issue
  acknowledges this implicitly ("silent_synthetic hitting zero *while subagents run*"); we have no
  way to know whether subagents ran. The traffic guard only catches total inactivity, not
  per-category inactivity. Accepted because the cost is a question the user rejects — unlike slice
  2, where a false positive silences real memories invisibly.
- **Bootstrap blind spot.** A pattern that matched heavily *before* the migration and stopped just
  after will have no `matched_pattern` history, so it reads as "never matched" and stays silent.
  Fails toward not bothering the user. Self-corrects as history accumulates.
- **Unverified:** the exact `ALTER TABLE` idiom used by `_migrate()` (`db.py:129`) was reported by
  exploration but not read line-by-line; the plan must read it before writing the migration.
- **Unverified:** whether `GET /agent/proposals` renders acceptably with `source_nodes='[]'` was
  reasoned from code (`routes_agent.py:341-359`), not executed. Verification step 4 covers it.
- **Dependency risk.** If r-spade requests changes to #141 that rename `is_synthetic_prompt` or
  reshape the settings, this branch rebases and Component 1 shifts. Low cost, but real.

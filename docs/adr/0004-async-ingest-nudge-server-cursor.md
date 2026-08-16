---
status: accepted
---

# Ingest is async: the client nudges, the server owns the cursor and advances on job completion

Both **Ingest** lanes coupled cursor-advance to a synchronous extraction that can outlast any client's
patience. The **Hook lane** posts the delta over HTTP and advances its client-side **Cursor**
(`whisper-cursors.json`) only on the response; extraction runs p50 118s / max 33.6min server-side while
the client's httpx gives up at ~135s, so the **Cursor** never advances and the next **Session boundary**
re-posts the same delta — the extraction completes server-side *and* is re-enqueued (the observed "same
1.14M-char payload posted 5×"). The **Watcher lane** runs in-process (no client timeout), but a
`claude -p` timeout returns `None` → classified provider-wide `EXTRACT_ERR_CALL_FAILED` → `TRANSIENT`
with *no* per-slice cap increment → the same slice re-extracts every tick forever, burning quota and
never quarantining (a second engine, distinct from the ADR-0003 recovery loop: this one re-does work
rather than duplicating nodes). And the two lanes track independent cursors over the same files with no
coordination (~250-500 double-ingested nodes — the two-cursor overlap).

Decision: **the client never waits.** The **Hook lane** becomes a pure **Nudge** (`POST /ingest/nudge
{path}`, 202, exit) — no content, no **Cursor**, no poll; `whisper-cursors.json` is deleted. The **server
owns the single Cursor** and advances it on **job completion**, not on a request response. The Cursor +
in-flight guard + `_ingest_session` worker — today reachable only behind the watchdog Observer and gated
by `session_watcher_enabled` — is extracted into an always-on **Ingest worker**; the watchdog Observer
and the reconcile sweep become optional **Producers** layered on top when the watcher is enabled.
Nudge (boundary) and Observer (continuous) feed one worker → one Cursor, one guard → the overlap is gone,
including for the watcher-on maintainer. Because nothing waits, the client timeout is removed and the
server-side extraction timeout is sized generously to the model's real worst case (`.env`-overridable,
per the ADR-0001 amendment); when it fires, a `TimeoutExpired` (a genuinely slow/toxic slice) counts
toward the per-slice cap and quarantines after N, while a fast failure (connection refused, missing
binary) stays uncapped `TRANSIENT` — preserving the H1 rule that a provider *outage* never quarantines
real data. A slow timeout is not an outage; the two `except` clauses in the adapter already separate them.

Durability: the **Cursor** is already durable; the queue and in-flight guard stay in-memory, and a
**startup drain** (the existing reconcile pass, run for every install) re-enqueues any transcript whose
Cursor is not at EOF. No durable job table — a lost in-memory job is re-derivable from "Cursor behind EOF".

## Considered options

- **`async:true` on the SessionEnd hook manifest only:** rejected — palliative. It stops the hook holding
  the session, but the Cursor still advances only on the synchronous HTTP response, so the
  freeze-and-re-post engine is untouched. (PreCompact already carries `async:true` and still showed the bug.)
- **Hook posts content, server enqueues the bytes with its own session-keyed cursor:** rejected — a second
  cursor + extraction path parallel to the watcher's; two implementations of the same cursored logic. The
  server already reads these files (same machine), so posting content is redundant once it owns the Cursor.
- **Only async-ify the hook, leave the watcher a separate lane:** rejected — smaller diff, but leaves two
  cursors whenever the watcher is on, so the double-ingest overlap survives for exactly the users (the
  maintainer included) who run the watcher.
- **Durable SQLite job table:** rejected for now — the Cursor is already the durable truth and a lost job
  self-heals via the startup drain; a job table is machinery for an error whose cost is low (Material
  recurs, ADR-0002). Revisit only if measured drain latency hurts.
- **Nudge + server-owned Cursor + lane convergence + generous timeout with slow/fast split (accepted):**
  smallest change that attacks the root — deletes the client Cursor and the whole-delta re-post, unifies
  the lanes, and closes the transient-retry loop without reintroducing the H1 outage risk.

## Consequences

- The hook loses all parse / space-detect / min-turns logic — it is a trigger. `whisper-cursors.json` is
  removed; on upgrade the server Cursor may sit behind it and re-ingest one delta (dedup heals the
  one-time overlap).
- The always-on **Ingest worker** instantiates the handler (Cursor + guard + `_ingest_session`) regardless
  of `session_watcher_enabled`; the Observer + reconcile attach only when it is enabled.
- The worker stays **serial** — multi-window concurrency is a separate track (issue #150), out of scope here.
- The `claude_cli` adapter must signal `TimeoutExpired` distinctly from other `None`-returns so the
  cap/quarantine split can key on it.
- Residual: an ended session whose in-memory job is lost while the server stays up (no crash) strands until
  the next restart's drain; the generous timeout value is a measured knob, not a proven constant.
- Provenance is **upstream**: the hook, the endpoint, and `session_watcher.py` all live in `upstream/main`,
  so this is an upstream contribution merged into the Beta (`local-main`); ships after the P1 gate
  (ADR-0002), which reduces the volume that would hit the redesigned lane.

## Amendment 2026-07-22 — the durable queue is a directory spool, not the Cursor alone (and not a job table)

The original text says the queue "stays in-memory" because "the Cursor is already the durable truth", and
rejects a durable SQLite job table on that basis. Eight rounds of plan review invalidated the premise, and
a prototype (`spool_proto*.py`, throwaway) measured the alternatives. Both halves of the original decision
change; the accepted decision itself (client nudges, server owns the Cursor, one always-on worker) stands.

**Why the premise failed.** Delivering the nudge needs three facts the Cursor does not model: *which
boundary was accepted*, *whether ingestion was explicitly requested* (the consent signal when
`session_watcher_enabled=False`), and *whether the server persisted the request before answering 202*.
Each was squeezed into `.session_watcher_state` — a single JSON blob per watch dir, rewritten whole from
four call sites (`session_watcher.py` 889/909/984/1046) via a non-atomic `write_text` (L700-703). Every
added field produced a new race: stale-snapshot clobber between the API thread and the worker thread, a
202 answered before the write landed, and path dedupe that did not survive a restart. The Cursor is a
progress record; it was being asked to be a queue.

**Why not the SQLite job table.** Measured, not assumed. `db.py:37-40` runs WAL with
`synchronous=NORMAL`, so a committed `INSERT` survives process death but **not** power loss — the
transactional-durability argument for the table does not hold here. Meanwhile writes are serialized with
`busy_timeout=5000`, so a nudge arriving during a maintenance transaction can block up to 5s inside the
one request path whose whole purpose is that nobody waits. The table would couple the cheapest operation
in the system to its heaviest. The original rejection stands, for better reasons than the original ones.

**Decision: a directory spool** under `memory_dir`, owned by the ingest lane and independent of the store:

```
ingest_queue/pending/<path-hash>.<boundary>.json     # one file per accepted nudge
ingest_queue/running/<path-hash>.<boundary>.json     # claimed
```

The worker claims by `os.rename(pending/x, running/x)`; the rename **is** the mutual exclusion. Completion
deletes the file. Startup renames everything under `running/` back to `pending/`. Measured properties:

- **Claim exclusivity holds across processes** — 40 rounds × 8 racing processes, always exactly one winner.
  `FileNotFoundError` on the loser is the mechanism, not an error to handle.
- **The boundary MUST live in the filename.** One-file-per-path with overwrite loses the higher boundary
  whenever a slower producer that measured an earlier EOF lands last: **135 of 300 races (45%)**, and the
  lost nudge is unrecoverable when the watcher is disabled. With the boundary in the name, nudges never
  overwrite each other: 0/300.
- **Every write is `tmp` + `os.replace`.** A direct `write_text` of a 400 KB file with a concurrent reader
  produced **7081 torn reads** against 664 clean ones over 1.5 s; via `os.replace`, 6210 clean and **0**
  torn. This also applies to `_save_state`, whose current non-atomic write can destroy every Cursor in a
  watch dir — fixed independently of this amendment.
- **Claim-by-rename excludes per JOB, not per transcript.** Because the boundary-in-name rule puts several
  files under one path, two workers can ingest the same transcript concurrently: 0 overlaps with 1 worker,
  14 with 2, 21 with 4. The worker is serial (issue #150), so this is latent, not live. When concurrency
  lands, claim the *path* with `os.mkdir(running/<path-hash>)` — atomic, `FileExistsError` means taken —
  then sweep that path's files into it: 0 overlaps at 4 workers. Do not ship concurrency without it.

**Durability level, named explicitly.** The spool is *not* fsynced by default. The threat model is process
restart and server crash, not power loss — the same guarantee the store already gives under
`synchronous=NORMAL`. The cost of upgrading is measured: `os.fsync` is nearly free (p50 0.147 ms vs
0.127 ms) but on APFS does **not** flush to media; real durability needs `fcntl(F_FULLFSYNC)`, at p50
**6.9 ms** / p95 9.0 ms per nudge. That is affordable if the guarantee is ever wanted; it is not the
default, and the choice is a decision rather than an oversight.

**Consequences that replace text above.**

- The queue is durable; "the queue and in-flight guard stay in-memory" no longer holds. The startup drain
  remains as a *recovery* producer, not as the durability mechanism.
- The residual "an ended session whose in-memory job is lost while the server stays up strands until the
  next restart" is **closed**: the job is a file on disk.
- **Consent is now structural.** When `session_watcher_enabled=False` the worker drains the spool and
  nothing else — a spool entry exists only because the user's own hook created it. This retires the
  intent-only reconcile-scope rule the plan review had derived, and with it the tree walk (`rglob`) on
  disabled installs.
- The Cursor keeps its job: byte offsets remain the progress truth. A job leaving the spool means the
  *intent* was consumed, never that the bytes were — an ingestion is capped by `flush_bytes` and may be
  partial. The two must not be conflated.
- The spool must live on the same filesystem as its `tmp` staging dir (rename atomicity is per-filesystem),
  hence inside `memory_dir`, never `/tmp`.
- **The client-side outbox survives.** Neither a spool nor a table protects against the server being
  unreachable — the hook reaches neither. Its locking must take a **stable lock file**: locking the outbox
  inode itself is now confirmed broken, not theoretical — with the drain rotating the file via
  `os.replace`, three appenders produced **1140 mutual-exclusion violations** in 2 s (the lock survives on
  an unlinked inode), against 0 with a separate lock file.
- Verified on APFS/macOS only. Rename atomicity is POSIX; the numbers are not portable.

## Field observation 2026-07-27 — the `no_safe_boundary` dead-letter has 533 transcripts and no drain

Measured on the live Beta, read-only, while deciding the merge window for ADR-0001 Amendment 3. Recorded
here because the mechanism is this ADR's, and because the code comment that created it points at a slice
that no longer exists.

**What it is.** `session_watcher.py:1279-1287`: when extraction returns NO_PROGRESS and
`_idle_with_unsafe_tail()` holds — an idle transcript with bytes past the cursor that the parser closes
nothing at, i.e. a single unterminated turn — the worker advances the cursor past the frozen prefix (so
the sweep stops re-selecting the file) and calls `spool.requeue(job, failure_class="no_safe_boundary")`.
In `ingest_spool.py:229-280` every class other than `external` is deterministic and is dead-lettered
immediately into `failed/`, with the original job bytes preserved plus a `<name>.error` sidecar. Only
`external` (provider down, timeout, EIO) retries forever with persisted backoff — the H1 rule that an
outage must never discard real data.

> **CORRECTED 2026-08-11.** "Retries forever" is the intent, not the behaviour. The backoff arithmetic
> raises `OverflowError` at the 1025th attempt and the requeue never lands, so the retry stops there —
> observed in production. See the amendment 2026-08-11 below.

This is deliberate, not a defect: the alternative at that call site is a silent `complete()`, which would
strand the bytes with no record at all. The code says so, and names its successor:
*"keep a dead-letter record with a distinct reason (slice 3 owns the real policy) — never a silent
complete."*

**Provenance: local, not upstream.** `src/ormah/background/ingest_spool.py` does not exist in
`upstream/main`, and the string appears nowhere in that branch's `session_watcher.py`. Introduced by
`adbec81` "feat(ingest): always-on ingest worker; Observer and reconcile become optional producers
(ADR-0004)". Nothing about this has ever been contributed upstream.

**The gap.** ADR-0004 **slice 3 was descoped on 2026-07-25** (recorded in the content-budget plan
overview: *"ADR-0004 slice 3 — descoped 2026-07-25, do not replan it"*). So the recording half shipped and
the draining half never did. Descoping was reasonable while the dead-letter was empty. It is no longer
empty, and the cost of the descope is now measurable rather than hypothetical.

**Measured 2026-07-27 (~17:10 BRT)**, spool root `memory_dir/ingest_queue/<root_key>/`:

| quantity | value |
|---|---|
| `pending` / `running` | **0 / 0** — the drain itself is complete |
| dead-lettered jobs | **586** (1172 files: each job is `<name>.json` + a 39-byte `<name>.json.error`) |
| **distinct transcripts** | **533** — 499 with a single record, max 5; not one file looping |
| transcripts still on disk | 533 / 533 |
| error text | 100% `deterministic failure: no_safe_boundary` |
| by `reason` | 518 `reconcile`, 60 `drain`, 8 `nudge` |
| growth | 427 at the Task 6 measurement (2026-07-26) → 586; most recent ~99 min before the reading |

Note for anyone re-measuring: counting raw files gives 1172 and makes the `.error` sidecars look like
corrupt JSON. Count `*.json` only.

**What this does and does not mean.** `pending = 0` is not "nothing is stuck": 533 sessions have content
that never entered the store, and their cursor has already advanced past it. Each is recoverable by hand —
the job preserves `path` and `boundary` — but nothing recovers them automatically, and the set grows.

**Not caused by, and not affected by, ADR-0001 Amendment 3.** `no_safe_boundary` is a boundary-detection
outcome, not a budget outcome; the content budget and the raw ceiling do not participate in that branch.

**UNVERIFIED, and the first thing to settle:** whether those orphaned bytes are genuinely lost or whether
some other path reprocesses them later. `_mark_frozen_prefix_consumed` was read at its call site only; its
consequences were not traced.

> **ANSWERED 2026-07-28** — nothing reprocesses them. `_mark_frozen_prefix_consumed` advanced the cursor
> precisely to stop re-selection, and `cursor == boundary == size` held across the whole sample. See the
> slice 3 amendment below, which also measures the volume the step above asked for.

**Suggested next steps, in order.**

1. **Measure the orphaned volume before prioritising.** Each job carries `boundary`; compared against the
   persisted cursor this bounds the bytes left behind. Without that number, "533 transcripts" could be a
   few unterminated lines each or months of conversation — and priority is guesswork either way.
2. **A minimal re-drain policy**, not necessarily all of slice 3. The common case is benign and
   self-healing in principle: the session was open when the job ran, and has since closed. Re-admitting a
   dead-lettered job once its transcript has grown a safe boundary would drain most of the 533 without any
   new policy surface.

## Amendment 2026-07-28 — slice 3: the frozen tail is force-closed automatically, behind an anti-rewind checkpoint

> **PARTIALLY RETRACTED 2026-08-09.** Never merged. Its **diagnosis** is confirmed — the permanent loss it
> describes is happening in production, measured. Its **remedy** (force-close, `force_closed_until`, park
> token, prefix digest) is retracted: it did not converge across 56 review rounds, and the tail it rescues
> has a median size of zero. Read the 2026-08-09 amendment before acting on anything here.

`no_safe_boundary` no longer exists as a failure class. This amendment records the policy that replaced
it, and — more importantly — records **why the obvious implementation is wrong**, so nobody reintroduces
it.

### What the measurement changed

Re-measured on the live spool (549 distinct transcripts, all still on disk):

| quantity | value |
|---|---|
| dead-lettered transcripts vs. entries in state | 549 of 609 — **90%** |
| median coverage already ingested per transcript | **99.5%** |
| never-closed tail, median | **998 B** — the last open JSONL line |
| never-closed tail, total | 1.02 MB |
| transcripts with real partial loss | 31 (worst: 15 turns / 66 KB) |
| transcripts with "total" loss | 8 — sessions with **no assistant response at all**; nothing to extract |

So the dead-letter was never a data-loss backlog: it is the **normal** end-of-session path, recorded as a
deterministic failure. The defect was twofold — unbounded noise that masks real failures, and a dead
session's open tail that is never recovered even when it holds turns.

### Why pure force-close is wrong (the council rejected it; do not reintroduce it)

Parking the cursor inside an open response makes the next slice start with an `assistant` and no `user`
(`parser.py:351-353`) → `leading_orphan` → nothing commits → `_safe_end` does not advance →
`should_rewind` is true (`parser.py:395`) → the watcher re-parses from offset 0 and **re-ingests the whole
transcript**. The risk was never losing a fragment; it was **mass duplication**.

The corollary bit us in the other direction too: a watermark that suppresses the rewind trades duplication
for **silent loss** unless the ordering is exact. The invariant that closes both holes:

> **force-close happens while the cursor is still at `safe_end`; park and watermark only after; a stale job
> never plants a cursor.**

### The policy as shipped

**Force-close gate — all four must hold** (`_ingest_session`). Idle past `idle_threshold`; job **fresh**
(`boundary is None or boundary >= size` — a stale ceiling must never force-close a response the file has
since completed); **recoverable assistant content** past the safe boundary, computed exactly as
`any(t.role == "assistant" for t in result.turns[len(result.safe_turns):])`; and **no pending `tool_use`**.

That fourth criterion is deliberately asymmetric, and the asymmetry is the point: `stop_reason="tool_use"`
is a *structural promise of continuation* — the tool will return and the response will close itself, so
force-closing it would discard a continuation that was always going to arrive. A Codex turn with no
`task_complete`, by contrast, is byte-for-byte indistinguishable from a dead session; no criterion
separates it from the ordinary case, so it is force-closed. A `stat` that fails counts as **not fresh** —
never force-close over a size you did not read.

**`force_closed_until` is a cursor invariant, not a flag.** It means *"this cursor stopped past content
that was never closed, up to N"*. Every writer that advances `end_offset` over unclosed bytes must record
it, so the rule lives **inside** `_commit_state`: `new_offset` and `crosses_unsafe` are parameters, a
metadata-only commit preserves the stored cursor by construction, and an entry that would mutate the cursor
without declaring it is **rejected**. The watermark is written monotonically (`max`), because the extract-skip
path inherits the *flag* from the slice that advanced — not the old *value*; keeping the old value would let
`prev_offset > force_closed_until` come true again and resurrect the very rewind loop this exists to kill.

The rewind call site — note the variable there is `existing`, not `entry`:

```python
if should_rewind(result, prev_offset) and prev_offset > (existing or {}).get("force_closed_until", 0):
```

`should_rewind` itself is unchanged; the decision belongs to the call site, which is what holds the state.
Legacy entries lack the field (default 0), so ADR-0003 recovery stays intact for legacy cursors.

**Parking no longer consumes bytes.** `_mark_frozen_prefix_consumed` advanced the cursor to mean "stop
re-selecting this" — two different things, and conflating them opened a TOCTOU with **permanent** loss: a
job fresh at classification goes stale between `_ingest_session` returning and the cursor mutation, the
writer appends the terminal assistant meanwhile, the successor sees an orphan, the watermark suppresses the
rewind, and the now-complete user/assistant pair becomes unreachable forever. Park therefore writes
`parked_until` and **leaves the cursor alone**; selection is suppressed only while `size <= parked_until`,
so growth past it re-selects the file and parsing resumes from the untouched safe cursor. The suppression is
applied in **both** producer lanes — `reconcile` and `_enqueue_path` — because gating only the sweep would
trade a full `failed/` for a hot enqueue loop on the Observer lane.

**Disposition lives inside the state entry.** A `jsonl` ledger beside the state file cannot work: `_save_state`
writes a pid-scoped temp, `fsync`s, and `os.replace`s; an append to another file does not participate in that
rename, and `state_lock` gives thread exclusion, not crash atomicity. Both orderings break — ledger-first
loses the cursor and re-extracts an already-closed slice; state-first keeps the watermark and loses the audit
record. So `{kind, prev_cursor, boundary, at}` is written *within* the entry, in the same `os.replace` as the
cursor: atomic by construction. A best-effort `jsonl` alongside may exist as history, but it is not what backs
the replay promise.

**A stale job enqueues its own successor before completing.** Merely completing would be a bet that "the next
job carries `boundary = size`". `reconcile` is gated on the per-watch `discover` flag; on an *acceptance-only*
root there is no Observer and no sweep, only external nudges — the recoverable tail would sit without a
successor indefinitely. The successor is enqueued with the size **already measured** by `_ingest_session`
(never a second `stat`, which would reopen the TOCTOU the disposition exists to close), and only when that
size is strictly greater than the job's ceiling — `enqueue` is idempotent on `(path, boundary)` via `os.link`,
so re-enqueuing at the same boundary would loop forever.

### Accepted cost

The continuation of a force-closed response is discarded as an orphan until a new user turn arrives, after
which the flow normalises on its own. That is the "small piece" traded for automatic ingestion, decided
explicitly on 2026-07-28. A slow tool (>600 s) keeps its file parked rather than force-closed — released as
soon as the file grows.

### Known gap, deliberately not closed here

`pause_turn` is non-terminal in the parser but does **not** hold the tail; only `tool_use` does. If it shows
up in practice, it is a force-close of a response that was still going to continue.

## Amendment 2026-08-09 — the 2026-07-28 force-close REMEDY is retracted; its DIAGNOSIS is confirmed and still open

The amendment above was never merged, and the mechanism it built does not survive review. But it must be
split in two, because the two halves have opposite fates:

- **Its diagnosis — that advancing the cursor to mean "stop re-selecting this" causes permanent loss — is
  CORRECT, and measurement today confirms it is happening in production.** See "The loss is real" below.
- **Its remedy — automatic force-close behind a `force_closed_until` watermark, a generation-bound park
  token and a versioned prefix digest — is RETRACTED.** It did not converge, and it is aimed at a tail
  that in the common case is not there.

The accepted decision (client nudges, server owns the Cursor, one always-on worker) and the 2026-07-22
spool amendment both stand untouched.

### It was never shipped

The section above is titled "The policy as shipped" and opens with "`no_safe_boundary` no longer exists as
a failure class". Neither is true of any branch that runs:

| symbol | `local-main` | `feat/adr-0004-slice3-force-close` | `upstream/main` |
|---|---|---|---|
| `no_safe_boundary` | 1 | 0 | 0 |
| `_idle_with_unsafe_tail` | 2 | 0 | 0 |
| `_mark_frozen_prefix_consumed` | 2 | 0 | 0 |
| `force_closed_until` | **0** | 15 | 0 |

The policy exists only on an unmerged branch. Anyone reading this ADR between 2026-07-28 and today would
conclude the dead-letter was solved. It was not, and it grew 5.4× while the document said otherwise.
**An ADR must describe what is merged; a design that lives on a branch is a proposal, whatever the
branch's test count says.**

### The premise: re-measured 2026-08-09

Same spool root, read-only:

| quantity | 2026-07-27 | 2026-08-09 |
|---|---|---|
| dead-lettered jobs | 586 | **3166** |
| distinct transcripts | 533 | **1367** |
| transcripts still on disk | 533 / 533 (100%) | **205 / 1367 (15%)** |
| repeats per transcript | "max 5; not one file looping" | **max 82** (also 65, 56, 45, 35) |
| error text | 100% `no_safe_boundary` | 100% `no_safe_boundary` |

And the measurement the 2026-07-27 "Suggested next steps" asked for, finally taken — bytes past the cursor,
for the 581 dead-lettered jobs whose transcript still exists:

| | |
|---|---|
| **cursor already at EOF (delta = 0)** | **558 — 96%** |
| median bytes behind the dead-letter | **0 B** |
| p90 | **0 B** |
| jobs over 10 KB | 22 |
| max | 981,572 B |

**96% of the dead-letter has nothing to recover.** These are deterministic failures recorded for sessions
that were ingested in full. The 2026-07-28 amendment justified force-close with "a dead session's open tail
that is never recovered even when it holds turns"; today the median such tail is zero bytes. The tail the
policy exists to rescue is, in the common case, not there.

### The loss is real — but it is not the dead-letter, and it is not a tail

> **CENSUS SUPERSEDED 2026-08-10.** The entry-shape count below (48, 3.2%) is structurally blind to
> files that were ingested successfully before freezing — they keep a healthy-looking entry and lose
> content anyway. Do not read 3.2% as the size of the defect. No replacement figure is defensible
> today; see the 2026-08-10 amendment.

The table above answers the question the 2026-07-27 note asked, and that question turns out to be the wrong
one. Counting bytes *behind a dead-lettered job* measures the noise. The defect shows up somewhere else
entirely: in the **shape of the state entry**.

A successful ingest writes `hash`, `last_ingested`, `node_ids`, `session_id`, `user_turns`. An entry holding
**only `end_offset`** means the cursor was advanced with nothing ingested. Across both state files
(1485 entries):

| entry shape | count |
|---|---|
| full ingest record (9–10 keys) | 1436 (96.7%) |
| **`end_offset` alone — never ingested** | **48 (3.2%)** |

Of those 48: **19 transcripts still exist, totalling 7,033,688 B**, and **29 are already gone from disk** —
irreversible, volume unknown. None is a subagent transcript (`_is_subagent_transcript` was checked; 0 of 19).
Cross-checked against the store: **zero nodes** for every one of the 12 largest sampled, in a store of
35,126 nodes. Twelve of the 19 have the **cursor at EOF**, so the `prev_offset >= size` short-circuit skips
them forever unless the file grows again.

This is not a lost tail. A 1.3 MB transcript with its cursor at 25% and no node in the store means the
*whole conversation* never entered memory. The 2026-07-28 amendment described this exact mechanism, and was
right:

> *"`_mark_frozen_prefix_consumed` advanced the cursor to mean 'stop re-selecting this' — two different
> things, and conflating them opened a TOCTOU with **permanent** loss"*

That half stands. **Advancing the cursor must never be the way to suppress selection** — which is why the
"Parking no longer consumes bytes" rule in that amendment is kept, while the force-close machinery around it
is not. The two were bundled; only one was load-bearing.

*Known since 2026-08-10 — see the amendment at the end of this document:* the ingest fails because the
predicate's parse is windowed by the accepted `boundary`, so a turn whose terminator lands past that
boundary is refused and the delta closes nothing. Resetting cursors is still **not** authorised: the
cause is closed, but no measurement can yet say which entries lost content.

### Why the design did not converge — the cascade

Worth recording as process, not just as outcome. The branch took 18 commits and **56 distinct council
rounds** (`council-a`…`council-bc`, plus `R1`–`R12`, cited at 119 points in its test file). Read in order,
each commit repairs the mechanism the previous one introduced:

force-close → mass duplication → `force_closed_until` watermark → silent loss → park → stranding on
acceptance-only roots → generation identity on the park token → versioned prefix digest → binding that
digest to the cursor.

The amendment above names the root without recognising it as one:

> *"a watermark that suppresses the rewind trades duplication for **silent loss** unless the ordering is
> exact."*

A correctness argument that rests on exact ordering across five coupled mechanisms does not converge under
adversarial review, and did not. **Non-convergence across many review rounds is evidence about the design,
not a sign of rigour in the implementation.** A sound design converges: round 1 finds much, round 3 finds
nothing.

### What replaces it

Two independent problems, deliberately kept apart — bundling them is what produced the cascade.

**A. The noise (3166 jobs, 96% benign).** The 2026-07-27 "Suggested next steps" already had this one:

> *"A minimal re-drain policy, not necessarily all of slice 3. (…) Re-admitting a dead-lettered job once its
> transcript has grown a safe boundary would drain most of the 533 without any new policy surface."*

Stop dead-lettering the normal end-of-session path, and re-admit on growth. No watermark, no park token,
no prefix digest, no choke point.

**B. The loss (48 entries, 7 MB still recoverable).** Re-admission does **not** fix this and must not be
sold as if it did: twelve of the nineteen have the cursor at EOF, so no amount of re-admission re-selects
them, and the bytes *behind* the cursor are unreachable by construction. This one needs, in order:

1. **A cause.** What fails the ingest before `_mark_frozen_prefix_consumed` runs? Unknown today. Repairing
   the cursors without it just refills the set.
2. **The rule from 2026-07-28 that survives**: suppression of selection is never expressed by moving the
   cursor. Whatever replaces `_mark_frozen_prefix_consumed` writes a suppression fact, not an offset.
3. **A one-off recovery** of the 19 live transcripts, decided separately and with a backup — it writes to
   production state, and 12 of them are one file-rotation away from being unrecoverable.

The force-close idea is not forbidden, but it needs its own measured problem. The one it was built for —
a dead session's recoverable open tail — has a median size of zero.

### Newly measured, and not previously known: recoverability expires

In July every dead-lettered transcript was still on disk, and this ADR concluded "each is recoverable by
hand — the job preserves `path` and `boundary`". Today **85% of them are gone**. Transcripts are rotated;
the recovery window is on the order of two weeks and nobody had measured it.

This is no longer only a theoretical worry. **29 of the 48 never-ingested entries have already lost their
transcript** — content that provably never reached the store, and whose bytes are now gone. Their volume is
unknown and unknowable; the surviving 19 average ~370 KB each, which is the only guide there is.

*Still unverifiable, and the largest open uncertainty:* whether the vanished *dead-lettered* transcripts
(the 85% of 1367) carried content. If the surviving proportion held for them — 96% already at EOF — almost
nothing was lost there. That is an inference, not a measurement, and it can no longer be made into one.
Note that it says nothing about the 29 above, which are a different and confirmed population.

### Status of the branch

`feat/adr-0004-slice3-force-close` stays on `fork` as a record and is **not** merged. Its 3397 lines of
tests remain the best available catalogue of how the simple design fails, should force-close ever be
revisited on real evidence.

Full audit: `docs/auditoria-2026-08-09-adr-0004.md`.

## Amendment 2026-08-10 — the cause is found: the frozen-prefix jump is a WINDOWED-parse artefact

The 2026-08-09 amendment closed with an open question it called gating:

> *"Not yet known, and it gates any repair: what makes the ingest fail in the first place, before
> `_mark_frozen_prefix_consumed` ever runs."*

**It is now known.** Verified independently three times — by the author reading the call path, and by
both council peers on separate routes (council run `d5d9b0cb-0cb7fc71-dd137674`, 2 rounds; Cursor
conceded its own opposing R1 finding after reading the parser contract). Line numbers pinned at
`0cb7fc7`.

### The mechanism

The predicate that authorises the jump does **not** parse to EOF. It parses a **window**:

```python
parsed = parse_transcript(path, start_offset=cursor, stop_offset=boundary)   # session_watcher.py:1519
return parsed.safe_end_offset <= cursor                                      # :1522
```

`stop_offset` is an absolute ceiling, not a budget — `parser.py:251` states it, and
`_exceeds_ceiling` (`parser.py:318`) enforces it, refusing *even the first turn of a slice*.
`_safe_end` starts at `start_offset` (`parser.py:271`). So when a user turn opens at the cursor and
its terminator lands past `boundary`:

1. every turn is refused by the ceiling → `safe_end_offset == cursor` exactly;
2. the predicate is TRUE → `_mark_frozen_prefix_consumed` runs (`session_watcher.py:1476`, `:1482`);
3. the cursor advances to `min(boundary, size)` (`:1539`, `:1544`) — **over the prompt bytes that
   opened the refused turn**;
4. a later whole-file parse closes that turn. The stored `user_turns` never counted it.

`boundary` is never `None` on this path in production: `SpoolJob.boundary: int`
(`ingest_spool.py:47`) and `enqueue(..., boundary: int, ...)` (`:109`) are both non-optional. The
unwindowed case does not arise.

This is not a new defect. It is the missing first half of the 2026-07-28 diagnosis, which described
what the cursor did but not what made the ingest fail beforehand.

### Retracted: the entry-shape census understates the defect

The 2026-08-09 amendment measured the defect by entry shape — "`end_offset` alone — never ingested",
48 of 1485 (3.2%). **That census is structurally blind to part of the loss, and the 3.2% must not be
read as the size of the defect.**

`entry = dict(self._state.get(rel, {}))` (`session_watcher.py:1543`) starts from the *existing*
entry. It is empty only when the file had no prior entry. A file ingested successfully **before** it
froze keeps `hash`, `node_ids`, `session_id` and `user_turns` — and `:1544` advances the cursor over
unconsumed bytes anyway. The resulting entry is **indistinguishable in shape from a healthy ingest**,
so the shape census cannot see that population at all.

**No replacement number is published here, deliberately.** Both peers rejected every candidate
measurement: per-slice `user_turns` accumulation is not identical to a whole-file parse (the inverse
case is observed), overcount and real loss coexist inside a single entry and mask each other, and
parser-version drift produces a positive deficit with no cursor jump at all. The honest quantity
today is an **unattributed net discrepancy**. Selecting cursor repairs by that quantity would rewrite
healthy entries and miss damaged ones — so no repair is authorised by this amendment.

Two supporting facts, corrected while measuring:

- A shrink-confirmed reset does **not** restart `user_turns`: `session_watcher.py:955` keeps
  `dict(existing or {})` and updates only `hash`/`end_offset`. The surviving counter is a
  stale-generation confounder — the opposite of a reset.
- The systematic ~800-900 B gap between a stored cursor and a whole-file `safe_end_offset` appears
  in entries with **no** loss at all, so it never was evidence for the mechanism. It is plausibly
  the trailing open span consumed by the jump, but that attribution is unproven.

### Narrowed: `_mark_frozen_prefix_consumed` is not the only writer of the `{end_offset}` shape

The single-origin claim, as previously worded, is false. `session_watcher.py:937` adds
`shrink_pending` to an existing entry, and `:966` removes it again before committing — so an entry
that was already `{end_offset}` passes through `{end_offset, shrink_pending}` and is persisted back
as **exactly** `{end_offset}` by a second call site.

The defensible claim is narrower: *`_mark_frozen_prefix_consumed` is the only origin of a **newly
created** exact-shape entry with no exact-shape ancestry.* The causal conclusion survives; the proof
table did not.

### What is unaffected

The accepted decision (client nudges, server owns the Cursor, one always-on worker), the 2026-07-22
spool amendment, the rule that **suppression of selection is never expressed by moving the cursor**,
and the 2026-08-09 finding that recoverability expires within roughly two weeks — all stand
untouched. The recovery window is the item with a clock on it.

## Amendment 2026-08-11 — H1's "retry forever" has a hard stop at attempt 1025, and a deleted transcript never reaches the dead-letter

H1 — *an outage must never discard real data* — is the rule the spool's failure classing exists to serve:
`external` retries forever with persisted backoff, everything else is deterministic and dead-lettered at
once (`ingest_spool.py:234-243 @ 67f70d4`). Both halves are wrong in the code as shipped, and the two
defects compose into a queue that neither retries nor records. Observed in production on 2026-08-11:
**1040** occurrences of `Ingest drain run error: int too large to convert to float` between 03:37:18 and
09:46:43, across 8 jobs, zero in the three preceding rotated logs.

### The backoff cap is applied after the exponentiation, so it never guards the arithmetic

```python
delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), _BACKOFF_MAX_SECONDS)  # ingest_spool.py:247
```

`2 ** (attempts - 1)` is an arbitrary-precision `int`; `min(…, 300.0)` runs only on the product. Once
`attempts - 1` crosses the float range the multiplication raises before any capping happens. Reproduced
by execution: `attempts=1024 → 300.0`, `attempts=1025 → OverflowError: int too large to convert to float`
— verbatim the logged message.

`requeue` raises before `self._write_job(name, payload, _PENDING)` (`ingest_spool.py:272`), so **no
retry is ever persisted**. This is not a cap that dead-letters — the outcome the docstring argues
against — it is a break that strands. The distinction matters: a dead-letter is a record, this is
neither progress nor record.

At the 300 s ceiling, attempt 1025 arrives after roughly 3.5 days of continuous retry. **Any** genuine
provider outage of that length hits the same wall, not only the deleted-transcript case below. The rule
this ADR exists to protect fails precisely in the scenario it was written for.

### A deleted transcript is classed as an external failure, against the contract

```python
except OSError as e:
    logger.warning("Cannot read %s: %s", path, e)   # session_watcher.py:879
    return IngestResult.TRANSIENT                   # :880
```

`FileNotFoundError` is an `OSError`, so a permanently deleted transcript is indistinguishable from
`EIO`/`EACCES` here and becomes `TRANSIENT` → `requeue(job, failure_class="external")` → retried
forever. `requeue`'s own contract says the opposite in as many words: *"deterministic (malformed job,
**transcript deleted**, path no longer under any watch root): a retry cannot change the outcome, so the
job is dead-lettered immediately"* (`ingest_spool.py:241-242`). The code contradicts its own docstring.
This is what fed the 8 jobs to attempt 1025 in the first place.

### The stranded job is re-admitted with no backoff, which is why it repeats

The drain's own recovery keeps the broken job alive rather than quarantining it. `_run_job` raises →
the handler tries `requeue` again (`session_watcher.py:1419-1420`) → same overflow, suppressed → the job
stays in `running/` → the idle branch's `self.spool.recover(min_age_seconds=self._recover_stale_seconds)`
(`:1401`, 60 s at `:1326`) renames it back to `pending/` (`ingest_spool.py:337`) **with the original
payload**, whose `not_before` elapsed long ago → immediately claimed → same overflow. A ~60 s cycle per
job, not a CPU spin, and permanent: the backoff that would slow it is exactly what fails to be written.

This is a third-order consequence, not a separate defect. It disappears once the arithmetic stops
raising; adding machinery here would treat the symptom.

### How it ended, and what that cost

The loop stopped because the spool was **deleted**, not fixed: every `ingest_queue/<root>/` subdirectory
carries an mtime of 09:47, matching the 09:47:16 restart that recreated them. The 8 jobs are gone. Their
transcripts were already unreadable — that is what jammed them — but whether any carried unconsumed
content is now unknowable, and the deletion was indiscriminate: a legitimate job queued in that window
would have gone with them. Manual destruction of the queue is the failure mode H1 forbids, arrived at
from the opposite direction.

*Not verified:* the log records four distinct paths across the 8 jobs, so the assumption that all eight
were deleted transcripts is inference, not measurement. The queue is gone; it cannot be made one.

### What this does not change

The accepted decision stands, and so does the directory spool: the failure is in two expressions inside
it, not in the choice of a spool over a job table. The 2026-08-10 windowed-parse cause is untouched —
that defect moves the cursor over unconsumed bytes, this one refuses to retry a job at all; they share
no mechanism. The repair order stated on 2026-08-09 (cause before repair) also holds here: both fixes
are small and their cause is now measured, which is the difference between this amendment and the
force-close one.

## Amendment 2026-08-12 — the windowed-parse defect reproduces post-wipe; neither fix from 08-09/08-10 has shipped

The 2026-08-11 amendment's "how it ended" section left an open question: whether the queue deletion also
ended the windowed-parse defect it wasn't targeting. It did not — this is a fresh reproduction, not
residue from before the wipe.

**Observed:** two `no_safe_boundary` dead-letters in `ingest_queue/66b287858fdea3e3/failed/`, both created
2026-08-12 (after the 08-11 09:47 queue recreation): `reason: drain` at 12:56 (`boundary=796621`, the
transcript at `.../Tools-ormah/a861349c-….jsonl` — the session that produced the prior handoff) and
`reason: nudge` at 11:29 (`boundary=379845`, `.../AndreMartins/8b53f0ac-….jsonl`). Both transcripts are
still on disk, both larger than their recorded boundary today (job 1: transcript now 1,200,759 B vs.
boundary 796,621 — 404 KB of growth since the dead-letter; job 2's transcript also intact). Per the
2026-08-10 finding, both are consistent with the cause already identified: a user turn opening before the
windowed `boundary` with a terminator past it, refused by `_exceeds_ceiling`, cursor advanced over the
refused prompt by `_mark_frozen_prefix_consumed`.

**Confirms:** neither shipped fix from the 08-09/08-10 amendments — (A) re-admit-on-growth for the benign
majority, (B) a suppression-fact mechanism replacing the cursor-advancing park — is present on `local-main`
(`grep` for `force_closed_until`/`parked_until` in `session_watcher.py`: 0 hits, consistent with the
08-09 amendment's symbol table). The defect is not historical; it is the live behavior of the code that
ships today.

**Recoverability, both jobs:** unlike the 08-09 population (85% of transcripts already rotated off disk),
both of today's two transcripts are present and growing — recoverable by hand per the same mechanism the
08-09 amendment describes (`path` + `boundary` on the dead-lettered job). No recovery was performed here;
this amendment only records the reproduction. **The clock the 08-09 amendment measured (~2-week window)
applies to these two starting today, 2026-08-12.**

**No code change made.** Decided explicitly: further work on this ADR (implementing Fix A, Fix B, or a
manual recovery of these two jobs) requires `superpowers:brainstorming` first, per this repo's standing
rule that any behavior change starts there — not a continuation of this reproduction.

## Amendment 2026-08-13 — Fix B ships: suppression is a fact about the file, not a cursor advance

The mechanism the 08-09 and 08-10 amendments identified is repaired and merged into `local-main`
(`d566478`). This amendment records what shipped, corrects one thing the 08-11 amendment leaves
standing, and — deliberately — **withdraws** an errata this work had intended to write.

### What shipped

`_mark_frozen_prefix_consumed` is gone. It expressed "stop re-selecting this file" by advancing
`end_offset`, which claims bytes nothing ingested — the loss this ADR has been circling since
07-28. Its replacement, `_mark_frozen_prefix_parked`, writes a *suppression fact* and leaves the
cursor alone:

- `frozen_until` — the ceiling the examination reached, never past the accepted `boundary`.
- `frozen_ino` / `frozen_mtime_ns` / `frozen_ctime_ns` — the identity of the file that was examined.

Both producers skip through one shared predicate, `_frozen_unchanged`, which is true only while the
file is byte-for-byte the one examined. Any change — growth, shrink, or replacement at the same
byte count — re-selects it, and the parse resumes from the **untouched** cursor. The fact is
cleared on a confirmed shrink and on a successful ingest.

| commit | |
|---|---|
| `a0b8997` | the park writes the fact; the cursor is never moved |
| `5aca3fd` | regression net for the plan review's rounds 2 and 3 |
| `b2ff755` | `_frozen_unchanged` + `reconcile` uses it |
| `33af30b` | the Observer lane uses the same predicate, not a copy |
| `df9c751` | the fact is cleared at both commit sites |
| `feecf20` | `reconcile`'s `>=` arm is left as found — see *Not shipped* |
| `54550a1` | the ceiling must not survive an mtime-preserving in-place shrink |
| `7e83d0c` | `ctime` joins the identity: `(size, inode, mtime_ns)` is not byte identity |

Verified at merge: 140 passed in the watcher suite (125 before this work), 2477 passed in the full
suite with only 7 pre-existing failures that also fail on `local-main` without any of this applied
(`tests/test_setup.py`, `tests/test_cloud_settings.py` — none touches `session_watcher.py`), `ruff`
clean on both touched files. `ingest_spool.py` is byte-identical: the `no_safe_boundary`
dead-letter behaviour and its volume are untouched by design, as Fix A remains separate.

The last two of those commits are worth naming, because both were found by the Dev Council
**after** three rounds of plan review had signed the design off, and each is a defect the plan
review's own regression tests could not reach:

- `54550a1` — the park's identity was `(inode, mtime_ns)` and omitted the size. An in-place
  `truncate` keeps the inode and `utime` restores the mtime, so a shrunk file kept the larger
  ceiling and `frozen_until == st_size` could never hold again: every sweep re-selecting and
  re-dead-lettering, unbounded `failed/`. This is precisely what plan round 3 claimed to have
  closed; its test replaces the file, which changes the inode, so the in-place path was
  unreachable by it.
- `7e83d0c` — an in-place rewrite of the *same length* with the mtime restored stayed suppressed,
  stranding every turn that rewrite closed. `st_ctime_ns` closes it: the kernel bumps it on any
  inode change and userspace has no API to set it. Upstream documents the same hole and accepts it
  *"[because] closing it means hashing every consumed file each tick"* — a false choice, as it
  costs one `stat` field.

### Correction to the 2026-08-11 amendment

Both defects that amendment describes are **fixed and merged**, and it does not say so:

- the backoff exponent clamp — `8438242`, with `_BACKOFF_MAX_SHIFT = 62` at `ingest_spool.py:43`
  and the clamp applied *before* the exponentiation at `:253`;
- the deleted transcript reaching the dead-letter as a deterministic failure — `9882872`, with
  `requeue(job, failure_class="transcript_deleted")` at `session_watcher.py:1536` and `:1582`.

Both are on `local-main` and both are present in the running code.

### Not shipped, deliberately: `reconcile`'s `>=`

`reconcile`'s cheap-skip arm still reads `(entry.get("end_offset") or 0) >= st.st_size`, so an entry
whose cursor sits **above** EOF is treated as fully consumed and dropped from the sweep — and the
two-tick shrink reset can then be armed only through the Observer, in the one component that exists
to recover dropped FSEvents. Every peer review of this work raised it.

It was in the branch as `>=` → `==` and was removed on measurement. Upstream has used `==` since
`4d8de6d` (2026-07-17) and never had `>=`, so the `>=` is Beta-local drift — but upstream pairs
`==` with an in-memory retry park (`_reconcile_attempts`, keyed on `(size, mtime_ns)`, bounded by
`MAX_RECONCILE_RETRIES`) that this codebase does not have, at 0 occurrences. Measured 2026-08-12
against the live state: 16 entries hold a cursor above EOF; **3** have an unchanged hash and would
re-enqueue forever, because `_ingest_session`'s guard returns `NO_PROGRESS` before the shrink branch
when the hash matches; the other **13** would reset to offset 0 and re-ingest **59.0 MB**, largest
file 40 MB. Seven of those 13 sit at exactly **83 bytes** above EOF, across files from 392 KB to
40 MB — a constant offset across unrelated files is not a shrink but an unexplained cursor
overshoot.

One consequence of this work runs the *other* way, and was checked rather than assumed: parking is
possible only while `st_size > cursor`, and the new park never writes `end_offset`. The predecessor
advanced the cursor toward the frozen boundary, giving a later shrink a *higher* cursor to fall
below. Leaving the cursor still **shrinks** the cursor-above-EOF population rather than feeding it.

Tracked, with the census and an ordering — find the 83-byte write path first — in
`AndreLFSMartins/ormah#2`.

### Withdrawn: the errata this amendment was going to carry

This work set out to correct the 2026-08-12 amendment above, on the claim that its two cited jobs
(`boundary=796621`, `boundary=379845`) did not exist in the spool and that the real population was
3806 jobs over 1619 transcripts with payloads from 2026-07-24 onward. **That correction is
withdrawn, because it cannot be substantiated.**

Measured 2026-08-13: `failed/` holds **2** dead-lettered jobs, both `no_safe_boundary`, both created
today at 08:52 and 08:54, both under `ingest_queue/66b287858fdea3e3/`, on transcripts in
`-Users-andre-Documents-Obsidian-AndreMartins`. The other root is empty. Nothing in
`ingest_spool.py` ever removes a file from `failed/` — it writes the job there with its original
bytes and an `.error` sidecar, and never unlinks — so the population did not shrink by any action of
the code. The spool is also not covered by `backup.py`, which never mentions `ingest_queue`.

So the queue was destroyed externally a second time, some time between 2026-08-12 and 2026-08-13
08:50, exactly as the 08-11 amendment records for the first occasion — and with the same result:
**neither the figures in the 08-12 amendment nor the figures that would have corrected them can now
be verified or refuted.** The 08-12 amendment therefore stands as written. Its numbers are not
confirmed here; they are simply no longer falsifiable, which is a different thing and is recorded as
such.

*The lesson is the same one the 08-11 amendment drew and is worth restating, because it has now cost
evidence twice:* manual destruction of the queue is the failure mode H1 forbids, arrived at from the
opposite direction. A retention policy that prunes `failed/` deliberately — with a record of what it
removed — would be strictly better than the current combination of never pruning and being wiped.

### Verification in production — confirmed by a second reading

Recorded at merge time, 2026-08-13: **1815** state entries, **75** holding only `end_offset`, **0**
holding `frozen_until`. The first count was also 75 when measured on 2026-08-12 against 1791
entries, which is the one figure from that measurement reproduced by an independent route here.

The claim this change makes is that the 75 stops rising and entries carrying `frozen_until` with an
intact cursor begin to appear. The Beta was restarted onto the merged code at 09:14:34.

A second reading, taken independently later the same day: **1817** state entries, **75** holding
only `end_offset` (unchanged), **1** holding `frozen_until`. The one `frozen_until` entry has
`end_offset` 647504 < `frozen_until` 647730 — the cursor is intact, not clamped to the ceiling —
plus `frozen_ino`/`frozen_mtime_ns`/`frozen_ctime_ns`, matching the design. This is a single
occurrence, not volume under sustained load, but it is the mechanism firing correctly in production
for the first time. **The change is now verified by production, not only by its test suite.**

### Still open

> **SUPERSEDED 2026-08-13** by the "Fix A ships" amendment below — item 1 (Fix A) is done;
> read that amendment's own "Still open" list for the current state.

- Fix A — the `no_safe_boundary` dead-letter noise, re-admit-on-growth. Untouched by design.
- Recovery of the content already lost: 14 transcripts / 5.92 MB / 23 closed user turns, per the
  2026-08-12 measurement. Its own spec, and the ~2-week rotation clock still applies.
- The 54 transcripts the parser closes nothing in even unwindowed — parser coverage, its own spec.
- `AndreLFSMartins/ormah#2` — the cursor-above-EOF class and the 83-byte overshoot.
- A test hole, known and deferred: mutating `_frozen_unchanged`'s `== st.st_size` to `<=` leaves the
  whole suite green while re-introducing the loss mode this amendment closes.

## Amendment 2026-08-13 — Fix A ships: the `no_safe_boundary` dead-letter is retired, not just re-admitted

The design this amendment implements is `docs/superpowers/specs/2026-08-13-adr-0004-fix-a-no-safe-boundary-noise-design.md`,
approved via `superpowers:brainstorming` per the 2026-08-12 amendment's explicit gate.

**Merged and running.** Branch `fix/adr-0004-fix-a-no-safe-boundary-noise`, cut from
`local-main` at `8887476`, fast-forwarded into `local-main` on 2026-08-13. Five commits:

| commit | |
|---|---|
| `ac634a2` | the park completes instead of dead-lettering; 10 tests (TDD, RED→GREEN) |
| `622445c` | the park log is `info`, not `debug`, and prints the ceiling actually persisted |
| `a0d4c84` | this amendment's first draft |
| `468d38e` | **`PARKED` must mean the fact is on disk** — see the section below |
| `a5edead` | corrects the durability claim `468d38e` invalidated, plus two overstatements |

The Beta was restarted onto the merged code at 14:15:51 (pid 42663) and verified by importing
from the server's own interpreter: `ParkOutcome` present with its three members, exactly **one**
`return ParkOutcome.PARKED` in `_mark_frozen_prefix_parked`, and the unsafe short-circuit
absent.

### What Fix A closes

- **The `no_safe_boundary` dead-letter class is retired at its only production call site.** A
  confirmed park is no longer a spool-level failure: it completes. `failed/` stops accruing the
  96%-benign end-of-session path (measured 2026-07-27) — which was never a loss backlog, only
  noise that masked real failures.
- **The 2026-08-09 amendment's item A** ("the noise — 3166 jobs, 96% benign", whose suggested
  remedy was re-admit-on-growth) is closed, and closed *differently* than suggested: Fix B's
  `frozen_until` fact already re-selects on growth through both producer lanes, so a second
  re-admission mechanism was never needed. Retiring the record beat re-draining it.
- **A refused park can no longer discard a job.** This is new safety Fix A had to add rather
  than inherit: the disposition is now explicit (`ParkOutcome`), so the two refusal paths reach
  `transcript_deleted` or a persisted-backoff `external` retry instead of falling into
  `complete()`.
- **`IngestSpool` is unchanged.** The generic dead-letter mechanism still serves
  `transcript_deleted` and any future deterministic class; only one caller stopped using it.

### What shipped, and why it is not the design's original shape

The approved design was a one-line disposition swap: when
`_mark_frozen_prefix_parked` confirms the suppression fact, call `spool.complete(job)`
instead of `spool.requeue(job, failure_class="no_safe_boundary")` — retiring the dead-letter
entirely rather than re-admitting it on growth (the design supersedes the 2026-08-09
amendment's "minimal re-drain policy" suggestion: Fix B's `frozen_until` fact already makes
growth re-select the file through both producer lanes, so a *second*, redundant re-admission
mechanism was never needed once Fix B shipped).

That one-liner never shipped. Five adversarial rounds across two phases — three on the plan
(`/council`, before any code) and two on the diff (`/council-pr`, after) — each found the same
failure in a new place: **a park that is not confirmed must never reach `complete()`**, or a job
vanishes with neither a durable fact nor a spool record, which is exactly the loss class this
whole ADR exists to close. The three plan rounds:

- **R1 (codex):** `_mark_frozen_prefix_parked` returns `None` on refusal (file deleted, or
  changed identity, between `_idle_with_unsafe_tail`'s examination and this method's own
  re-stat) as well as on success — the original one-line swap could not tell the two apart.
- **R2 (codex + cursor, independently, same defect):** the R1 fix (a `bool` return plus a
  fresh `path.exists()` re-check at the call site) reopened a narrower version of the same
  race: a delete-then-recreate between that re-check and the pre-existing lower guard could
  still reach an unconditional `complete()`.
- **R3 (codex):** a *different*, pre-existing race in `_idle_with_unsafe_tail`'s own `None`
  return (any reason, including its own `stat()` failing) — verified independently to be
  unmodified by this change and identical with or without it. Deliberately deferred; see
  "Still open" below.

Then the code was written, reviewed per-task, reviewed whole-branch (opus), and only *then* put
to the peers again as a diff. Both PR rounds still found something:

- **PR-R1 (codex, 0.96):** the `PARKED`-without-a-write short-circuit — the one defect in this
  whole sequence that had already been *cleared* by two prior reviews. Accepted and fixed
  (`468d38e`); it has its own section below, because how it survived matters more than what it was.
- **PR-R2 (codex):** escalated to the window between `_commit_state` returning and
  `spool.complete()` executing. Rebutted on the ground that the untouched `IngestResult.OK` path
  carries the identical window and is byte-identical pre-Fix-A, and that the remedy is the
  transactional store the 2026-07-22 amendment already rejected with measurements. **Codex
  conceded** it does not block Fix A; recorded under "Still open" as a lane-wide property.

The pattern is worth naming, because it contradicts the lesson the 2026-08-09 amendment drew
from the force-close cascade. There, non-convergence was evidence the *design* was wrong. Here
each round found a defect in the *previous round's fix*, and the sequence converged on a shape
that is smaller and more obviously correct than any intermediate one — the disposition decided
once, at one site, verifiable by structure. The distinguishing signal is not "how many rounds"
but whether the fixes are converging on fewer moving parts or accumulating more.

**What shipped instead of the one-liner:** `_mark_frozen_prefix_parked` now returns a
`ParkOutcome` enum (`PARKED` / `GONE` / `RETRY`), decided **inside** the method from the
single `stat()` it already performs — `FileNotFoundError` → `GONE`, any other `OSError` or an
identity mismatch → `RETRY`, a confirmed fact → `PARKED`. The call site dispatches once on
that value with a `return` in every branch and never re-checks `path.exists()` — closing the
race structurally rather than by ordering two checks correctly. `GONE` dead-letters as
`transcript_deleted` (an existing class); `RETRY` gets the same persisted-backoff `external`
requeue the neighboring `shrink_pending` race already gets, for the same acceptance-only-root
reason. `IngestSpool` itself is untouched.

**Verified on the merged `local-main` (`a5edead`), not on an intermediate commit:** `make test`
→ **2512 passed**, 12 deselected, 0 failures. That is the pre-Fix-A baseline of 2503 plus
exactly the 9 tests this work added (8 with `ac634a2`, 1 with `468d38e`) — the arithmetic is
stated because it is the check that the count moved for the reason claimed.
`test_session_watcher.py` alone: 149 passed. `ruff` clean on both touched files.

*A verification trap worth recording, since it produced a fully plausible false result before
being caught:* `Tools/ormah`'s shared `.venv` is editable-installed against the **main**
checkout, so running the suite from a worktree silently tests the main repo's source instead.
The first run of this work's own `-k` selector "failed 10 tests" against code that had never
been touched. Every figure above comes from an interpreter confirmed with
`python -c "import ormah; print(ormah.__file__)"`. The final whole-branch review reproduced
this trap independently.

The final whole-branch review (opus) confirmed the R3 deferral is accurate:
`_idle_with_unsafe_tail` and the `shrink_pending` / `path.exists()` / final-`complete()`
fallthrough below the dispatch are untouched by this change.

**Not yet verified: production.** Fix B earned a "verified by production" note by watching the
live state file until entries carrying `frozen_until` appeared with intact cursors. Fix A has
no equivalent reading yet — the Beta has only just been restarted onto it. The claim to test is
that `failed/` stops accruing `no_safe_boundary` entries while parks continue to be recorded.
Until someone takes that reading, this amendment is verified **by its test suite and by the
running import**, not by production.

### The `PARKED` short-circuit: cleared by two reviews, and wrong — `468d38e`

Worth recording as a review lesson, not only as a fix. `_mark_frozen_prefix_parked` had an
"already recorded, identically" branch that returned `PARKED` **without writing**, on the
argument that `_commit_state` persists to disk before publishing to the in-memory `_state`
dict — so memory could never be ahead of disk. Both the final whole-branch review (opus) and
the `/council-pr` R1 peer (cursor) examined that exact line and cleared it, each restating
that same argument.

The argument is true and does not prove what it was used for. It proves memory cannot lead
disk **at the moment of writing**. It says nothing about disk falling **behind** memory
*afterwards*: `self._state` is loaded once at handler construction (`_load_state`, ~`:1386`)
and never re-read, so a state file destroyed, rolled back, or overwritten by another process
leaves memory asserting a fact that no longer exists on disk. With Fix A, that stale `PARKED`
reaches `spool.complete()` — the job unlinked with neither a fact nor a record. And it was
**newly reachable**: before Fix A this path dead-lettered, so a record always survived.

Found by Codex (`/council-pr` R1, 0.96), confirmed by reading, fixed in `468d38e` by deleting
the short-circuit. `PARKED` now returns only after a successful `_commit_state` — durable **by
construction**, verifiable by structure rather than by argument: exactly one
`return ParkOutcome.PARKED` exists, immediately after the commit. A failed write raises,
propagates to the drain's handler, and requeues as `external` (persisted backoff, never
dead-lettered) — the H1-correct outcome. Cost is one state write per re-park of an unchanged
file, a path both producer lanes already gate with `_frozen_unchanged`.

*The lesson, since two independent reviews cleared this line:* a durability argument must name
the window it covers. "Persist before publish" is a claim about one instant; the invariant
needed here was about an interval.

### Operational signal, corrected before merge

The design specified `logger.debug` for the park-confirmed log line, calling it "the cheap
substitute" for the removed `grep no_safe_boundary failed/*.error`. The final review found
that substitute does not exist under this project's default log level (`INFO`) — a default
deployment gets neither the old `.error` sidecar nor the new log line. Promoted to
`logger.info` before merge (park is per-idle-session frequency, not hot-path, so the volume is
defensible). The log line was also found to print `job.boundary` rather than the ceiling
actually persisted (`min(boundary, size)`, further ratcheted on a re-park) — now reads the
value `_mark_frozen_prefix_parked` actually wrote to state.

### The 2026-08-12 census, re-measured 2026-08-13

The 2026-08-12 census (in the Fix B design spec) is what the two remaining content items are
built on, and both were about to be acted on from a month-old reading. Re-measured on
2026-08-13 by the same route — for every `.session_watcher_state` entry across **both** watch
roots whose only key is `end_offset` (cursor advanced, nothing ingested), with the transcript
still on disk, run the project's own `parse_transcript` over the **whole file, unwindowed**, and
count `len(result.safe_turns)` plus its `role == "user"` subset:

| quantity | 2026-08-12 | 2026-08-13 |
|---|---|---|
| `end_offset`-only state entries | 75 | **75** — unchanged |
| of those, transcript still on disk | 68 (8,029,774 B) | **62** (8,028,919 B) |
| parser closes content the cursor skipped | 14 files / 5,923,567 B / 23 closed user turns | **identical — 14 / 5,923,567 B / 23** |
| parser closes nothing even unwindowed | 54 files / 2,106,207 B | **48 files / 2,105,352 B** |

Three things this reading establishes, none of which were true-by-assumption before it:

- **The route is the same route.** The 14-file set reproduces to the byte *and* to the turn
  (5,923,567 B, 23 user turns, 255 turns total). A re-measurement that lands on the same two
  independent figures a month later is the check that this is the census's own method, not a
  near-miss reimplementation of it.
- **The recovery window did not expire.** The 2026-08-09 amendment closes with "the recovery
  window is the item with a clock on it" (§ *What is unaffected*), and an earlier draft of the
  list below extrapolated from it that the window was by now "likely expired" — reasoning from
  a measured two-week rotation to a month-old census. That extrapolation was **wrong for this
  set**: all 14 files were still on disk, unrotated, a month on. The 2026-08-09 finding stands
  exactly as it was measured; it simply does not generalize to the files this census pinned, and
  no reading had ever been taken to check whether it did.
- **Attrition hit only the other set.** 68 → 62 on disk, and every one of the 6 lost came from
  the closes-nothing side (54 → 48) — the defect set lost nothing. Both totals fell by exactly
  855 B, so on the assumption that the surviving files did not change size, the 6 that rotated
  away were tiny (~142 B each) — consistent with the census's "single-turn sessions" cause, but
  inferred from the arithmetic, not read off the missing files themselves.

### Recovery of the lost content — retired by decision, not by repair

**Dropped 2026-08-13 by the ADR owner's explicit decision.** The 14 transcripts the census
found unrecovered will not be recovered; this is no longer an open item and should not be
reopened as one.

The reason is recorded because it is not the reason the text above would have predicted: the
content was **still on disk, byte-for-byte**, when the decision was taken. This closes as a
choice not to spend the effort — *not* as a rotation window that closed the option. The census
itself stays on the record in
`docs/superpowers/specs/2026-08-12-adr-0004-frozen-prefix-suppression-fact-design.md`, because
it is the evidence the defect existed at all; only the work item is retired.

### Still open

- **Parser coverage — 48 transcripts / 2,105,352 B the parser closes nothing in even
  unwindowed** (re-measured 2026-08-13; the census's own figure was 54 / 2,106,207 B, and the
  6-file difference is rotation, not a code change — nothing in Fix A or Fix B touches the
  parser). This is *not* a cursor-loss item: the cursor skipped nothing a parser could have
  closed, so it is out of ADR-0004's own defect class and needs its own spec. Its shape is
  lopsided and worth carrying into that spec: **4 Codex `rollout-*.jsonl` files carry 1,623,823 B
  — 77% of the bytes** — against 44 Claude Code sessions holding the remaining 481,529 B. The
  causes named by the census (Codex rollouts with no `task_complete`; single-turn sessions) map
  onto exactly that split, so per-byte the item is mostly one missing Codex terminator.
- `AndreLFSMartins/ormah#2` — the cursor-above-EOF class and the 83-byte overshoot.
- A test hole, known and deferred: mutating `_frozen_unchanged`'s `== st.st_size` to `<=` leaves the
  whole suite green while re-introducing the loss mode the Fix B amendment closes.
- **New (`/council-pr` R2, codex — lane-wide, NOT specific to Fix A):** `_commit_state`
  returning and `spool.complete(job)` executing are two statements, not one transaction. State
  destroyed or rolled back in that window leaves the job unlinked with no surviving fact. This
  is a property of the **commit-then-complete protocol itself**, not of parking: the
  `IngestResult.OK` path (`:1553-1563`) does the identical thing with the cursor advance, is
  byte-identical on `local-main` pre-Fix-A, and is far more frequent than a park. Codex
  conceded on R2 that it therefore does not block Fix A, and that closing it needs the
  durable-receipt-or-transactional-store redesign the 2026-07-22 amendment already rejected
  with measurements (`synchronous=NORMAL` does not survive power loss, so the transactional
  argument does not hold; `busy_timeout=5000` would let a nudge block 5s in the one path whose
  purpose is that nobody waits). Recorded here rather than fixed. Note the window is now
  microseconds between two adjacent statements — before `468d38e` the equivalent exposure was
  unbounded, since memory could assert an arbitrarily stale fact.
- **New (R3, this amendment):** `_idle_with_unsafe_tail` returns `None` for any reason,
  including its own `stat()` failing — a deleted-then-recreated file in that window is
  indistinguishable, at the call site, from every other `None` cause (not-yet-idle,
  unparseable, cursor already at EOF), and the *unchanged* `shrink_pending` /
  `path.exists()` / final `complete()` fallthrough a few lines below can still reach an
  unconditional `complete()` in that narrow window. Pre-existing, not introduced or widened by
  Fix A — present identically with or without it. Closing it needs a tagged return from
  `_idle_with_unsafe_tail` itself (`UNSAFE`/examined, `GONE`, `RETRY`, `NOT_APPLICABLE`, per
  Codex's R3 recommendation) so the *entire* NO_PROGRESS branch can dispatch from one
  atomically-captured result — every other NO_PROGRESS caller in this file depends on that
  method's contract, so this is a larger, separate change needing its own design, not an
  extension of Fix A's.

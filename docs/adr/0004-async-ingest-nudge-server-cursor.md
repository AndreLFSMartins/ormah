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
